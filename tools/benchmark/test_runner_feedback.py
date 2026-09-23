"""Runner loss/rejection feedback: loss_reason, PREVIOUS ATTEMPT, rejected
actions and the "board did not change" note.

Drives runner.py over stdin/stdout against a throwaway pack.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
RUNNER = BENCH_DIR / "runner.py"

_GAME = {
    "layers": [
        {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
        {"id": "actors", "occupancy": "zero_or_one"},
    ],
    "entityKinds": {
        "empty": {"layer": "ground", "tags": ["walkable"], "symbol": "."},
        "wall": {"layer": "ground", "tags": ["solid"], "symbol": "#"},
        "red": {"layer": "actors", "tags": ["actor"], "symbol": "R", "uiName": "Red piece"},
    },
    "actions": [
        {"id": "move", "params": {"direction": {"type": "direction",
                                                "values": ["up", "down", "left", "right"]}}},
        {"id": "tap_cell", "params": {"position": {"type": "position"}}},
    ],
    "systems": [
        {"id": "individual", "type": "individual_actors",
         "config": {"actorLayer": "actors", "groundLayer": "ground"}},
    ],
    "defaults": {"avatar": {"enabled": False}},
}


def _level(description: str | None) -> dict:
    lose = {"type": "max_actions", "config": {"limit": 2}}
    if description is not None:
        lose["description"] = description
    return {
        "id": "fb_01",
        "board": {"size": [3, 1], "layers": {
            "ground": {"format": "sparse", "entries": [{"position": [2, 0], "kind": "wall"}]},
            "actors": {"format": "sparse", "entries": [{"position": [0, 0], "kind": "red"}]},
        }},
        "state": {"avatar": {"enabled": False}},
        "goals": [{"id": "g", "type": "reach_target", "config": {"targetKind": "wall"}}],
        "loseConditions": [lose],
        "solution": {"goldPath": [{"action": "move", "direction": "right"}]},
    }


def _run(inputs: list[dict], *args: str, description: str | None = None) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        pack = Path(tmp) / "fbpack"
        (pack / "levels").mkdir(parents=True)
        (pack / "manifest.json").write_text(json.dumps({"id": "fbpack", "title": "FB"}))
        (pack / "game.json").write_text(json.dumps(_GAME))
        (pack / "levels" / "fb_01.json").write_text(json.dumps(_level(description)))
        proc = subprocess.run(
            [sys.executable, str(RUNNER), "--pack", "fbpack", "--level", "fb_01",
             "--packs-dir", tmp, "--attempt-multiplier", "10",
             "--total-multiplier", "20", *args],
            input="".join(json.dumps(i) + "\n" for i in inputs),
            capture_output=True, text=True, timeout=60,
        )
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


_SELECT = {"action": "tap_cell", "position": [0, 0]}
_LEFT = {"action": "move", "direction": "left"}  # blocked by the edge: accepted, no change


def test_loss_reason_generic_and_description():
    events = _run([_SELECT, _LEFT, _LEFT])
    assert events[-1]["event"] == "lost"
    assert events[-1]["loss_reason"] == "move limit of 2 reached"
    events = _run([_SELECT, _LEFT, _LEFT], description="the lamp burned out")
    assert events[-1]["loss_reason"] == "the lamp burned out"


def test_previous_attempt_line_after_a_lost_attempt():
    events = _run([_SELECT, _LEFT, _LEFT], "--max-attempts", "2")
    states = [e for e in events if e["event"] == "state"]
    first_of_attempt_2 = states[-1]["prompt"]
    assert ("PREVIOUS ATTEMPT: lost — move limit of 2 reached\n"
            "CURRENT BOARD (first move of this attempt):\n") in first_of_attempt_2
    assert all("PREVIOUS ATTEMPT" not in s["prompt"] for s in states[:-1])


def test_previous_attempt_after_give_up_is_shown_once():
    events = _run([{"action": "give_up"}, _SELECT], "--max-attempts", "3")
    states = [e for e in events if e["event"] == "state"]
    assert "PREVIOUS ATTEMPT: given up\nCURRENT BOARD" in states[1]["prompt"]
    assert "PREVIOUS ATTEMPT" not in states[2]["prompt"]


def test_rejected_action_section_replaces_before_after():
    events = _run([_LEFT])  # moving with nothing selected is vetoed
    assert events[1]["event"] == "rejected"
    prompt = events[2]["prompt"]
    assert ('LAST ACTION: {"action": "move", "direction": "left"} — REJECTED '
            "(move is not legal in this state); no action was spent, the board "
            "is unchanged.\nCURRENT BOARD:\n") in prompt, prompt
    assert "BOARD BEFORE" not in prompt


def test_board_did_not_change_note_and_allowance():
    events = _run([_SELECT, _LEFT])
    prompt = [e for e in events if e["event"] == "state"][-1]["prompt"]
    assert ("Moves this attempt: 1 of 2 allowed\nSelected: Red piece at (0,0)\n"
            "The board did not change.\n") in prompt, prompt


_IMAGE_NOTE = "(See the attached image of the current board."


def test_image_mode_keeps_feedback_and_status_without_the_grid():
    events = _run([_LEFT, _SELECT, _LEFT, _LEFT], "--input", "image", "--max-attempts", "2")
    states = [e for e in events if e["event"] == "state"]
    assert all(s.get("image_b64") for s in states)
    assert all("Each character is one cell" not in s["prompt"] for s in states)
    assert all("GOAL: " in s["prompt"] for s in states)
    # Rejected action: the rejection line, then the image note as the board.
    rejected = states[1]["prompt"]
    assert ('REJECTED (move is not legal in this state); no action was spent, the board '
            "is unchanged.\nCURRENT BOARD:\n" + _IMAGE_NOTE) in rejected, rejected
    # Selecting: the ring is explained, the status lines follow the note, and
    # the text-board comparison still says the board did not change.
    selected = states[2]["prompt"]
    assert ("BOARD BEFORE:\n(Not shown: only the current board is attached as an image.)\n"
            ) in selected, selected
    assert ("Image marks: a gold ring marks the selected piece.\n"
            "Moves this attempt: 0 of 2 allowed\nSelected: Red piece at (0,0)\n"
            "The board did not change.\n") in selected, selected
    assert "Compare the two boards" not in selected
    # The edge bump is accepted, costs a move and changes nothing.
    bumped = states[3]["prompt"]
    assert "Moves this attempt: 1 of 2 allowed\nSelected: Red piece at (0,0)\n" in bumped
    assert "The board did not change.\n" in bumped
    # The second attempt opens with the previous attempt's loss.
    assert ("PREVIOUS ATTEMPT: lost — move limit of 2 reached\n"
            "CURRENT BOARD (first move of this attempt):\n" + _IMAGE_NOTE) in states[4]["prompt"]


def test_text_image_mode_keeps_the_grid_and_names_the_image_marks():
    events = _run([_SELECT], "--input", "text+image")
    states = [e for e in events if e["event"] == "state"]
    prompt = states[1]["prompt"]
    assert states[1].get("image_b64")
    assert "BOARD BEFORE:\nR.#\n" in prompt, prompt
    assert ("Selected: Red piece at (0,0)\nThe board did not change.\n\n"
            "Compare the two boards") in prompt, prompt
    assert ("The attached image is a sprite rendering of the current board "
            "(same state as the text grid above).\n"
            "Image marks: a gold ring marks the selected piece.\n") in prompt, prompt


def test_text_mode_has_no_image_notes():
    events = _run([_SELECT])
    prompt = [e for e in events if e["event"] == "state"][-1]["prompt"]
    assert "image" not in prompt.lower(), prompt
    assert all("image_b64" not in e for e in events)


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  ok    {name}")
            except AssertionError as exc:
                failed += 1
                print(f"  FAIL  {name}: {exc}")
    sys.exit(1 if failed else 0)
