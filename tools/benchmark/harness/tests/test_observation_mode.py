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
