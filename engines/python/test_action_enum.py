from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._turn_engine import TurnEngine
from engines.python.action_enum import enumerate_actions


def _game() -> GameDef:
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "empty"}
            ],
            "entityKinds": {
                "empty": {"layer": "ground", "tags": ["walkable"], "symbol": "."},
                "void": {"layer": "ground", "tags": ["solid"], "symbol": "#"},
            },
            "actions": [
                {
                    "id": "move",
                    "params": {
                        "direction": {
                            "type": "direction",
                            "values": ["left", "right"],
                        }
                    },
                },
                {"id": "unused"},
            ],
            "systems": [
                {
                    "id": "nav",
                    "type": "avatar_navigation",
                    "config": {"moveAction": "move", "solidHandling": "block"},
                }
            ],
        }
    )


def _level() -> dict:
    return {
        "board": {
            "size": [3, 1],
            "layers": {
                "ground": [
                    ["void", "empty", "empty"],
                ]
            },
        },
        "state": {"avatar": {"enabled": True, "position": [1, 0]}},
        "goals": [],
    }


def test_engine_probe_filters_vetoed_and_no_effect_actions() -> None:
    game = _game()
    engine = TurnEngine(game, _level())

    assert enumerate_actions(game, engine.state, engine=engine) == [
        {"action": "move", "direction": "right"}
    ]
    assert engine.state.avatar.position.x == 1
    assert engine.undo_depth == 0


def _select_game() -> GameDef:
    """Two selectable pieces over a wall row; `tap_cell` takes a position.
    Mirrors `_selectGame` in engines/dart/test/agent_action_enum_test.dart."""
    return GameDef.from_dict({
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "actors", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"], "symbol": "."},
            "wall": {"layer": "ground", "tags": ["solid"], "symbol": "#"},
            "wei": {"layer": "actors", "tags": ["actor"], "symbol": "W"},
            "shu": {"layer": "actors", "tags": ["actor"], "symbol": "S"},
        },
        "actions": [
            {"id": "move", "params": {"direction": {
                "type": "direction", "values": ["up", "down", "left", "right"]}}},
            {"id": "tap_cell", "params": {"position": {"type": "position"}}},
        ],
        "systems": [{"id": "individual", "type": "individual_actors", "config": {}}],
    })


def _select_level() -> dict:
    return {
        "board": {
            "size": [3, 2],
            "layers": {
                "ground": [["empty", "empty", "empty"], ["wall", "wall", "wall"]],
                "actors": {"format": "sparse", "entries": [
                    {"position": [0, 0], "kind": "wei"},
                    {"position": [2, 0], "kind": "shu"},
                ]},
            },
        },
        "state": {"avatar": {"enabled": False}},
        "goals": [],
    }


def test_retapping_the_selected_piece_is_not_offered() -> None:
    """A tap whose only event is `actor_selected` and that leaves the state
    key unchanged re-selects what is already selected: not effectful."""
    game = _select_game()
    engine = TurnEngine(game, _select_level())
    assert enumerate_actions(game, engine.state, engine=engine) == [
        {"action": "tap_cell", "position": [0, 0]},
        {"action": "tap_cell", "position": [2, 0]},
    ]
    assert engine.execute_turn("tap_cell", {"position": [0, 0]}).accepted
    key = engine.state_key()
    assert enumerate_actions(game, engine.state, engine=engine) == [
        {"action": "move", "direction": "up"},
        {"action": "move", "direction": "down"},
        {"action": "move", "direction": "left"},
        {"action": "move", "direction": "right"},
        {"action": "tap_cell", "position": [2, 0]},
    ]
    assert engine.state_key() == key
    assert engine.undo_depth == 1


def _machine_game(frequency: int) -> GameDef:
    """One patrolling machine and a bare `wait` action."""
    return GameDef.from_dict({
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "actors", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"], "symbol": "."},
            "machine": {"layer": "actors", "tags": ["npc", "solid"], "symbol": "M"},
        },
        "actions": [{"id": "wait"}],
        "systems": [{"id": "machines", "type": "follower_npcs", "config": {
            "behaviors": {"line": {"type": "patrol", "solidBlocking": True,
                                   "frequency": frequency}}}}],
    })


def _machine_level(width: int) -> dict:
    return {
        "board": {"size": [width, 1], "layers": {"actors": {"format": "sparse", "entries": [
            {"position": [0, 0], "kind": "machine", "behavior": "line", "facing": "right"},
        ]}}},
        "state": {"avatar": {"enabled": False}},
        "goals": [],
    }


def test_an_off_beat_wait_is_offered_when_a_slow_machine_is_on_the_board() -> None:
    """The state key leaves the turn counter out. A frequency-2 machine idles
    on the 2nd beat, so that `wait` changes no key — but it moves the machine
    onto its next active beat, so it is still a move worth offering."""
    game = _machine_game(2)
    engine = TurnEngine(game, _machine_level(3))
    assert engine.turn_count_matters()
    assert engine.execute_turn("wait", {}).accepted  # beat 1: the machine steps
    key = engine.state_key()
    assert enumerate_actions(game, engine.state, engine=engine) == [{"action": "wait"}]
    assert engine.execute_turn("wait", {}).accepted  # beat 2: idle
    assert engine.state_key() == key


def test_a_wait_that_changes_nothing_is_not_offered_without_a_slow_machine() -> None:
    game = _machine_game(1)
    engine = TurnEngine(game, _machine_level(1))  # boxed in: never moves
    assert not engine.turn_count_matters()
    assert enumerate_actions(game, engine.state, engine=engine) == []


if __name__ == "__main__":
    test_engine_probe_filters_vetoed_and_no_effect_actions()
    test_retapping_the_selected_piece_is_not_offered()
    test_an_off_beat_wait_is_offered_when_a_slow_machine_is_on_the_board()
    test_a_wait_that_changes_nothing_is_not_offered_without_a_slow_machine()
    print("4 passed")
