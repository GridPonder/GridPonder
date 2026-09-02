"""Focused tests for elastic rectangle inflation and collapse."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine


def _game(config: dict | None = None) -> GameDef:
    return GameDef.from_dict({
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
            {"id": "objects", "occupancy": "zero_or_one"},
            {"id": "markers", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "floor": {"layer": "ground", "tags": ["walkable"], "symbol": "."},
            "void": {"layer": "ground", "tags": [], "symbol": "#"},
            "wall": {"layer": "objects", "tags": ["solid"], "symbol": "W"},
            "crate": {"layer": "objects", "tags": ["solid", "pushable"], "symbol": "C"},
            "coin": {"layer": "objects", "tags": [], "symbol": "O"},
            "target_a": {"layer": "markers", "tags": [], "symbol": "A"},
            "target_b": {"layer": "markers", "tags": [], "symbol": "T"},
            "elastic_block": {"layer": "structures", "tags": ["solid"], "symbol": "B"},
        },
        "actions": [{
            "id": "move",
            "params": {"direction": {"type": "direction", "values": ["up", "down", "left", "right"]}},
        }],
        "systems": [{
            "id": "elastic",
            "type": "elastic_block",
            "config": {"objectKind": "elastic_block", **(config or {})},
        }],
        "rules": [],
        "defaults": {"avatar": {"enabled": False}},
    }, id="elastic_block_test")


def _level(
    cells: list[list[int]],
    *,
    size: list[int] | None = None,
    objects: list[dict] | None = None,
    markers: list[dict] | None = None,
) -> dict:
    return {
        "id": "test",
        "board": {
            "size": size or [4, 4],
            "layers": {
                "ground": {"format": "sparse", "entries": []},
                "objects": {"format": "sparse", "entries": objects or []},
                "markers": {"format": "sparse", "entries": markers or []},
            },
            "multiCellObjects": [{"id": "block", "kind": "elastic_block", "cells": cells}],
        },
        "state": {"variables": {}, "avatar": {"enabled": False}},
        "goals": [],
        "rules": [],
        "solution": {"goldPath": []},
    }


def _positions(engine: TurnEngine) -> set[Pos]:
    block = engine.state.board.get_multi_cell_object("block")
    assert block is not None
    return set(block.cells)


class ElasticBlockTest(unittest.TestCase):
    def test_empty_board_worked_example(self) -> None:
        engine = TurnEngine(_game(), _level([[0, 3]]))

        for direction in ["up", "right", "right", "up"]:
            self.assertTrue(engine.execute_turn("move", {"direction": direction}).accepted)

        self.assertEqual(_positions(engine), {Pos(3, 0)})

    def test_partial_blocking_stops_the_whole_face(self) -> None:
        engine = TurnEngine(
            _game(),
            _level(
                [[0, 0], [0, 1]],
                size=[4, 2],
                objects=[{"position": [2, 1], "kind": "wall"}],
            ),
        )

        result = engine.execute_turn("move", {"direction": "right"})

        self.assertTrue(result.accepted)
        self.assertEqual(_positions(engine), {Pos(0, 0), Pos(0, 1), Pos(1, 0), Pos(1, 1)})

    def test_crate_is_bulldozed_until_it_jams(self) -> None:
        engine = TurnEngine(
            _game(),
            _level(
                [[0, 0]],
                size=[5, 1],
                objects=[
                    {"position": [2, 0], "kind": "crate"},
                    {"position": [4, 0], "kind": "wall"},
                ],
            ),
        )

        result = engine.execute_turn("move", {"direction": "right"})

        self.assertTrue(result.accepted)
        self.assertEqual(_positions(engine), {Pos(0, 0), Pos(1, 0), Pos(2, 0)})
        self.assertEqual(engine.state.board.get_entity("objects", Pos(3, 0)).kind, "crate")
        self.assertEqual([event["type"] for event in result.events].count("object_pushed"), 1)

    def test_blocked_press_collapses_against_leading_edge(self) -> None:
        engine = TurnEngine(
            _game(),
            _level(
                [[0, 0], [1, 0], [2, 0]],
                size=[4, 1],
                objects=[{"position": [3, 0], "kind": "wall"}],
            ),
        )

        result = engine.execute_turn("move", {"direction": "right"})

        self.assertTrue(result.accepted)
        self.assertEqual(_positions(engine), {Pos(2, 0)})
        self.assertIn("elastic_block_collapsed", [event["type"] for event in result.events])

    def test_blocked_one_thick_press_is_rejected_transactionally(self) -> None:
        engine = TurnEngine(
            _game(),
            _level(
                [[2, 0]],
                size=[4, 1],
                objects=[{"position": [3, 0], "kind": "wall"}],
            ),
        )

        result = engine.execute_turn("move", {"direction": "right"})

        self.assertFalse(result.accepted)
        self.assertEqual(_positions(engine), {Pos(2, 0)})
        self.assertEqual(engine.state.action_count, 0)

    def test_crate_chain_jams_without_moving(self) -> None:
        engine = TurnEngine(
            _game(),
            _level(
                [[0, 0]],
                size=[4, 1],
                objects=[
                    {"position": [1, 0], "kind": "crate"},
                    {"position": [2, 0], "kind": "crate"},
                ],
            ),
        )

        result = engine.execute_turn("move", {"direction": "right"})

        self.assertFalse(result.accepted)
        self.assertEqual(_positions(engine), {Pos(0, 0)})
        self.assertEqual(engine.state.board.get_entity("objects", Pos(1, 0)).kind, "crate")
        self.assertEqual(engine.state.board.get_entity("objects", Pos(2, 0)).kind, "crate")

    def test_chain_push_moves_adjacent_crates_together(self) -> None:
        engine = TurnEngine(
            _game({"chainPush": True}),
            _level(
                [[0, 0]],
                size=[5, 1],
                objects=[
                    {"position": [1, 0], "kind": "crate"},
                    {"position": [2, 0], "kind": "crate"},
                ],
            ),
        )

        result = engine.execute_turn("move", {"direction": "right"})

        self.assertTrue(result.accepted)
        self.assertEqual(_positions(engine), {Pos(0, 0), Pos(1, 0), Pos(2, 0)})
        self.assertEqual(engine.state.board.get_entity("objects", Pos(3, 0)).kind, "crate")
        self.assertEqual(engine.state.board.get_entity("objects", Pos(4, 0)).kind, "crate")
        origins = {
            event["originPosition"]
            for event in result.events
            if event["type"] == "object_pushed"
        }
        self.assertEqual(origins, {Pos(1, 0), Pos(2, 0)})

    def test_push_does_not_overwrite_nonblocking_entity(self) -> None:
        engine = TurnEngine(
            _game(),
            _level(
                [[0, 0]],
                size=[4, 1],
                objects=[
                    {"position": [1, 0], "kind": "crate"},
                    {"position": [2, 0], "kind": "coin"},
                ],
            ),
        )

        result = engine.execute_turn("move", {"direction": "right"})

        self.assertFalse(result.accepted)
        self.assertEqual(engine.state.board.get_entity("objects", Pos(1, 0)).kind, "crate")
        self.assertEqual(engine.state.board.get_entity("objects", Pos(2, 0)).kind, "coin")

    def test_completed_target_transforms_only_after_full_exit(self) -> None:
        config = {
            "targets": [{"id": "a", "markerKind": "target_a", "onLeave": "wall"}],
        }
        engine = TurnEngine(
            _game(config),
            _level([[0, 3]], markers=[{"position": [3, 0], "kind": "target_a"}]),
        )
        for direction in ["up", "right", "right", "up"]:
            engine.execute_turn("move", {"direction": direction})

        self.assertEqual(engine.state.variables["completedTargetCount"], 1)
        self.assertIsNone(engine.state.board.get_entity("objects", Pos(3, 0)))

        engine.execute_turn("move", {"direction": "down"})
        self.assertIsNone(engine.state.board.get_entity("objects", Pos(3, 0)))
        result = engine.execute_turn("move", {"direction": "down"})

        self.assertEqual(engine.state.board.get_entity("objects", Pos(3, 0)).kind, "wall")
        self.assertIn("target_consumed", [event["type"] for event in result.events])
        self.assertEqual(engine.state.variables["completedTargetCount"], 1)

    def test_multiple_targets_require_exact_matches_and_can_create_void(self) -> None:
        config = {
            "targets": [
                {"id": "a", "markerKind": "target_a", "onLeave": "none"},
                {"id": "b", "markerKind": "target_b", "onLeave": "void"},
            ],
        }
        engine = TurnEngine(
            _game(config),
            _level(
                [[0, 0]],
                size=[4, 1],
                markers=[
                    {"position": [0, 0], "kind": "target_a"},
                    {"position": [3, 0], "kind": "target_b"},
                ],
            ),
        )

        engine.execute_turn("move", {"direction": "right"})
        self.assertEqual(engine.state.variables.get("completedTargetCount", 0), 0)
        engine.execute_turn("move", {"direction": "right"})
        self.assertEqual(engine.state.variables["completedTargetIds"], ["b"])
        engine.execute_turn("move", {"direction": "left"})
        engine.execute_turn("move", {"direction": "left"})

        self.assertEqual(engine.state.variables["completedTargetIds"], ["a", "b"])
        self.assertEqual(engine.state.variables["completedTargetCount"], 2)
        self.assertEqual(engine.state.board.get_entity("ground", Pos(3, 0)).kind, "void")


if __name__ == "__main__":
    unittest.main()
