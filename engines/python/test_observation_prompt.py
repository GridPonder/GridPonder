"""Focused prompt tests for action-allowance rendering."""
from __future__ import annotations

from engines.python._game_def import GameDef
from engines.python._turn_engine import TurnEngine
from engines.python.observation import build_prompt


def _game() -> GameDef:
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "floor"}
            ],
            "entityKinds": {
                "floor": {"layer": "ground", "symbol": ".", "uiName": "Floor"}
            },
            "actions": [{"id": "wait", "params": {}}],
            "systems": [],
        },
        id="prompt_allowance_test",
        title="Prompt allowance test",
    )


def _level(lose_conditions: list[dict]) -> dict:
    return {
        "id": "allowance",
        "board": {"size": [1, 1], "layers": {}},
        "state": {"avatar": {"enabled": False}},
        "goals": [],
        "loseConditions": lose_conditions,
    }


def test_prompt_shows_remaining_max_actions_allowance() -> None:
    game = _game()
    level = _level(
        [
            {"type": "variable_threshold", "config": {"variable": "caught", "target": 1}},
            {"type": "max_actions", "config": {"limit": 5}},
        ]
    )
    engine = TurnEngine(game, level)
    engine.state.action_count = 3

    prompt = build_prompt(game, level, engine.state)

    assert "Moves this attempt: 3 | Actions remaining: 2 of 5" in prompt


def test_prompt_does_not_invent_allowance_without_max_actions() -> None:
    game = _game()
    level = _level(
        [{"type": "variable_threshold", "config": {"variable": "caught", "target": 1}}]
    )
    engine = TurnEngine(game, level)

    prompt = build_prompt(game, level, engine.state)

    assert "Moves this attempt: 0" in prompt
    assert "Actions remaining:" not in prompt
