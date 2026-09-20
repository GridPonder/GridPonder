"""Parity tests for local routed-motion gates driven by turn_cycle."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine


def _game(
    *, signal_first: bool = False, cycle_config_overrides=None
) -> GameDef:
    cycle_config_overrides = cycle_config_overrides or {}
    data = {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "void"},
                {"id": "markers", "occupancy": "zero_or_one"},
                {"id": "objects", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "void": {"layer": "ground", "tags": [], "symbol": "V"},
                "road_h": {
                    "layer": "ground",
                    "tags": ["route"],
                    "symbol": "-",
                },
                "road_v": {
                    "layer": "ground",
                    "tags": ["route"],
                    "symbol": "|",
                },
                "car": {
                    "layer": "objects",
                    "tags": ["routed_mover", "vehicle"],
                    "symbol": "C",
                },
                "exit": {
                    "layer": "markers",
                    "tags": ["route_exit"],
                    "symbol": "E",
                },
                "signal_red": {
                    "layer": "markers",
                    "tags": ["route_signal", "route_closed"],
                    "symbol": "R",
                },
                "signal_yellow_to_green": {
                    "layer": "markers",
                    "tags": ["route_signal", "route_closed"],
                    "symbol": "A",
                },
                "signal_green": {
                    "layer": "markers",
                    "tags": ["route_signal"],
                    "symbol": "G",
                },
                "signal_yellow_to_red": {
                    "layer": "markers",
                    "tags": ["route_signal", "route_closed"],
                    "symbol": "Y",
                },
            },
            "actions": [
                {"id": "rotate_cell", "params": {"position": {"type": "position"}}}
            ],
            "systems": [
                {
                    "id": "rotate_roads",
                    "type": "cell_rotation",
                    "config": {
                        "cycles": {"road_h": "road_v", "road_v": "road_h"},
                        "blockingLayers": ["objects"],
                        "blockingTags": ["routed_mover"],
                    },
                },
                {
                    "id": "traffic",
                    "type": "routed_motion",
                    "config": {
                        "routes": {
                            "road_h": {"left": "right", "right": "left"},
                            "road_v": {"up": "down", "down": "up"},
                        },
                        "movementMode": "until_blocked",
                        "blockedBehavior": "stop",
                        "matchParam": "color",
                        "exitMatchParam": "color",
                        "gateLayer": "markers",
                    },
                },
                {
                    "id": "signal_clock",
                    "type": "turn_cycle",
                    "config": {
                        "triggerActions": ["rotate_cell"],
                        "layer": "markers",
                        "cycles": {
                            "signal_red": "signal_yellow_to_green",
                            "signal_yellow_to_green": "signal_green",
                            "signal_green": "signal_yellow_to_red",
                            "signal_yellow_to_red": "signal_red",
                        },
                        **cycle_config_overrides,
                    },
                },
            ],
        }
    if signal_first:
        signal_clock = data["systems"].pop()
        data["systems"].insert(1, signal_clock)
    return GameDef.from_dict(data)


def _level(*, reverse: bool = False) -> dict:
    car_x = 3 if reverse else 0
    exit_x = 0 if reverse else 3
    return {
        "id": "signal_test",
        "board": {
            "size": [4, 2],
            "layers": {
                "ground": {
                    "format": "sparse",
                    "entries": [
                        *[
                            {"position": [x, 0], "kind": "road_h"}
                            for x in range(4)
                        ],
                        {"position": [0, 1], "kind": "road_h"},
                    ],
                },
                "markers": {
                    "format": "sparse",
                    "entries": [
                        {"position": [exit_x, 0], "kind": "exit"},
                        {
                            "position": [2, 0],
                            "kind": "signal_red",
                            "entrySide": "left",
                        },
                    ],
                },
                "objects": {
                    "format": "sparse",
                    "entries": [
                        {
                            "position": [car_x, 0],
                            "kind": "car",
                            "heading": "left" if reverse else "right",
                        }
                    ],
                },
            },
        },
        "state": {"avatar": {"enabled": False}, "variables": {}},
        "goals": [
            {"id": "arrive", "type": "all_cleared", "config": {"tag": "vehicle"}}
        ],
        "loseConditions": [],
    }


class TurnCycleGateTest(unittest.TestCase):
    def test_malformed_cycle_entries_are_ignored_instead_of_throwing(self):
        game = _game(cycle_config_overrides={"cycles": {"signal_red": 7}})
        engine = TurnEngine(game, _level())

        result = engine.execute_turn(
            "rotate_cell", {"position": [0, 1]}
        )

        self.assertTrue(result.accepted)
        self.assertEqual(
            engine.state.board.get_entity("markers", Pos(2, 0)).kind,
            "signal_red",
        )

    def test_declaring_signal_first_changes_light_before_routed_movement(self):
        engine = TurnEngine(_game(signal_first=True), _level())

        first = engine.execute_turn("rotate_cell", {"position": [0, 1]})
        self.assertTrue(first.accepted)
        self.assertEqual(
            engine.state.board.get_entity("markers", Pos(2, 0)).kind,
            "signal_yellow_to_green",
        )
        self.assertIsNotNone(
            engine.state.board.get_entity("objects", Pos(1, 0))
        )

        second = engine.execute_turn("rotate_cell", {"position": [0, 1]})
        self.assertTrue(second.is_won)
        self.assertEqual(
            engine.state.board.get_entity("markers", Pos(2, 0)).kind,
            "signal_green",
        )
        light_changed_at = next(
            index
            for index, event in enumerate(second.events)
            if event["type"] == "cell_transformed"
            and event.get("layer") == "markers"
        )
        vehicle_moved_at = next(
            index
            for index, event in enumerate(second.events)
            if event["type"] == "entity_path_moved"
        )
        self.assertLess(light_changed_at, vehicle_moved_at)

        self.assertTrue(engine.undo())
        self.assertEqual(
            engine.state.board.get_entity("markers", Pos(2, 0)).kind,
            "signal_yellow_to_green",
        )
        self.assertIsNotNone(
            engine.state.board.get_entity("objects", Pos(1, 0))
        )

    def test_current_phase_blocks_before_cycle_and_undo_restores_phase(self):
        engine = TurnEngine(_game(), _level())

        first = engine.execute_turn("rotate_cell", {"position": [0, 1]})
        self.assertTrue(first.accepted)
        self.assertIsNotNone(engine.state.board.get_entity("objects", Pos(1, 0)))
        self.assertEqual(
            engine.state.board.get_entity("markers", Pos(2, 0)).kind,
            "signal_yellow_to_green",
        )
        self.assertTrue(
            any(
                event["type"] == "routed_motion_blocked"
                and event["reason"] == "closed_gate"
                for event in first.events
            )
        )

        engine.execute_turn("rotate_cell", {"position": [0, 1]})
        self.assertIsNotNone(engine.state.board.get_entity("objects", Pos(1, 0)))
        self.assertEqual(
            engine.state.board.get_entity("markers", Pos(2, 0)).kind,
            "signal_green",
        )

        third = engine.execute_turn("rotate_cell", {"position": [0, 1]})
        self.assertTrue(third.is_won)
        self.assertEqual(
            engine.state.board.get_entity("markers", Pos(2, 0)).kind,
            "signal_yellow_to_red",
        )

        self.assertTrue(engine.undo())
        self.assertIsNotNone(engine.state.board.get_entity("objects", Pos(1, 0)))
        restored_signal = engine.state.board.get_entity("markers", Pos(2, 0))
        self.assertEqual(restored_signal.kind, "signal_green")
        self.assertEqual(restored_signal.param("entrySide"), "left")

    def test_rejected_action_does_not_advance_signal(self):
        engine = TurnEngine(_game(), _level())

        result = engine.execute_turn("rotate_cell", {"position": [0, 0]})

        self.assertFalse(result.accepted)
        self.assertEqual(
            engine.state.board.get_entity("markers", Pos(2, 0)).kind,
            "signal_red",
        )
        self.assertEqual(engine.state.turn_count, 0)

    def test_gate_controls_only_its_configured_entry_side(self):
        engine = TurnEngine(_game(), _level(reverse=True))

        result = engine.execute_turn("rotate_cell", {"position": [0, 1]})

        self.assertTrue(result.is_won)
        self.assertIsNone(engine.state.board.get_entity("objects", Pos(3, 0)))


if __name__ == "__main__":
    unittest.main()
