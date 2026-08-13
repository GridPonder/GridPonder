"""preview_turn — a dry run must answer "what would this do?" and change nothing.

Kept in lockstep with engines/dart/test/engine/turn_preview_test.dart: the two
engines must agree on what a preview reports and on when an action is refused.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine


def _game() -> GameDef:
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "void"},
            ],
            "entityKinds": {
                "void": {"layer": "ground", "tags": [], "symbol": " "},
                "hull": {"layer": "ground", "tags": ["walkable"], "symbol": "H"},
                "exit": {"layer": "ground", "tags": ["walkable"], "symbol": "E"},
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
                {
                    "id": "nav",
                    "type": "avatar_navigation",
                    "config": {"validGroundTags": ["walkable"]},
                },
            ],
        },
        id="turn_preview_test",
    )


def _level() -> dict:
    # 4x1 board:  H H E H  — the avatar starts at the left end. Reaching the
    # exit wins, and a walkable cell remains past it, so an action taken after
    # the win is refused because the level is over, not because it is illegal.
    return {
        "id": "turn_preview",
        "board": {
            "size": [4, 1],
            "layers": {
                "ground": {
                    "format": "sparse",
                    "entries": [
                        {"position": [0, 0], "kind": "hull"},
                        {"position": [1, 0], "kind": "hull"},
                        {"position": [2, 0], "kind": "exit"},
                        {"position": [3, 0], "kind": "hull"},
                    ],
                }
            },
        },
        "state": {"avatar": {"enabled": True, "position": [0, 0]}},
        "goals": [
            {
                "id": "reach_exit",
                "type": "reach_target",
                "config": {"targetKind": "exit"},
            }
        ],
        "rules": [],
        "solution": {"goldPath": []},
    }


def _walk_to_exit(engine: TurnEngine) -> None:
    engine.execute_turn("move", {"direction": "right"})
    engine.execute_turn("move", {"direction": "right"})


class TurnPreviewTest(unittest.TestCase):
    def test_preview_reports_what_the_turn_would_do(self):
        engine = TurnEngine(_game(), _level())

        result = engine.preview_turn("move", {"direction": "right"})

        self.assertTrue(result.accepted)
        entered = [e for e in result.events if e["type"] == "avatar_entered"]
        self.assertEqual([e["position"] for e in entered], [Pos(1, 0)])

    def test_preview_commits_nothing(self):
        engine = TurnEngine(_game(), _level())

        engine.preview_turn("move", {"direction": "right"})

        # Position, both counters and the undo stack are exactly as they were.
        self.assertEqual(engine.state.avatar.position, Pos(0, 0))
        self.assertEqual(engine.state.action_count, 0)
        self.assertEqual(engine.state.turn_count, 0)
        self.assertEqual(engine.undo_depth, 0)

    def test_preview_matches_the_turn_it_predicts(self):
        engine = TurnEngine(_game(), _level())

        predicted = engine.preview_turn("move", {"direction": "right"})
        actual = engine.execute_turn("move", {"direction": "right"})

        self.assertEqual(predicted.accepted, actual.accepted)
        self.assertEqual(predicted.events, actual.events)

    def test_a_won_level_refuses_further_actions(self):
        engine = TurnEngine(_game(), _level())
        _walk_to_exit(engine)
        self.assertTrue(engine.is_won)

        result = engine.execute_turn("move", {"direction": "right"})

        # (3,0) is walkable, so only the win can be refusing this.
        self.assertFalse(result.accepted)
        self.assertEqual(engine.state.avatar.position, Pos(2, 0))
        self.assertEqual(engine.state.action_count, 2)
        self.assertEqual(engine.state.turn_count, 2)

    def test_preview_on_a_won_level_is_refused(self):
        engine = TurnEngine(_game(), _level())
        _walk_to_exit(engine)

        result = engine.preview_turn("move", {"direction": "right"})

        self.assertFalse(result.accepted)
        self.assertEqual(result.events, [])


if __name__ == "__main__":
    unittest.main()
