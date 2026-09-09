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
    "u_turn": {"left": "left"},
}


def _game(
    movement_mode="single_step",
    blocked_behavior="fail",
    allow_u_turns=True,
    exit_requires_route=True,
    routes=None,
    route_selector_layer=None,
) -> GameDef:
    kinds = {
        "void": {"layer": "ground", "tags": [], "symbol": "V"},
        "road_h": {"layer": "ground", "tags": ["route"], "symbol": "-"},
        "road_v": {"layer": "ground", "tags": ["route"], "symbol": "|"},
        "corner_ne": {"layer": "ground", "tags": ["route"], "symbol": "1"},
        "corner_se": {"layer": "ground", "tags": ["route"], "symbol": "2"},
        "corner_sw": {"layer": "ground", "tags": ["route"], "symbol": "3"},
        "corner_nw": {"layer": "ground", "tags": ["route"], "symbol": "4"},
        "u_turn": {"layer": "ground", "tags": ["route"], "symbol": "U"},
        "junction_t": {
            "layer": "ground",
            "tags": ["route"],
            "symbol": "+",
        },
        "truck": {
            "layer": "objects",
            "tags": ["routed_mover", "cargo"],
            "symbol": "T",
        },
        "barrier": {"layer": "objects", "tags": [], "symbol": "B"},
        "exit_red": {"layer": "markers", "tags": ["route_exit"], "symbol": "E"},
        "selector_up": {
            "layer": "markers",
            "tags": ["route_selector"],
            "symbol": "U",
        },
        "selector_right": {
            "layer": "markers",
            "tags": ["route_selector"],
            "symbol": "R",
        },
        "selector_yellow": {
            "layer": "markers",
            "tags": ["route_selector"],
            "symbol": "Y",
        },
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
                    "config": {
                        "routes": routes or ROUTES,
                        "failureVariable": "crashes",
                        "movementMode": movement_mode,
                        "blockedBehavior": blocked_behavior,
                        "allowUTurns": allow_u_turns,
                        "exitRequiresRoute": exit_requires_route,
                        **(
                            {"routeSelectorLayer": route_selector_layer}
                            if route_selector_layer
                            else {}
                        ),
                    },
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


class ContinuousRoutedMotionTest(unittest.TestCase):
    def setUp(self):
        self.game = _game("until_blocked", "stop", False)

    def test_connected_path_reaches_exit_in_one_action(self):
        level = _level(
            size=(4, 1),
            ground=[
                {"position": [x, 0], "kind": "road_h"} for x in range(4)
            ],
            objects=[
                {
                    "position": [0, 0],
                    "kind": "truck",
                    "heading": "right",
                    "color": "red",
                }
            ],
            markers=[
                {
                    "position": [3, 0],
                    "kind": "exit_red",
                    "color": "red",
                }
            ],
            with_goal=True,
        )
        engine = TurnEngine(self.game, level)

        result = engine.execute_turn("advance")

        self.assertTrue(result.is_won)
        self.assertEqual(engine.state.action_count, 1)
        self.assertEqual(list(engine.state.board.layers["objects"].entries()), [])
        path_event = next(
            event
            for event in result.events
            if event["type"] == "entity_path_moved"
        )
        self.assertEqual(
            path_event["path"],
            [Pos(0, 0), Pos(1, 0), Pos(2, 0), Pos(3, 0)],
        )

    def test_matching_exit_accepts_horizontal_and_vertical_arrivals(self):
        game = _game("until_blocked", "stop", False, False)
        cases = [
            (
                "horizontal",
                (2, 1),
                Pos(0, 0),
                Pos(1, 0),
                "road_h",
                "road_v",
                "right",
            ),
            (
                "vertical",
                (1, 2),
                Pos(0, 1),
                Pos(0, 0),
                "road_v",
                "road_h",
                "up",
            ),
        ]

        for name, size, source, target, source_road, target_road, heading in cases:
            with self.subTest(name=name):
                level = _level(
                    size=size,
                    ground=[
                        {"position": [source.x, source.y], "kind": source_road},
                        {"position": [target.x, target.y], "kind": target_road},
                    ],
                    objects=[
                        {
                            "position": [source.x, source.y],
                            "kind": "truck",
                            "heading": heading,
                            "color": "red",
                        }
                    ],
                    markers=[
                        {
                            "position": [target.x, target.y],
                            "kind": "exit_red",
                            "color": "red",
                        }
                    ],
                    with_goal=True,
                )
                engine = TurnEngine(game, level)

                result = engine.execute_turn("advance")

                self.assertTrue(result.is_won)
                self.assertEqual(
                    list(engine.state.board.layers["objects"].entries()), []
                )

    def test_junction_follows_its_local_selector_and_waits_without_one(self):
        routes = {
            **ROUTES,
            "junction_t": {
                "left": {
                    "selector_up": "up",
                    "selector_right": "right",
                }
            },
        }
        game = _game(
            "until_blocked",
            "stop",
            False,
            routes=routes,
            route_selector_layer="markers",
        )

        def build_engine(selector_kind):
            destination = [1, 0] if selector_kind == "selector_up" else [2, 1]
            return TurnEngine(
                game,
                _level(
                    size=(3, 2),
                    ground=[
                        {"position": [0, 1], "kind": "road_h"},
                        {"position": [1, 1], "kind": "junction_t"},
                        {"position": [2, 1], "kind": "road_h"},
                        {"position": [1, 0], "kind": "road_v"},
                    ],
                    objects=[
                        {
                            "position": [0, 1],
                            "kind": "truck",
                            "heading": "right",
                            "color": "red",
                        }
                    ],
                    markers=[
                        {"position": [1, 1], "kind": selector_kind},
                        {
                            "position": destination,
                            "kind": "exit_red",
                            "color": "red",
                        },
                    ],
                    with_goal=True,
                ),
            )

        expected_paths = {
            "selector_up": [Pos(0, 1), Pos(1, 1), Pos(1, 0)],
            "selector_right": [Pos(0, 1), Pos(1, 1), Pos(2, 1)],
        }
        for selector_kind, expected_path in expected_paths.items():
            with self.subTest(selector=selector_kind):
                engine = build_engine(selector_kind)
                result = engine.execute_turn("advance")
                self.assertTrue(result.is_won)
                path = next(
                    event
                    for event in result.events
                    if event["type"] == "entity_path_moved"
                )
                self.assertEqual(path["path"], expected_path)

        waiting = build_engine("selector_yellow")
        result = waiting.execute_turn("advance")
        self.assertFalse(result.is_won)
        self.assertIsNotNone(
            waiting.state.board.get_entity("objects", Pos(0, 1))
        )
        self.assertIn(
            "disconnected_road",
            {
                event["reason"]
                for event in result.events
                if event["type"] == "routed_motion_blocked"
            },
        )

    def test_disconnected_route_stops_without_crashing(self):
        level = _level(
            size=(3, 1),
            ground=[
                {"position": [0, 0], "kind": "road_h"},
                {"position": [1, 0], "kind": "road_h"},
                {"position": [2, 0], "kind": "road_v"},
            ],
            objects=[
                {"position": [0, 0], "kind": "truck", "heading": "right"}
            ],
        )
        engine = TurnEngine(self.game, level)

        result = engine.execute_turn("advance")

        self.assertFalse(result.is_lost)
        self.assertEqual(engine.state.variables["crashes"], 0)
        self.assertIsNotNone(
            engine.state.board.get_entity("objects", Pos(1, 0))
        )
        self.assertIn(
            "disconnected_road",
            {
                event["reason"]
                for event in result.events
                if event["type"] == "routed_motion_blocked"
            },
        )

    def test_closed_loop_runs_one_lap_and_terminates(self):
        level = _level(
            size=(2, 2),
            ground=[
                {"position": [0, 0], "kind": "corner_se"},
                {"position": [1, 0], "kind": "corner_sw"},
                {"position": [1, 1], "kind": "corner_nw"},
                {"position": [0, 1], "kind": "corner_ne"},
            ],
            objects=[
                {"position": [0, 0], "kind": "truck", "heading": "right"}
            ],
        )
        engine = TurnEngine(self.game, level)

        result = engine.execute_turn("advance")

        path_event = next(
            event
            for event in result.events
            if event["type"] == "entity_path_moved"
        )
        self.assertEqual(
            path_event["path"],
            [Pos(0, 0), Pos(1, 0), Pos(1, 1), Pos(0, 1), Pos(0, 0)],
        )
        self.assertIn(
            "route_cycle",
            {
                event["reason"]
                for event in result.events
                if event["type"] == "routed_motion_blocked"
            },
        )

    def test_u_turn_is_blocked_and_undo_restores_travel(self):
        u_turn_level = _level(
            size=(2, 1),
            ground=[
                {"position": [0, 0], "kind": "road_h"},
                {"position": [1, 0], "kind": "u_turn"},
            ],
            objects=[
                {"position": [0, 0], "kind": "truck", "heading": "right"}
            ],
        )
        u_turn_engine = TurnEngine(self.game, u_turn_level)
        u_turn_engine.execute_turn("advance")
        self.assertIsNotNone(
            u_turn_engine.state.board.get_entity("objects", Pos(0, 0))
        )

        path_level = _level(
            size=(3, 1),
            ground=[
                {"position": [x, 0], "kind": "road_h"} for x in range(3)
            ],
            objects=[
                {"position": [0, 0], "kind": "truck", "heading": "right"}
            ],
        )
        path_engine = TurnEngine(self.game, path_level)
        path_engine.execute_turn("advance")
        self.assertIsNotNone(
            path_engine.state.board.get_entity("objects", Pos(2, 0))
        )
        path_engine.undo()
        self.assertIsNotNone(
            path_engine.state.board.get_entity("objects", Pos(0, 0))
        )


if __name__ == "__main__":
    unittest.main()
