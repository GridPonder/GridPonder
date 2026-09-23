"""
Prompt status block and feedback lines built by `observation.build_prompt`.

Covers the public status lines under the board (move allowance, the
`individual_actors` selection and budgets, `ui.readouts`), the
`PREVIOUS ATTEMPT:` line, the rejected-action section and the
"board did not change" note. Builds an inline GameDef + level (no pack files).

Run from engines/python/:  python test_observation.py
"""
from __future__ import annotations
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine
from engines.python.anon import build_anon_kind_to_label
from engines.python.observation import build_prompt, status_fingerprint, status_lines
from engines.python.text_renderer import render


_GAME = {
    "layers": [
        {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
        {"id": "actors", "occupancy": "zero_or_one"},
    ],
    "entityKinds": {
        "empty": {"layer": "ground", "tags": ["walkable"], "symbol": "."},
        "wall": {"layer": "ground", "tags": ["solid"], "symbol": "#"},
        "red": {"layer": "actors", "tags": ["actor"], "symbol": "R", "uiName": "Red piece"},
        "blue": {"layer": "actors", "tags": ["actor"], "symbol": "B", "uiName": "Blue piece"},
    },
    "actions": [
        {"id": "move", "params": {"direction": {"type": "direction",
                                                "values": ["up", "down", "left", "right"]}}},
        {"id": "tap_cell", "params": {"position": {"type": "position"}}},
    ],
    "systems": [
        {"id": "individual", "type": "individual_actors", "enabled": False,
         "config": {"actorLayer": "actors", "groundLayer": "ground",
                    "budgets": {"red": 3, "blue": 2}}},
    ],
    "defaults": {"avatar": {"enabled": False}},
    "ui": {"readouts": [
        {"variable": "heat", "label": "Heat", "blankWhen": -1},
        {"variable": "missing", "label": "Never shown"},
        {"variable": "gauge", "label": "Gauge"},
    ]},
}

_LEVEL = {
    "id": "obs_01",
    "board": {"size": [3, 2], "layers": {
        "ground": {"format": "sparse", "entries": [{"position": [2, 1], "kind": "wall"}]},
        "actors": {"format": "sparse", "entries": [
            {"position": [0, 0], "kind": "red"},
            {"position": [0, 1], "kind": "blue"},
        ]},
    }},
    "state": {"avatar": {"enabled": False}, "variables": {"heat": -1, "gauge": 2.0}},
    "systemOverrides": {"individual": {"enabled": True}},
    "goals": [{"id": "g", "type": "reach_target", "config": {"targetKind": "wall"}}],
    "loseConditions": [{"type": "max_actions", "config": {"limit": 11}}],
}


def _setup(level_patch: dict | None = None, game_patch: dict | None = None):
    game_data = copy.deepcopy(_GAME)
    game_data.update(game_patch or {})
    level = copy.deepcopy(_LEVEL)
    level.update(level_patch or {})
    game = GameDef.from_dict(game_data, id="obs")
    return game, level, TurnEngine(game, level)


def _status(game, level, engine, anon=False) -> list[str]:
    labels = build_anon_kind_to_label(game) if anon else None
    return status_lines(game, level, engine.state, anonymize=anon,
                        kind_to_label=labels).split("\n")[1:]


# ── E. status block ───────────────────────────────────────────────────────

def test_initial_status_block():
    game, level, engine = _setup()
    assert _status(game, level, engine) == [
        "Moves this attempt: 0 of 11 allowed",
        "Selected: none",
        "Moves left: Red piece 3, Blue piece 2",
        "Heat: -",
        "Gauge: 2",
    ]


def test_selection_and_budget_after_moves():
    game, level, engine = _setup()
    assert engine.execute_turn("tap_cell", {"position": [0, 0]}).accepted
    assert engine.execute_turn("move", {"direction": "right"}).accepted
    engine.state.variables["heat"] = 4
    assert _status(game, level, engine) == [
        "Moves this attempt: 1 of 11 allowed",
        "Selected: Red piece at (1,0)",
        "Moves left: Red piece 2, Blue piece 2",
        "Heat: 4",
        "Gauge: 2",
    ]


def test_selection_that_no_longer_holds_its_piece():
    game, level, engine = _setup()
    engine.execute_turn("tap_cell", {"position": [0, 0]})
    engine.state.board.set_entity("actors", Pos(0, 0), None)
    assert _status(game, level, engine)[1] == (
        "Selected: none (the piece selected at (0,0) is gone or changed)")


def test_anonymous_status_block_uses_labels():
    game, level, engine = _setup()
    labels = build_anon_kind_to_label(game)
    engine.execute_turn("tap_cell", {"position": [0, 1]})
    lines = _status(game, level, engine, anon=True)
    assert lines == [
        "Moves this attempt: 0 of 11 allowed",
        f"Selected: {labels['blue']} at (0,1)",
        f"Moves left: {labels['red']} 3, {labels['blue']} 2",
        "Readout 1: -",
        "Readout 3: 2",
    ], lines
    assert not any("piece" in line or "Heat" in line for line in lines)


def test_system_disabled_and_no_max_actions_keeps_old_lines():
    game, level, engine = _setup(
        level_patch={"systemOverrides": {},
                     "loseConditions": [{"type": "variable_threshold",
                                         "config": {"variable": "heat", "target": 9}}]},
        game_patch={"ui": {}})
    assert _status(game, level, engine) == ["Moves this attempt: 0"]


def test_no_lose_conditions_no_status():
    game, level, engine = _setup(
        level_patch={"systemOverrides": {}, "loseConditions": []}, game_patch={"ui": {}})
    assert status_lines(game, level, engine.state) == ""


def test_readouts_parsing_drops_malformed_entries():
    game = GameDef.from_dict({"ui": {"readouts": [
        {"variable": "a", "label": "A", "blankWhen": 0},
        {"label": "no variable"},
        "not an object",
        {"variable": "", "label": "empty"},
    ]}})
    assert game.ui_readouts == [
        {"variable": "a", "label": "A", "color": None, "blankWhen": 0}]
    assert GameDef.from_dict({}).ui_readouts == []


# ── F. prompt feedback ────────────────────────────────────────────────────

def test_previous_attempt_line_sits_before_current_board():
    game, level, engine = _setup()
    prompt = build_prompt(game, level, engine.state,
                          previous_attempt="lost — move limit of 11 reached")
    assert ("PREVIOUS ATTEMPT: lost — move limit of 11 reached\n"
            "CURRENT BOARD (first move of this attempt):\n") in prompt


def test_rejected_action_section():
    game, level, engine = _setup()
    board = render(engine.state, game)
    prompt = build_prompt(
        game, level, engine.state,
        last_action={"action": "tap_cell", "position": [0, 0]},
        previous_board_text="irrelevant",
        rejected_action={"action": "move", "direction": "up", "memory": "x"},
        rejection_detail="move is not legal in this state",
    )
    expected = (
        'LAST ACTION: {"action": "move", "direction": "up"} — REJECTED '
        "(move is not legal in this state); no action was spent, the board is unchanged.\n"
        "CURRENT BOARD:\n" + board + "\nMoves this attempt: 0 of 11 allowed"
    )
    assert expected in prompt, prompt
    assert "BOARD BEFORE" not in prompt and "BOARD AFTER" not in prompt


def test_board_did_not_change_note():
    game, level, engine = _setup()
    engine.execute_turn("tap_cell", {"position": [0, 1]})
    before = render(engine.state, game, include_legend=False)
    before_status = status_fingerprint(game, level, engine.state)
    # Blue moving down leaves the board: blocked, but accepted and counted.
    # Only the move counter changed, which is not a change to the board.
    result = engine.execute_turn("move", {"direction": "down"})
    assert result.accepted and engine.state.action_count == 1
    prompt = build_prompt(game, level, engine.state,
                          last_action={"action": "move", "direction": "down"},
                          previous_board_text=before,
                          previous_status=before_status)
    assert ("Moves this attempt: 1 of 11 allowed\nSelected: Blue piece at (0,1)\n"
            "Moves left: Red piece 3, Blue piece 2\nHeat: -\nGauge: 2\n"
            "The board did not change.\n\nCompare the two boards") in prompt, prompt


def test_status_fingerprint_drops_only_the_move_counter():
    game, level, engine = _setup()
    assert status_fingerprint(game, level, engine.state) == (
        "Selected: none\nMoves left: Red piece 3, Blue piece 2\nHeat: -\nGauge: 2")


def test_a_selection_change_has_no_note():
    """Selecting redraws no cell, but `Selected:` changed: not "no change"."""
    game, level, engine = _setup()
    before = render(engine.state, game, include_legend=False)
    before_status = status_fingerprint(game, level, engine.state)
    engine.execute_turn("tap_cell", {"position": [0, 0]})
    assert render(engine.state, game, include_legend=False) == before
    prompt = build_prompt(game, level, engine.state,
                          last_action={"action": "tap_cell", "position": [0, 0]},
                          previous_board_text=before,
                          previous_status=before_status)
    assert "Selected: Red piece at (0,0)" in prompt, prompt
    assert "The board did not change." not in prompt, prompt
    # Anonymous prompts decide the same way (labels are a bijection).
    labels = build_anon_kind_to_label(game)
    anon_before = render(engine.state, game, include_legend=False,
                         kind_symbol_overrides=labels)
    anon = build_prompt(game, level, engine.state, anonymize=True,
                        last_action={"action": "tap_cell", "position": [0, 0]},
                        previous_board_text=anon_before,
                        previous_status=before_status)
    assert "The board did not change." not in anon, anon


def test_changed_board_has_no_note():
    game, level, engine = _setup()
    engine.execute_turn("tap_cell", {"position": [0, 0]})
    before = render(engine.state, game, include_legend=False)
    engine.execute_turn("move", {"direction": "right"})
    prompt = build_prompt(game, level, engine.state,
                          last_action={"action": "move", "direction": "right"},
                          previous_board_text=before)
    assert "The board did not change." not in prompt


def test_anonymous_inventory_shows_label_not_kind():
    game = GameDef.from_dict({
        "layers": [{"id": "ground", "occupancy": "exactly_one", "default": "empty"}],
        "entityKinds": {
            "empty": {"layer": "ground", "symbol": "."},
            "torch": {"layer": "ground", "symbol": "t", "uiName": "Torch"},
        },
        "actions": [{"id": "wait"}],
    }, id="inv")
    level = {
        "id": "inv_01",
        "board": {"size": [2, 1], "layers": {}},
        "state": {"avatar": {"enabled": True, "position": [0, 0],
                             "inventory": {"slot": "torch"}}},
        "goals": [],
    }
    engine = TurnEngine(game, level)
    label = build_anon_kind_to_label(game)["torch"]
    named = build_prompt(game, level, engine.state)
    assert "\nInventory: torch" in named
    board = render(engine.state, game, include_legend=False)
    anon = build_prompt(game, level, engine.state, anonymize=True,
                        last_action={"action": "wait"},
                        previous_board_text=board, previous_inventory="torch")
    assert f"\nInventory: {label}" in anon
    assert "torch" not in anon.lower(), anon


def run_all() -> bool:
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok    {t.__name__}")
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {exc}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
