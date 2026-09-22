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


def test_position_parameters_enumerate_every_board_coordinate_row_major() -> None:
    game = GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "floor"}
            ],
            "entityKinds": {
                "floor": {"layer": "ground", "tags": [], "symbol": "."}
            },
            "actions": [
                {
                    "id": "tap_cell",
                    "params": {"position": {"type": "position"}},
                }
            ],
        }
    )
    engine = TurnEngine(
        game,
        {
            "board": {"size": [2, 2], "layers": {}},
            "state": {"avatar": {"enabled": False}},
            "goals": [],
        },
    )

    assert enumerate_actions(game, engine.state) == [
        {"action": "tap_cell", "position": [0, 0]},
        {"action": "tap_cell", "position": [1, 0]},
        {"action": "tap_cell", "position": [0, 1]},
        {"action": "tap_cell", "position": [1, 1]},
    ]


if __name__ == "__main__":
    test_engine_probe_filters_vetoed_and_no_effect_actions()
    test_position_parameters_enumerate_every_board_coordinate_row_major()
    print("2 passed")
