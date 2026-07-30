"""End-to-end: supervisor → sandbox → ./play → runner → engine → metrics.

Drives real subprocesses over a real unix socket. Nothing is stubbed, so a
failure here means the loop is actually broken rather than a mock drifting.

The packs live in the private submodule; the tests skip when it is not
checked out, which is the normal state of a bare public clone.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HARNESS_DIR = Path(__file__).resolve().parents[1]
PLATFORM_ROOT = HARNESS_DIR.parents[2]
SUPERVISOR = HARNESS_DIR / "supervisor.py"
AGENT = Path(__file__).resolve().parent / "scripted_agent.py"

if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

PRIVATE_PACKS = Path(
    os.environ.get("GRIDPONDER_PRIVATE_PACKS", PLATFORM_ROOT / "packs-private")
)

# One introductory level and one mid-arc level per pack. The mid-arc pair is
# not redundant: it is longer, uses more of the pack's mechanics, and its
# boards are big enough that a rendering or coordinate bug has room to show.
LEVELS = [
    ("three_kingdoms", "tk_001"),
    ("three_kingdoms", "tk_006"),
    ("pincer", "pc_001"),
    ("pincer", "pc_006"),
]


def _requires(pack: str) -> Path:
    if not (PRIVATE_PACKS / pack / "game.json").is_file():
        pytest.skip(f"private pack {pack!r} not checked out at {PRIVATE_PACKS}")
    # A private pack can also need a system this branch predates. Check the
    # registry explicitly: instantiate_systems drops unknown types silently, so
    # the pack would otherwise "run" with its central mechanic missing and fail
    # here as if the harness were broken.
    from engines.python._systems import _REGISTRY
    from engines.python.loader import load_pack

    game_def, _levels = load_pack(str(PRIVATE_PACKS / pack))
    missing = sorted(
        s["type"] for s in game_def.systems
        if s.get("enabled", True) and s["type"] not in _REGISTRY
    )
    if missing:
        pytest.skip(f"pack {pack!r} needs system(s) this engine lacks: {missing}")
    return PRIVATE_PACKS


def gold_path(packs_dir: Path, pack: str, level: str) -> list[dict]:
    return json.loads(
        (packs_dir / pack / "levels" / f"{level}.json").read_text()
    )["solution"]["goldPath"]


def requires_winnable_gold_path(packs_dir: Path, pack: str, level: str) -> None:
    """Skip when the level's own action limit is shorter than its gold path.

    Such a level cannot be solved by anyone, including the agent following the
    intended solution: the lose condition fires before the winning move lands.
    That is a level defect, not a harness one, so it is called out here rather
    than reported as the sandbox failing to solve a solvable puzzle.

    `engines/python/test_gold_paths.py` does not catch it — it replays the whole
    path and checks `is_won` at the end, never `is_lost` along the way.
    """
    level_json = json.loads(
        (packs_dir / pack / "levels" / f"{level}.json").read_text()
    )
    gold = len(level_json["solution"]["goldPath"])
    limit = next(
        (c["config"]["limit"] for c in level_json.get("loseConditions", [])
         if c.get("type") == "max_actions"),
        None,
    )
    if limit is not None and limit < gold:
        pytest.skip(
            f"{pack}/{level} is unwinnable: max_actions={limit} but the gold "
            f"path is {gold} moves, so the level is lost one move before it "
            f"can be won"
        )


def anonymize(table: dict, moves: list[dict]) -> list[dict]:
    """Rewrite real moves into the aliases an anonymous agent would type."""
    alias_of = {entry["action"]: alias for alias, entry in table.items()}
    out = []
    for move in moves:
        alias = alias_of[move["action"]]
        translated = {"action": alias}
        for p_alias, spec in table[alias]["params"].items():
            value = move[spec["name"]]
            if spec["values"] is not None:
                value = next(k for k, v in spec["values"].items() if v == value)
            translated[p_alias] = value
        out.append(translated)
    return out


def run_session(tmp_path: Path, packs_dir: Path, pack: str, level: str,
                moves: list[dict], *, anon: bool = False) -> dict:
    sandbox = tmp_path / f"{pack}_{level}"
    result_path = tmp_path / f"{pack}_{level}.json"
    argv = [
        sys.executable, str(SUPERVISOR),
        "--pack", pack, "--level", level,
        "--packs-dir", str(packs_dir),
        "--sandbox", str(sandbox),
        "--result", str(result_path),
        # These tests are about the protocol and the metrics, and their agent
        # is a script in this repo, which confinement correctly hides. The
        # confinement itself is covered in test_sandbox_and_sweep.py.
        "--isolation", "none",
    ]
    if anon:
        argv.append("--anon")
    argv += ["--agent-cmd", sys.executable, str(AGENT), json.dumps(moves)]

    proc = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"supervisor failed:\n{proc.stdout}\n{proc.stderr}"
    result = json.loads(result_path.read_text())
    result["_sandbox"] = sandbox
    result["_stdout"] = proc.stdout
    return result


# ── the sandbox itself ────────────────────────────────────────────────────

@pytest.mark.parametrize("pack,level", LEVELS)
def test_sandbox_contains_only_rules_and_play(tmp_path, pack, level):
    packs_dir = _requires(pack)
    result = run_session(tmp_path, packs_dir, pack, level,
                         gold_path(packs_dir, pack, level))
    sandbox = Path(result["_sandbox"])
    # The socket is removed on shutdown, so RULES.md and play are what is left.
    assert sorted(p.name for p in sandbox.iterdir()) == ["RULES.md", "play"]
    assert os.access(sandbox / "play", os.X_OK)


@pytest.mark.parametrize("pack,level", LEVELS)
def test_rules_leak_neither_gold_path_nor_its_length(tmp_path, pack, level):
    packs_dir = _requires(pack)
    from engines.python.loader import load_pack
    from tools.benchmark.harness import rules as rules_mod

    game_def, _levels = load_pack(str(packs_dir / pack))
    gold = gold_path(packs_dir, pack, level)
    result = run_session(tmp_path, packs_dir, pack, level, gold)
    rules = (Path(result["_sandbox"]) / "RULES.md").read_text()

    # Each action gets one fixed example call, built from game.json's declared
    # parameters and nothing else. It is the same on every level of the pack,
    # so when it coincides with a gold move (pincer's `move` example is "up",
    # and pc_006 steps up) that is arithmetic, not a leak. Anything else
    # matching a gold move would mean the level's solution reached RULES.md.
    boilerplate = {rules_mod._example_json(a) for a in game_def.actions}
    for move in gold:
        rendered = json.dumps(move)
        if rendered in boilerplate:
            continue
        assert rendered not in rules
    assert f"{len(gold)} moves" not in rules
    assert f"{len(gold)} actions" not in rules


# ── solving ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pack,level", LEVELS)
def test_gold_path_solves_the_level_through_the_sandbox(tmp_path, pack, level):
    packs_dir = _requires(pack)
    requires_winnable_gold_path(packs_dir, pack, level)
    gold = gold_path(packs_dir, pack, level)
    result = run_session(tmp_path, packs_dir, pack, level, gold)

    assert result["solved"] is True
    assert result["actions_total"] == len(gold)
    assert result["attempts"] == 1
    assert result["rejected_schema"] == 0
    assert result["rejected_illegal"] == 0
    assert result["first_divergence"] is None
    assert result["efficiency"] == 1.0
    assert result["tier"] == "trivial"


@pytest.mark.parametrize("pack,level", LEVELS)
def test_anon_run_solves_and_never_prints_a_real_kind_name(tmp_path, pack, level):
    """Anonymous runs must be playable from RULES.md alone, and stay anonymous."""
    packs_dir = _requires(pack)
    requires_winnable_gold_path(packs_dir, pack, level)
    sys.path.insert(0, str(PLATFORM_ROOT))
    from engines.python.loader import load_pack
    from engines.python.anon import build_anon_action_shapes

    game_def, _levels = load_pack(str(packs_dir / pack))
    _shapes, table = build_anon_action_shapes(game_def)
    anon_moves = anonymize(table, gold_path(packs_dir, pack, level))

    result = run_session(tmp_path, packs_dir, pack, level, anon_moves, anon=True)
    assert result["solved"] is True
    assert result["rejected_schema"] == 0
    # The gold path is written in real ids. Scoring the agent's aliases against
    # it directly makes every anon run diverge at move 0, flawless or not.
    assert result["first_divergence"] is None

    from tools.benchmark.harness.supervisor import RESULT_MARKER
    # Everything after the marker is the supervisor talking to us, not to
    # the agent: it names the pack and level by design.
    transcript = result["_stdout"].split(RESULT_MARKER)[0]
    visible = (Path(result["_sandbox"]) / "RULES.md").read_text() + transcript
    # Kinds rendered as '.' or ' ' keep their own symbol by design, so the
    # legend says ".=empty"; everything with a generated letter must hide.
    from engines.python.anon import build_anon_kind_to_label

    for kind_id in build_anon_kind_to_label(game_def):
        assert kind_id not in visible, f"anon run leaked entity kind {kind_id!r}"
    for action in game_def.actions:
        assert f"### `{action['id']}`" not in visible, (
            f"anon run leaked action id {action['id']!r}"
        )


@pytest.mark.parametrize("pack,level", LEVELS)
def test_anon_scoring_form_recovers_the_real_move(pack, level):
    """`first_divergence is None` must mean "matched", not "always None".

    Checks the translation the supervisor scores with, without a subprocess:
    every aliased move has to come back as exactly what the gold path says.
    """
    packs_dir = _requires(pack)
    from tools.benchmark.harness.supervisor import Session
    from engines.python.anon import build_anon_action_shapes

    session = Session(packs_dir / pack, level, anon=True)
    _shapes, table = build_anon_action_shapes(session.game_def)
    gold = gold_path(packs_dir, pack, level)

    recovered = [session._scoring_form(m) for m in anonymize(table, gold)]
    assert recovered == gold

    # A gold path can be a single move repeated, which `recovered == gold`
    # alone would not distinguish from a translation that collapses everything
    # to one value. Perturb one parameter and require the result to change.
    wrong = dict(anonymize(table, [gold[0]])[0])
    p_alias, spec = next(iter(table[wrong["action"]]["params"].items()))
    if spec["values"] is not None:
        wrong[p_alias] = next(v for v in spec["values"] if v != wrong[p_alias])
    else:
        wrong[p_alias] = [99, 99]
    assert session._scoring_form(wrong) != gold[0]


# ── the counters comment 3 is about ───────────────────────────────────────

# three_kingdoms runs coupled_actors, which vetoes nothing: a tap_cell there is
# accepted as a no-op turn. pincer runs individual_actors, which vetoes a tap
# on an unreachable cell. Same probe, opposite handling — which is precisely
# why a single `rejected` counter could not mean the same thing in both packs.
# The split follows the system, not the level, so both levels of a pack agree.
_PROBE_EXPECTATIONS = [
    ("three_kingdoms", "tk_001", 0, 1),
    ("three_kingdoms", "tk_006", 0, 1),
    ("pincer", "pc_001", 1, 0),
    ("pincer", "pc_006", 1, 0),
]


@pytest.mark.parametrize("pack,level,illegal,wasted", _PROBE_EXPECTATIONS)
def test_probing_and_bad_json_are_counted_apart(tmp_path, pack, level,
                                                illegal, wasted):
    """A solved run stays 'trivial' no matter how much the agent probed.

    Illegal moves are ordinary exploration; only malformed JSON is friction.
    Both are injected here, and the run still solves.
    """
    packs_dir = _requires(pack)
    requires_winnable_gold_path(packs_dir, pack, level)
    gold = gold_path(packs_dir, pack, level)
    probes = [
        {"action": "tap_cell", "position": [0, 0]},        # a wall cell
        {"action": "nonsense"},                            # schema: no such action
        {"action": "tap_cell", "position": "over there"},  # schema: bad type
    ]
    result = run_session(tmp_path, packs_dir, pack, level, probes + gold)

    assert result["solved"] is True
    assert result["rejected_schema"] == 2
    assert result["rejected_illegal"] == illegal
    assert result["tier"] == "trivial", (
        "probing must not be classified as friction on a solved run"
    )
    # Schema rejections never cost an action. A vetoed one does not either;
    # an accepted no-op does, which is the `wasted` column.
    assert result["actions_total"] == len(gold) + wasted


@pytest.mark.parametrize("pack,level", LEVELS)
def test_five_malformed_moves_in_a_row_is_friction(tmp_path, pack, level):
    packs_dir = _requires(pack)
    result = run_session(tmp_path, packs_dir, pack, level,
                         [{"action": "nonsense"}] * 5)
    assert result["solved"] is False
    assert result["rejected_schema"] == 5
    assert result["tier"] == "friction"


# ── malformed input never reaches the engine ──────────────────────────────

@pytest.mark.parametrize("pack,level", LEVELS)
def test_malformed_position_does_not_kill_the_run(tmp_path, pack, level):
    """Agent-authored JSON must not be able to crash the harness."""
    packs_dir = _requires(pack)
    requires_winnable_gold_path(packs_dir, pack, level)
    gold = gold_path(packs_dir, pack, level)
    result = run_session(
        tmp_path, packs_dir, pack, level,
        [{"action": "tap_cell", "position": "nope"}] + gold,
    )
    assert result["reached_terminal"] is True
    assert result["solved"] is True
    assert result["rejected_schema"] == 1


# ── runs that never finish ────────────────────────────────────────────────

@pytest.mark.parametrize("pack,level", LEVELS)
def test_unfinished_run_reports_the_actions_it_took(tmp_path, pack, level):
    """An agent that stops early must not look like it played nothing.

    Reporting actions_total 0 for a run that moved would read as a perfectly
    efficient failure, which is the opposite of what happened.
    """
    packs_dir = _requires(pack)
    gold = gold_path(packs_dir, pack, level)
    partial = gold[:2]
    result = run_session(tmp_path, packs_dir, pack, level, partial)

    assert result["reached_terminal"] is False
    assert result["solved"] is False
    assert result["actions_total"] == len(partial)
    assert result["efficiency"] == len(partial) / len(gold)
