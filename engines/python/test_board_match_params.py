"""Parameter-aware board_match remains opt-in and backward compatible."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._goal import evaluate_goals
from engines.python._models import Board, GameState


class BoardMatchParamsTests(unittest.TestCase):
    def setUp(self):
        self.game = GameDef.from_dict({
            "layers": [{"id": "objects", "occupancy": "zero_or_one"}],
            "entityKinds": {
                "cell": {
                    "layer": "objects",
                    "tags": [],
                    "symbol": "C",
                    "params": {"charge": {"type": "integer"}},
                }
            },
            "actions": [],
            "systems": [],
        })
        board = Board.from_json({
            "size": [2, 1],
            "layers": {"objects": [[
                {"kind": "cell", "charge": 1},
                {"kind": "cell", "charge": 2},
            ]]},
        }, self.game.layers)
        self.state = GameState.from_json({}, board, self.game.defaults)

    def _evaluate(self, target, match_params=None):
        config = {
            "targetLayers": {"objects": [target]},
            "matchMode": "exact",
        }
        if match_params is not None:
            config["matchParams"] = match_params
        goals = [{"id": "target", "type": "board_match", "config": config}]
        return evaluate_goals(goals, self.state, self.game, [])

    def test_kind_only_behavior_is_unchanged_when_match_params_is_absent(self):
        won, progress, _ = self._evaluate([
            {"kind": "cell", "charge": 9},
            {"kind": "cell", "charge": 9},
        ])
        self.assertTrue(won)
        self.assertEqual(progress["target"], 1.0)

    def test_selected_param_must_match_exactly(self):
        won, progress, _ = self._evaluate([
            {"kind": "cell", "charge": 1},
            {"kind": "cell", "charge": 9},
        ], ["charge"])
        self.assertFalse(won)
        self.assertEqual(progress["target"], 0.5)

    def test_target_must_name_every_selected_param(self):
        won, progress, _ = self._evaluate([
            {"kind": "cell", "charge": 1},
            {"kind": "cell"},
        ], ["charge"])
        self.assertFalse(won)
        self.assertEqual(progress["target"], 0.5)


if __name__ == "__main__":
    unittest.main()
