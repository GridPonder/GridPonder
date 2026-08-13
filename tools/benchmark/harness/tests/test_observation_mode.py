"""Verify --observation harness emits board-only state events."""
import json
import subprocess
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parents[2]
PLATFORM_ROOT = BENCH_DIR.parents[1]
RUNNER = BENCH_DIR / "runner.py"
PACKS_DIR = PLATFORM_ROOT / "packs"

if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from engines.python.loader import load_pack  # noqa: E402
from engines.python.anon import build_anon_kind_to_label  # noqa: E402


def _first_state_event(
    *extra_args: str, pack: str = "number_cells", level: str = "nc_001"
) -> dict:
    """Start the runner, read events until the first state event, kill it."""
    proc = subprocess.Popen(
        [sys.executable, str(RUNNER),
         "--pack", pack, "--level", level,
         "--packs-dir", str(PACKS_DIR), *extra_args],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1,
    )
    try:
        for raw in proc.stdout:
            line = raw.strip()
            if not line:
                continue
            event = json.loads(line)
            if event.get("event") == "state":
                return event
        raise AssertionError("runner produced no state event")
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_harness_mode_omits_leaky_fields():
    event = _first_state_event("--observation", "harness")
    assert "valid_actions" not in event
    assert "gold_path_length" not in event
    assert "prompt" not in event


def test_harness_mode_provides_board_and_goals():
    event = _first_state_event("--observation", "harness")
    assert isinstance(event["board_text"], str)
    assert event["board_text"].strip() != ""
    assert isinstance(event["goals"], str)
    assert event["goals"].strip() != ""
    assert event["moves_this_attempt"] == 0


def test_default_mode_unchanged():
    """Existing bench.py consumers must keep seeing prompt + valid_actions."""
    event = _first_state_event()
    assert "prompt" in event
    assert "valid_actions" in event
    assert "gold_path_length" in event


def test_harness_mode_anon_goals_do_not_leak_real_entity_name():
    """--anon must anonymise goal text exactly like it anonymises the board.

    carrot_quest/fw_003's only goal is reach_target on the tag carried by the
    "carrot" entity kind. In anon mode the board legend hides that kind
    behind a generated letter label (e.g. "B=?"); the goal text must use the
    same letter, never the real kind name "carrot".
    """
    game_def, _levels = load_pack(PACKS_DIR / "carrot_quest")
    label = build_anon_kind_to_label(game_def)["carrot"]

    event = _first_state_event(
        "--observation", "harness", "--anon",
        pack="carrot_quest", level="fw_003",
    )

    assert "carrot" not in event["goals"].lower(), (
        f"anon goals leaked the real entity name: {event['goals']!r}"
    )
    assert event["goals"] == f"Reach the {label}", event["goals"]


# ── comment 4: anon must not leak a real kind name through the inventory ──

def _drive(moves, *extra_args, pack: str, level: str) -> list[dict]:
    """Send `moves` to the runner, returning every event it emitted."""
    proc = subprocess.Popen(
        [sys.executable, str(RUNNER), "--pack", pack, "--level", level,
         "--packs-dir", str(PACKS_DIR), *extra_args],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    payload = "".join(json.dumps(m) + "\n" for m in moves)
    out, _err = proc.communicate(payload, timeout=60)
    return [json.loads(line) for line in out.strip().splitlines()]


def test_harness_anon_inventory_uses_the_board_label():
    """fw_003 picks up a torch; the board calls that kind 'H', so must inventory."""
    game_def, levels = load_pack(PACKS_DIR / "carrot_quest")
    from engines.python.anon import build_anon_action_shapes

    label = build_anon_kind_to_label(game_def)["torch"]
    _shapes, table = build_anon_action_shapes(game_def)
    directions = table["a1"]["params"]["p1"]["values"]
    alias_of = {real: alias for alias, real in directions.items()}
    moves = [
        {"action": "a1", "p1": alias_of[m["direction"]]}
        for m in levels["fw_003"]["solution"]["goldPath"]
    ]

    events = _drive(moves, "--observation", "harness", "--anon",
                    pack="carrot_quest", level="fw_003")
    carried = {e["inventory"] for e in events
               if e["event"] == "state" and e["inventory"]}
    assert carried == {label}
    assert "torch" not in carried


# ── comment 2: an anon run must be playable from the documented shapes ────

def test_harness_anon_solves_using_only_documented_aliases():
    game_def, levels = load_pack(PACKS_DIR / "carrot_quest")
    from engines.python.anon import build_anon_action_shapes

    _shapes, table = build_anon_action_shapes(game_def)
    directions = table["a1"]["params"]["p1"]["values"]
    alias_of = {real: alias for alias, real in directions.items()}
    moves = [
        {"action": "a1", "p1": alias_of[m["direction"]]}
        for m in levels["fw_003"]["solution"]["goldPath"]
    ]

    events = _drive(moves, "--observation", "harness", "--anon",
                    pack="carrot_quest", level="fw_003")
    assert events[-1]["event"] == "won"
    assert not [e for e in events if e["event"] == "rejected"]


def test_harness_anon_still_hides_the_legal_move_list():
    """The aliases are a schema, not a menu: no state event enumerates moves."""
    event = _first_state_event("--observation", "harness", "--anon",
                               pack="carrot_quest", level="fw_003")
    assert "valid_actions" not in event
    assert "actions" not in event


def test_harness_anon_rejects_the_real_action_id():
    """The whole point of the alias: 'move' is not a name this run answers to."""
    events = _drive([{"action": "move", "direction": "up"}],
                    "--observation", "harness", "--anon",
                    pack="carrot_quest", level="fw_003")
    rejected = [e for e in events if e["event"] == "rejected"]
    assert rejected and rejected[0]["reason"] == "schema"


# ── comment 3 + the crash: malformed params are rejected, not executed ────

def test_malformed_direction_is_a_schema_rejection_not_a_wasted_turn():
    events = _drive([{"action": "move", "direction": "northwest"}],
                    "--observation", "harness",
                    pack="carrot_quest", level="fw_003")
    rejected = [e for e in events if e["event"] == "rejected"]
    assert rejected and rejected[0]["reason"] == "schema"
    state = [e for e in events if e["event"] == "state"][-1]
    assert state["moves_this_attempt"] == 0


def test_missing_parameter_is_a_schema_rejection():
    events = _drive([{"action": "move"}], "--observation", "harness",
                    pack="carrot_quest", level="fw_003")
    rejected = [e for e in events if e["event"] == "rejected"]
    assert rejected and rejected[0]["reason"] == "schema"


def test_terminal_events_carry_both_counters():
    events = _drive([{"action": "nonsense"}] * 5, "--observation", "harness",
                    pack="carrot_quest", level="fw_003")
    assert events[-1]["event"] == "lost"
    assert events[-1]["rejected_schema"] == 5
    assert events[-1]["rejected_illegal"] == 0
