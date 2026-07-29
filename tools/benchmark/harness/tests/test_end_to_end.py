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

@pytest.mark.parametrize("pack,level", [("three_kingdoms", "tk_001"),
                                        ("pincer", "pc_001")])
def test_sandbox_contains_only_rules_and_play(tmp_path, pack, level):
    packs_dir = _requires(pack)
    result = run_session(tmp_path, packs_dir, pack, level,
                         gold_path(packs_dir, pack, level))
    sandbox = Path(result["_sandbox"])
    # The socket is removed on shutdown, so RULES.md and play are what is left.
    assert sorted(p.name for p in sandbox.iterdir()) == ["RULES.md", "play"]
    assert os.access(sandbox / "play", os.X_OK)


@pytest.mark.parametrize("pack,level", [("three_kingdoms", "tk_001"),
                                        ("pincer", "pc_001")])
def test_rules_leak_neither_gold_path_nor_its_length(tmp_path, pack, level):
    packs_dir = _requires(pack)
    gold = gold_path(packs_dir, pack, level)
    result = run_session(tmp_path, packs_dir, pack, level, gold)
    rules = (Path(result["_sandbox"]) / "RULES.md").read_text()
    for move in gold:
        assert json.dumps(move) not in rules
    assert f"{len(gold)} moves" not in rules
    assert f"{len(gold)} actions" not in rules


# ── solving ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pack,level", [("three_kingdoms", "tk_001"),
                                        ("pincer", "pc_001")])
def test_gold_path_solves_the_level_through_the_sandbox(tmp_path, pack, level):
    packs_dir = _requires(pack)
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


@pytest.mark.parametrize("pack,level", [("three_kingdoms", "tk_001"),
                                        ("pincer", "pc_001")])
def test_anon_run_solves_and_never_prints_a_real_kind_name(tmp_path, pack, level):
    """Anonymous runs must be playable from RULES.md alone, and stay anonymous."""
    packs_dir = _requires(pack)
    sys.path.insert(0, str(PLATFORM_ROOT))
    from engines.python.loader import load_pack
    from engines.python.anon import build_anon_action_shapes

    game_def, _levels = load_pack(str(packs_dir / pack))
    _shapes, table = build_anon_action_shapes(game_def)
    alias_of = {entry["action"]: alias for alias, entry in table.items()}

    anon_moves = []
    for move in gold_path(packs_dir, pack, level):
        alias = alias_of[move["action"]]
        translated = {"action": alias}
        for p_alias, spec in table[alias]["params"].items():
            value = move[spec["name"]]
            if spec["values"] is not None:
                value = next(k for k, v in spec["values"].items() if v == value)
            translated[p_alias] = value
        anon_moves.append(translated)

    result = run_session(tmp_path, packs_dir, pack, level, anon_moves, anon=True)
    assert result["solved"] is True
    assert result["rejected_schema"] == 0

    visible = (Path(result["_sandbox"]) / "RULES.md").read_text() + result["_stdout"]
    # Kinds rendered as '.' or ' ' keep their own symbol by design, so the
    # legend says ".=empty"; everything with a generated letter must hide.
    from engines.python.anon import build_anon_kind_to_label

    for kind_id in build_anon_kind_to_label(game_def):
        assert kind_id not in visible, f"anon run leaked entity kind {kind_id!r}"
    for action in game_def.actions:
        assert f"### `{action['id']}`" not in visible, (
            f"anon run leaked action id {action['id']!r}"
        )


# ── the counters comment 3 is about ───────────────────────────────────────

# tk_001 runs coupled_actors, which vetoes nothing: a tap_cell there is
# accepted as a no-op turn. pincer runs individual_actors, which vetoes a tap
# on an unreachable cell. Same probe, opposite handling — which is precisely
# why a single `rejected` counter could not mean the same thing in both packs.
_PROBE_EXPECTATIONS = [
    ("three_kingdoms", "tk_001", 0, 1),
    ("pincer", "pc_001", 1, 0),
]


@pytest.mark.parametrize("pack,level,illegal,wasted", _PROBE_EXPECTATIONS)
def test_probing_and_bad_json_are_counted_apart(tmp_path, pack, level,
                                                illegal, wasted):
    """A solved run stays 'trivial' no matter how much the agent probed.

    Illegal moves are ordinary exploration; only malformed JSON is friction.
    Both are injected here, and the run still solves.
    """
    packs_dir = _requires(pack)
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


@pytest.mark.parametrize("pack,level", [("three_kingdoms", "tk_001"),
                                        ("pincer", "pc_001")])
def test_five_malformed_moves_in_a_row_is_friction(tmp_path, pack, level):
    packs_dir = _requires(pack)
    result = run_session(tmp_path, packs_dir, pack, level,
                         [{"action": "nonsense"}] * 5)
    assert result["solved"] is False
    assert result["rejected_schema"] == 5
    assert result["tier"] == "friction"


# ── malformed input never reaches the engine ──────────────────────────────

@pytest.mark.parametrize("pack,level", [("three_kingdoms", "tk_001"),
                                        ("pincer", "pc_001")])
def test_malformed_position_does_not_kill_the_run(tmp_path, pack, level):
    """Agent-authored JSON must not be able to crash the harness."""
    packs_dir = _requires(pack)
    gold = gold_path(packs_dir, pack, level)
    result = run_session(
        tmp_path, packs_dir, pack, level,
        [{"action": "tap_cell", "position": "nope"}] + gold,
    )
    assert result["reached_terminal"] is True
    assert result["solved"] is True
    assert result["rejected_schema"] == 1
