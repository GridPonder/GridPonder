"""Verify --observation harness emits board-only state events."""
import json
import subprocess
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parents[2]
PLATFORM_ROOT = BENCH_DIR.parents[1]
RUNNER = BENCH_DIR / "runner.py"
PACKS_DIR = PLATFORM_ROOT / "packs"


def _first_state_event(*extra_args: str) -> dict:
    """Start the runner, read events until the first state event, kill it."""
    proc = subprocess.Popen(
        [sys.executable, str(RUNNER),
         "--pack", "number_cells", "--level", "nc_001",
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
