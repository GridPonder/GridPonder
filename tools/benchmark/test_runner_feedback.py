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


def _run(inputs: list[dict], *args: str, description: str | None = None,
         game: dict | None = None, level: dict | None = None) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        pack = Path(tmp) / "fbpack"
        (pack / "levels").mkdir(parents=True)
        (pack / "manifest.json").write_text(json.dumps({"id": "fbpack", "title": "FB"}))
        (pack / "game.json").write_text(json.dumps(game or _GAME))
        (pack / "levels" / "fb_01.json").write_text(
            json.dumps(level or _level(description)))
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


def test_a_selection_change_is_not_reported_as_no_change():
    """Selecting redraws no cell, but the `Selected:` status line changed, so
    the action did something and the note must not claim otherwise."""
    events = _run([_SELECT])
    prompt = [e for e in events if e["event"] == "state"][-1]["prompt"]
    assert "BOARD BEFORE:\nR.#\n" in prompt, prompt
    assert "Selected: Red piece at (0,0)\n\nCompare the two boards" in prompt, prompt
    assert "The board did not change." not in prompt, prompt


_STAMP_GAME = {
    "layers": [
        {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
        {"id": "paper", "occupancy": "zero_or_one"},
        {"id": "ink", "occupancy": "zero_or_one"},
        {"id": "held", "occupancy": "zero_or_one"},
    ],
    "entityKinds": {
        "empty": {"layer": "ground", "tags": [], "symbol": "."},
        "only_red": {"layer": "paper", "tags": [], "symbol": "4", "uiName": "Red plate"},
        "ink_red": {"layer": "ink", "tags": [], "symbol": "r"},
        "ink_blue": {"layer": "ink", "tags": [], "symbol": "b", "uiName": "Blue ink"},
        "held_red": {"layer": "held", "tags": [], "symbol": "R"},
        "held_blue": {"layer": "held", "tags": [], "symbol": "B"},
        "slot_empty": {"layer": "held", "tags": [], "symbol": "o"},
    },
    "actions": [
        {"id": "move", "params": {"direction": {"type": "direction",
                                                "values": ["left", "right"]}}},
        {"id": "press", "params": {}},
    ],
    "systems": [
        {"id": "cursor", "type": "overlay_cursor", "config": {
            "moveAction": "move", "size": [1, 1], "carryLayers": ["held"]}},
        {"id": "stamp", "type": "region_transform", "config": {"operations": {"press": {
            "type": "exchange", "action": "press", "layers": ["ink", "held"],
            "pairs": [["ink_red", "held_red"], ["ink_blue", "held_blue"],
                      [None, "slot_empty"]],
            "restrict": {"layer": "paper", "accepts": {"only_red": ["ink_red"]}}}}}},
    ],
    "defaults": {"avatar": {"enabled": False}},
}

_STAMP_LEVEL = {
    "id": "fb_01",
    "board": {"size": [2, 1], "layers": {
        "paper": {"format": "sparse", "entries": [{"position": [0, 0], "kind": "only_red"}]},
        "held": {"format": "sparse", "entries": [{"position": [0, 0], "kind": "held_blue"},
                                                  {"position": [1, 0], "kind": "slot_empty"}]},
    }},
    "state": {"avatar": {"enabled": False},
              "overlay": {"position": [0, 0], "size": [1, 1]}},
    "goals": [{"id": "g", "type": "board_match", "config": {
        "layer": "ink", "target": [["ink_blue", None]]}}],
    "solution": {"goldPath": [{"action": "move", "direction": "right"}]},
}

_REASON = "Red plate at (0,0) refuses Blue ink"


def test_an_engine_veto_reason_is_the_rejection_detail():
    events = _run([{"action": "press"}], game=_STAMP_GAME, level=_STAMP_LEVEL)
    assert events[1] == {"event": "rejected", "action": {"action": "press"},
                         "reason": "illegal", "detail": _REASON}, events[1]
    assert (f'LAST ACTION: {{"action": "press"}} — REJECTED ({_REASON}); '
            "no action was spent") in events[2]["prompt"], events[2]["prompt"]


def test_an_anonymous_run_never_shows_the_veto_reason():
    """The reason names kinds; the harness shows the event detail to the agent,
    so an anonymous run keeps the generic text in the event too, naming the
    action by the submitted label rather than its real id."""
    events = _run([{"action": "a2"}], "--anon", "--observation", "harness",
                  game=_STAMP_GAME, level=_STAMP_LEVEL)
    rejected = [e for e in events if e["event"] == "rejected"]
    assert rejected and rejected[0]["detail"] == "a2 is not legal in this state", events
    assert all("Red plate" not in json.dumps(e) for e in events), events
    assert all("press" not in json.dumps(e) for e in events), events


def test_an_anonymous_rejection_detail_names_the_submitted_label():
    """Without a veto reason the generic event detail used to name the real
    action ("move is not legal ..."); the harness shows it to the agent."""
    move_left = {"action": "a1", "p1": "v2"}  # schema aliases: move, direction=left
    events = _run([move_left], "--anon", "--observation", "harness")
    assert events[1] == {"event": "rejected", "action": move_left,
                         "reason": "illegal",
                         "detail": "a1 is not legal in this state"}, events[1]
    assert all("move" not in e.get("detail", "") for e in events), events


def test_anonymous_last_action_echoes_the_submitted_label():
    """Labels are renumbered every turn. Selecting removes the re-tap action,
    so looking the last action up among the new labels found nothing ("?");
    the prompt must echo the label the agent actually sent."""
    events = _run([{"action": "a1"}], "--anon")
    assert events[0]["valid_actions"][0] == _SELECT
    prompt = events[-1]["prompt"]
    assert 'LAST ACTION: {"action": "a1"}\nBOARD BEFORE:' in prompt, prompt
    assert '"?"' not in prompt, prompt
    # Moves are now offered as a1..a4 (sorted: down, left, right, up); moving
    # right echoes a3 whatever the following state numbers it as.
    events = _run([{"action": "a1"}, {"action": "a3"}], "--anon")
    prompt = [e for e in events if e["event"] == "state"][-1]["prompt"]
    assert 'LAST ACTION: {"action": "a3"}\nBOARD BEFORE:' in prompt, prompt


def test_anonymous_last_action_label_in_a_fixed_n_batch():
    """Batch modes echo the submitted label too (the re-tap is gone from the
    next state, so a lookup there printed "?"), and a batch resolves every
    label against the one prompt it answers."""
    level = _level(None)
    level["loseConditions"][0]["config"]["limit"] = 9
    events = _run([{"actions": [{"action": "a1"}]},
                   {"actions": [{"action": "a3"}, {"action": "a2"}]}],
                  "--anon", "--mode", "fixed-n", "--step-size", "2", level=level)
    states = [e for e in events if e["event"] == "state"]
    assert 'LAST ACTION: {"action": "a1"}\nBOARD BEFORE:' in states[1]["prompt"], states[1]
    assert 'LAST ACTION: {"action": "a2"}\nBOARD BEFORE:' in states[2]["prompt"], states[2]


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
    # Selecting: the ring is explained and the status lines follow the note;
    # the selection changed, so there is no "did not change" note.
    selected = states[2]["prompt"]
    assert ("BOARD BEFORE:\n(Not shown: only the current board is attached as an image.)\n"
            ) in selected, selected
    assert ("Image marks: a gold ring marks the selected piece.\n"
            "Moves this attempt: 0 of 2 allowed\nSelected: Red piece at (0,0)\n\n"
            ) in selected, selected
    assert "The board did not change." not in selected
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
    assert ("Selected: Red piece at (0,0)\n\n"
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
