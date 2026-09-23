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

    assert "Moves this attempt: 3 of 5 allowed" in prompt


def test_prompt_does_not_invent_allowance_without_max_actions() -> None:
    game = _game()
    level = _level(
        [{"type": "variable_threshold", "config": {"variable": "caught", "target": 1}}]
    )
    engine = TurnEngine(game, level)

    prompt = build_prompt(game, level, engine.state)

    assert "Moves this attempt: 0" in prompt
    assert "allowed" not in prompt


def _won_and_lost_level(lose_conditions: list[dict]) -> dict:
    level = _level(lose_conditions)
    level["state"]["variables"] = {"score": 0, "heat": 0}
    level["goals"] = [{"id": "g", "type": "variable_threshold",
                       "config": {"variable": "score", "comparison": "gte", "target": 0}}]
    return level


def test_a_turn_that_wins_and_breaks_a_lose_condition_is_a_loss() -> None:
    game = _game()
    engine = TurnEngine(game, _won_and_lost_level([
        {"type": "variable_threshold",
         "config": {"variable": "heat", "comparison": "gte", "target": 0}},
    ]))
    result = engine.execute_turn("wait", {})
    assert result.accepted
    assert result.is_lost and not result.is_won
    assert engine.is_lost and not engine.is_won


def test_winning_on_the_last_allowed_move_is_still_a_win() -> None:
    game = _game()
    engine = TurnEngine(game, _won_and_lost_level([
        {"type": "max_actions", "config": {"limit": 1}},
    ]))
    result = engine.execute_turn("wait", {})
    assert result.is_won and not result.is_lost


def test_text_prompt_states_the_coordinate_convention_once() -> None:
    game = _game()
    level = _level([])
    engine = TurnEngine(game, level)
    prompt = build_prompt(game, level, engine.state)
    assert prompt.count("(0,0) is the top-left cell") == 1
    assert "column x, row y" in prompt


def test_anonymous_labels_stay_one_character_past_26_kinds() -> None:
    from engines.python.anon import build_anon_kind_to_label

    kinds = {f"k{i:02d}": {"layer": "ground", "symbol": chr(0x100 + i)}
             for i in range(70)}
    kinds["floor"] = {"layer": "ground", "symbol": "."}
    game = GameDef.from_dict({
        "layers": [{"id": "ground", "occupancy": "exactly_one", "default": "floor"}],
        "entityKinds": kinds,
    })
    labels = build_anon_kind_to_label(game)
    assert len(labels) == 70
    assert all(len(label) == 1 for label in labels.values())
    assert len(set(labels.values())) == 70
    assert not set(labels.values()) & {".", "?", "@", "·", "=", "+", "(", ")", ",", ":"}
