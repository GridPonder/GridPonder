"""Parity tests for cell_rotation + routed_motion."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine


ROUTES = {
    "road_h": {"left": "right", "right": "left"},
    "road_v": {"up": "down", "down": "up"},
    "corner_ne": {"up": "right", "right": "up"},
    "corner_se": {"right": "down", "down": "right"},
    "corner_sw": {"down": "left", "left": "down"},
    "corner_nw": {"left": "up", "up": "left"},
}


def _game() -> GameDef:
    kinds = {
        "void": {"layer": "ground", "tags": [], "symbol": "V"},
        "road_h": {"layer": "ground", "tags": ["route"], "symbol": "-"},
        "road_v": {"layer": "ground", "tags": ["route"], "symbol": "|"},
        "corner_ne": {"layer": "ground", "tags": ["route"], "symbol": "1"},
        "corner_se": {"layer": "ground", "tags": ["route"], "symbol": "2"},
        "corner_sw": {"layer": "ground", "tags": ["route"], "symbol": "3"},
        "corner_nw": {"layer": "ground", "tags": ["route"], "symbol": "4"},
        "truck": {
            "layer": "objects",
            "tags": ["routed_mover", "cargo"],
            "symbol": "T",
        },
        "barrier": {"layer": "objects", "tags": [], "symbol": "B"},
        "exit_red": {"layer": "markers", "tags": ["route_exit"], "symbol": "E"},
    }
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "void"},
                {"id": "markers", "occupancy": "zero_or_one"},
                {"id": "objects", "occupancy": "zero_or_one"},
            ],
            "entityKinds": kinds,
            "actions": [
                {"id": "rotate_cell", "params": {"position": {"type": "position"}}},
                {"id": "advance", "params": {}},
            ],
            "systems": [
                {
                    "id": "rotate_roads",
                    "type": "cell_rotation",
                    "config": {
                        "cycles": {
                            "road_h": "road_v",
                            "road_v": "road_h",
                            "corner_ne": "corner_se",
                            "corner_se": "corner_sw",
                            "corner_sw": "corner_nw",
                            "corner_nw": "corner_ne",
                        }
                    },
                },
                {
                    "id": "traffic",
                    "type": "routed_motion",
                    "config": {"routes": ROUTES, "failureVariable": "crashes"},
                },
            ],
        }
    )


def _level(
    *,
    size=(3, 2),
    ground: list[dict] | None = None,
    objects: list[dict] | None = None,
    markers: list[dict] | None = None,
    with_goal: bool = False,
) -> dict:
    return {
        "id": "route_test",
        "board": {
            "size": list(size),
            "layers": {
                "ground": {"format": "sparse", "entries": ground or []},
                "objects": {"format": "sparse", "entries": objects or []},
                "markers": {"format": "sparse", "entries": markers or []},
            },
        },
        "state": {"avatar": {"enabled": False}, "variables": {"crashes": 0}},
        "goals": (
            [{"id": "deliver", "type": "all_cleared", "config": {"tag": "cargo"}}]
            if with_goal
            else []
        ),
        "loseConditions": [
            {
                "type": "variable_threshold",
                "config": {"variable": "crashes", "target": 1, "comparison": "gte"},
            }
        ],
    }


def _prototype_level() -> dict:
    return _level(
        ground=[
            {"position": [2, 0], "kind": "road_v"},
            {"position": [0, 1], "kind": "road_h"},
            {"position": [1, 1], "kind": "road_h"},
            {"position": [2, 1], "kind": "corner_se"},
        ],
        objects=[
            {"position": [0, 1], "kind": "truck", "heading": "right", "color": "red"}
        ],
        markers=[
            {"position": [2, 0], "kind": "exit_red", "color": "red"}
        ],
        with_goal=True,
    )


class RoutedMotionTest(unittest.TestCase):
    def test_first_level_gold_path_requires_preparing_the_corner(self):
        engine = TurnEngine(_game(), _prototype_level())

        first = engine.execute_turn("rotate_cell", {"position": [2, 1]})
        second = engine.execute_turn("rotate_cell", {"position": [2, 1]})
        third = engine.execute_turn("advance")

        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)
        self.assertTrue(third.is_won)
        self.assertIsNone(engine.state.board.get_entity("objects", Pos(2, 0)))
        self.assertEqual(engine.state.action_count, 3)

    def test_occupied_road_cannot_rotate_and_does_not_tick_traffic(self):
        engine = TurnEngine(_game(), _prototype_level())

        result = engine.execute_turn("rotate_cell", {"position": [0, 1]})

        self.assertFalse(result.accepted)
        self.assertIsNotNone(engine.state.board.get_entity("objects", Pos(0, 1)))
        self.assertEqual(engine.state.action_count, 0)

    def test_unprepared_corner_loses_without_partially_moving(self):
        engine = TurnEngine(_game(), _prototype_level())
        engine.execute_turn("advance")

        result = engine.execute_turn("advance")

        self.assertTrue(result.is_lost)
        self.assertEqual(engine.state.variables["crashes"], 1)
        self.assertIsNotNone(engine.state.board.get_entity("objects", Pos(1, 1)))
        self.assertIsNone(engine.state.board.get_entity("objects", Pos(2, 1)))

    def test_convoy_can_enter_cells_vacated_on_the_same_tick(self):
        level = _level(
            size=(4, 1),
            ground=[
                {"position": [x, 0], "kind": "road_h"} for x in range(4)
            ],
            objects=[
                {"position": [0, 0], "kind": "truck", "heading": "right"},
                {"position": [1, 0], "kind": "truck", "heading": "right"},
            ],
        )
        engine = TurnEngine(_game(), level)

        result = engine.execute_turn("advance")

        self.assertTrue(result.accepted)
        self.assertEqual(engine.state.variables["crashes"], 0)
        self.assertIsNotNone(engine.state.board.get_entity("objects", Pos(1, 0)))
        self.assertIsNotNone(engine.state.board.get_entity("objects", Pos(2, 0)))

    def test_two_trucks_claiming_one_destination_fail_atomically(self):
        level = _level(
            size=(3, 1),
            ground=[
                {"position": [x, 0], "kind": "road_h"} for x in range(3)
            ],
            objects=[
                {"position": [0, 0], "kind": "truck", "heading": "right"},
                {"position": [2, 0], "kind": "truck", "heading": "left"},
            ],
        )
        engine = TurnEngine(_game(), level)

        result = engine.execute_turn("advance")

        self.assertTrue(result.is_lost)
        self.assertIsNotNone(engine.state.board.get_entity("objects", Pos(0, 0)))
        self.assertIsNotNone(engine.state.board.get_entity("objects", Pos(2, 0)))
        failures = [e for e in result.events if e["type"] == "routed_motion_failed"]
        self.assertEqual({e["reason"] for e in failures}, {"same_destination"})


if __name__ == "__main__":
    unittest.main()
