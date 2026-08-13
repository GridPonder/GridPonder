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


def _level(lose_after: int | None = None) -> dict:
    # 4x1 board:  H H E H  — the avatar starts at the left end. Reaching the
    # exit wins, and a walkable cell remains past it, so an action taken after
    # the win is refused because the level is over, not because it is illegal.
    # `lose_after` caps the action count, which is how the loss case is set up.
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
        "loseConditions": (
            [{"type": "max_actions", "config": {"limit": lose_after}}]
            if lose_after is not None
            else []
        ),
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

    def test_preview_exposes_the_board_it_would_produce(self):
        engine = TurnEngine(_game(), _level())

        result = engine.preview_turn("move", {"direction": "right"})

        # The whole point of a dry run: read the would-be board without
        # entering it. The live board is untouched at the same moment.
        self.assertIsNotNone(result.new_state)
        self.assertEqual(result.new_state.avatar.position, Pos(1, 0))
        self.assertEqual(engine.state.avatar.position, Pos(0, 0))

    def test_preview_commits_nothing(self):
        engine = TurnEngine(_game(), _level())

        engine.preview_turn("move", {"direction": "right"})

        # Position, both counters, the undo stack and both flags are exactly
        # as they were.
        self.assertEqual(engine.state.avatar.position, Pos(0, 0))
        self.assertEqual(engine.state.action_count, 0)
        self.assertEqual(engine.state.turn_count, 0)
        self.assertEqual(engine.undo_depth, 0)
        self.assertFalse(engine.is_won)
        self.assertFalse(engine.is_lost)

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

    def test_preview_on_a_lost_level_is_refused(self):
        # One action allowed, and one step is not enough to reach the exit.
        engine = TurnEngine(_game(), _level(lose_after=1))
        engine.execute_turn("move", {"direction": "right"})
        self.assertTrue(engine.is_lost)

        result = engine.preview_turn("move", {"direction": "right"})

        self.assertFalse(result.accepted)
        self.assertEqual(result.events, [])


if __name__ == "__main__":
    unittest.main()
