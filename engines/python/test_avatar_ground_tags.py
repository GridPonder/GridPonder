"""avatar_navigation.validGroundTags — the target's ground must carry a tag."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine


def _game(valid_ground_tags: list[str] | None) -> GameDef:
    config: dict = {}
    if valid_ground_tags is not None:
        config["validGroundTags"] = valid_ground_tags
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "void"},
            ],
            "entityKinds": {
                "void": {"layer": "ground", "tags": [], "symbol": " "},
                "hull": {"layer": "ground", "tags": ["walkable"], "symbol": "H"},
                "wreck": {"layer": "ground", "tags": ["solid"], "symbol": "w"},
            },
            "actions": [
                {
                    "id": "move",
                    "params": {
                        "direction": {
                            "type": "direction",
                            "values": ["up", "down", "left", "right"],
                        }
                    },
                },
            ],
            "systems": [
                {"id": "nav", "type": "avatar_navigation", "config": config},
            ],
        },
        id="ground_tags_test",
    )


def _level() -> dict:
    # 3x1 board:  H w H  — the avatar starts on the left hull plate.
    return {
        "id": "ground_tags",
        "board": {
            "size": [3, 1],
            "layers": {
                "ground": {
                    "format": "sparse",
                    "entries": [
                        {"position": [0, 0], "kind": "hull"},
                        {"position": [1, 0], "kind": "wreck"},
                        {"position": [2, 0], "kind": "hull"},
                    ],
                }
            },
        },
        "state": {"avatar": {"enabled": True, "position": [0, 0]}},
        "goals": [],
        "rules": [],
        "solution": {"goldPath": []},
    }


class AvatarGroundTagsTest(unittest.TestCase):
    def test_move_onto_untagged_ground_is_rejected(self):
        game = _game(["walkable"])
        engine = TurnEngine(game, _level())

        engine.execute_turn("move", {"direction": "right"})

        # wreck is not walkable — the avatar stays put.
        self.assertEqual(engine.state.avatar.position, Pos(0, 0))

    def test_move_onto_tagged_ground_is_allowed(self):
        game = _game(["walkable"])
        engine = TurnEngine(game, _level())
        engine.state.avatar.position = Pos(1, 0)

        engine.execute_turn("move", {"direction": "right"})

        # hull at (2,0) is walkable — the move succeeds.
        self.assertEqual(engine.state.avatar.position, Pos(2, 0))

    def test_absent_config_preserves_existing_behaviour(self):
        game = _game(None)
        engine = TurnEngine(game, _level())

        engine.execute_turn("move", {"direction": "right"})

        # No validGroundTags: wreck is non-void ground with nothing solid on the
        # objects layer, so the move succeeds exactly as it does today.
        self.assertEqual(engine.state.avatar.position, Pos(1, 0))


if __name__ == "__main__":
    unittest.main()
