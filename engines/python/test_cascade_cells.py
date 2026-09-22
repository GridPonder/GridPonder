"""Parity tests for the generic synchronous cascade_cells system."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine


def _cell(charge: int, *, threshold: int = 4, kernel: str = "plus") -> dict:
    return {
        "kind": "cascade_cell",
        "charge": charge,
        "threshold": threshold,
        "kernel": kernel,
    }


def _game(config=None) -> GameDef:
    data = {
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
            {"id": "objects", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "floor": {"layer": "ground", "tags": ["walkable"], "symbol": "."},
            "cascade_cell": {
                "layer": "objects",
                "tags": ["cascade_cell"],
                "symbol": "C",
                "symbolParam": "charge",
                "params": {
                    "charge": {"type": "integer", "required": True},
                    "threshold": {"type": "integer", "required": True},
                    "kernel": {"type": "string", "required": True},
                },
            },
        },
        "actions": [
            {"id": "tap_cell", "params": {"position": {"type": "position"}}}
        ],
        "systems": [
            {"id": "cascade", "type": "cascade_cells", "config": config or {}}
        ],
        "defaults": {"avatar": {"enabled": False}},
    }
    return GameDef.from_dict(data)


def _level(objects, *, goals=None, lose=None) -> dict:
    height = len(objects)
    width = len(objects[0])
    return {
        "id": "cascade_test",
        "board": {"size": [width, height], "layers": {"objects": objects}},
        "state": {"avatar": {"enabled": False}},
        "goals": goals or [],
        "loseConditions": lose or [],
    }


def _charges(engine: TurnEngine) -> list[list[int]]:
    return [
        [
            engine.state.board.get_entity("objects", Pos(x, y)).param("charge")
            for x in range(engine.state.board.width)
        ]
        for y in range(engine.state.board.height)
    ]


class CascadeCellsTests(unittest.TestCase):
    def test_center_click_resolves_three_waves_and_matches_charge_target(self):
        initial = [
            [_cell(1), _cell(3), _cell(1)],
            [_cell(3), _cell(3), _cell(3)],
            [_cell(1), _cell(3), _cell(1)],
        ]
        target = [
            [{"kind": "cascade_cell", "charge": 3}, {"kind": "cascade_cell", "charge": 1}, {"kind": "cascade_cell", "charge": 3}],
            [{"kind": "cascade_cell", "charge": 1}, {"kind": "cascade_cell", "charge": 0}, {"kind": "cascade_cell", "charge": 1}],
            [{"kind": "cascade_cell", "charge": 3}, {"kind": "cascade_cell", "charge": 1}, {"kind": "cascade_cell", "charge": 3}],
        ]
        goals = [{
            "id": "target",
            "type": "board_match",
            "config": {
                "targetLayers": {"objects": target},
                "matchMode": "exact",
                "matchParams": ["charge"],
            },
        }]
        engine = TurnEngine(_game(), _level(initial, goals=goals))

        result = engine.execute_turn("tap_cell", {"position": [1, 1]})

        self.assertTrue(result.accepted)
        self.assertTrue(result.is_won)
        self.assertEqual(_charges(engine), [[3, 1, 3], [1, 0, 1], [3, 1, 3]])
        self.assertEqual(
            [event["wave"] for event in result.events if event["type"] == "cascade_wave_started"],
            [1, 2, 3],
        )
        self.assertEqual(engine.state.action_count, 1)

    def test_each_builtin_kernel_hits_only_its_offsets(self):
        expected = {
            "plus": {(2, 1), (3, 2), (2, 3), (1, 2)},
            "x": {(1, 1), (3, 1), (3, 3), (1, 3)},
            "h": {(1, 2), (3, 2)},
            "v": {(2, 1), (2, 3)},
        }
        for kernel, destinations in expected.items():
            with self.subTest(kernel=kernel):
                board = [[_cell(0) for _ in range(5)] for _ in range(5)]
                board[2][2] = _cell(3, kernel=kernel)
                engine = TurnEngine(_game(), _level(board))
                result = engine.execute_turn("tap_cell", {"position": [2, 2]})
                self.assertTrue(result.accepted)
                for y in range(5):
                    for x in range(5):
                        expected_charge = 1 if (x, y) in destinations else 0
                        self.assertEqual(
                            engine.state.board.get_entity(
                                "objects", Pos(x, y)
                            ).param("charge"),
                            expected_charge,
                            (kernel, x, y),
                        )

    def test_overflow_can_make_one_cell_explode_in_consecutive_waves(self):
        config = {
            "kernels": {
                "burst": [[1, 0], [1, 0], [1, 0], [1, 0], [1, 0]],
                "none": [],
            }
        }
        engine = TurnEngine(
            _game(config),
            _level([[_cell(3, kernel="burst"), _cell(3, kernel="none")]]),
        )

        result = engine.execute_turn("tap_cell", {"position": [0, 0]})

        self.assertTrue(result.accepted)
        self.assertEqual(_charges(engine), [[0, 0]])
        exploded = [
            (event["position"], event["wave"])
            for event in result.events
            if event["type"] == "cell_exploded"
        ]
        self.assertEqual(
            exploded,
            [(Pos(0, 0), 1), (Pos(1, 0), 2), (Pos(1, 0), 3)],
        )

    def test_invalid_click_is_vetoed_without_counting(self):
        engine = TurnEngine(_game(), _level([[_cell(0), None]]))
        before = engine.state.to_key()

        result = engine.execute_turn("tap_cell", {"position": [1, 0]})

        self.assertFalse(result.accepted)
        self.assertEqual(engine.state.to_key(), before)
        self.assertEqual(engine.state.action_count, 0)

    def test_wave_limit_veto_rolls_back_the_complete_transition(self):
        config = {
            "maxWaves": 2,
            "kernels": {"loop": [[0, 0], [0, 0], [0, 0], [0, 0]]},
        }
        engine = TurnEngine(
            _game(config), _level([[_cell(3, kernel="loop")]])
        )
        before = engine.state.to_key()

        result = engine.execute_turn("tap_cell", {"position": [0, 0]})

        self.assertFalse(result.accepted)
        self.assertEqual([event["type"] for event in result.events], ["action_vetoed"])
        self.assertEqual(engine.state.to_key(), before)
        self.assertEqual(engine.state.action_count, 0)

    def test_per_cell_threshold_is_respected(self):
        engine = TurnEngine(
            _game(),
            _level([[_cell(1, threshold=2, kernel="h"), _cell(0)]]),
        )

        result = engine.execute_turn("tap_cell", {"position": [0, 0]})

        self.assertTrue(result.accepted)
        self.assertEqual(_charges(engine), [[0, 1]])


if __name__ == "__main__":
    unittest.main()
