"""Focused tests for the gravity system and sliding_blocks pushable roles."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine


def _game_dict() -> dict:
    return {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
                {"id": "objects", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "floor": {"layer": "ground", "tags": ["walkable"], "symbol": "."},
                "zone": {
                    "layer": "ground",
                    "tags": ["walkable", "target"],
                    "symbol": "T",
                    "animations": {
                        "eat": {"frames": ["a.png", "b.png"], "duration": 400, "mode": "once"}
                    },
                },
                "zone_fed": {"layer": "ground", "tags": ["walkable"], "symbol": "F"},
                "box": {"layer": "structures", "tags": ["sliding_block"], "symbol": "G"},
                "block": {"layer": "structures", "tags": ["sliding_block"], "symbol": "S"},
            },
            "actions": [
                {
                    "id": "move",
                    "params": {
                        "position": {"type": "position"},
                        "direction": {
                            "type": "direction",
                            "values": ["up", "down", "left", "right"],
                        },
                    },
                }
            ],
            "systems": [
                {
                    "id": "sliding",
                    "type": "sliding_blocks",
                    "config": {
                        "pushableRoles": ["good", "bad"],
                        "pushDirections": ["left", "right"],
                    },
                },
                {
                    "id": "gravity",
                    "type": "gravity",
                    "config": {
                        "fallRoles": ["good", "bad"],
                        "groundTagVariables": [
                            {"role": "good", "groundTag": "target", "variable": "onTarget"}
                        ],
                    },
                },
            ],
            "rules": [],
            "defaults": {"avatar": {"enabled": False}, "maxCascadeDepth": 4},
    }


def _game() -> GameDef:
    return GameDef.from_dict(_game_dict(), id="gravity_test")


def _absorbing_game() -> GameDef:
    raw = _game_dict()
    for system in raw["systems"]:
        if system["type"] == "gravity":
            system["config"]["absorb"] = [
                {
                    "role": "good",
                    "groundTag": "target",
                    "toGroundKind": "zone_fed",
                    "animation": "eat",
                    "variable": "fed",
                }
            ]
    return GameDef.from_dict(raw, id="gravity_absorb_test")


def _pounce_game() -> GameDef:
    raw = _game_dict()
    raw["systems"].append(
        {
            "id": "pounce",
            "type": "pounce",
            "config": {
                "hunterRoles": ["bad"],
                "preyRoles": ["good"],
                "variable": "stolen",
            },
        }
    )
    return GameDef.from_dict(raw, id="pounce_test")


def _step_game(absorb: bool = False) -> GameDef:
    """Step-by-step falling with pounce looking before every step."""
    raw = _game_dict()
    raw["defaults"]["maxCascadeDepth"] = 12
    sliding, gravity = raw["systems"]
    gravity["config"]["stepsPerPass"] = 1
    if absorb:
        gravity["config"]["absorb"] = [
            {"role": "good", "groundTag": "target", "toGroundKind": "zone_fed", "variable": "fed"}
        ]
    pounce = {
        "id": "pounce",
        "type": "pounce",
        "config": {"hunterRoles": ["bad"], "preyRoles": ["good"], "variable": "stolen"},
    }
    raw["systems"] = [sliding, pounce, gravity]
    return GameDef.from_dict(raw, id="step_test")


def _blocked_game() -> GameDef:
    raw = _game_dict()
    raw["systems"][0]["config"]["blockedGroundTags"] = ["target"]
    return GameDef.from_dict(raw, id="blocked_ground_test")


def _box(obj_id: str, kind: str, cells: list[list[int]], role: str | None, axis: str):
    params = {"axis": axis}
    if role:
        params["role"] = role
    return {
        "id": obj_id,
        "kind": kind,
        "cells": [{"position": c} for c in cells],
        "params": params,
    }


def _engine(objects: list[dict], game: GameDef | None = None) -> TurnEngine:
    level = {
        "id": "gravity_level",
        "board": {
            "size": [5, 4],
            "layers": {
                "ground": {
                    "format": "sparse",
                    "entries": [{"position": [3, 3], "kind": "zone"}],
                },
                "objects": {"format": "sparse", "entries": []},
            },
            "multiCellObjects": objects,
        },
        "state": {"variables": {"onTarget": 0, "fed": 0, "stolen": 0}, "avatar": {"enabled": False}},
        "goals": [],
        "rules": [],
        "solution": {"goldPath": []},
    }
    return TurnEngine(game or _game(), level)


def _cells(engine: TurnEngine, obj_id: str) -> list[Pos]:
    return engine.state.board.get_multi_cell_object(obj_id).cells


def _ledge(cells: list[list[int]]) -> dict:
    return _box("ledge", "block", cells, None, "both")


def _pusher(cell: list[int]) -> dict:
    return _box("pusher", "block", [cell], None, "both")


class GravityTest(unittest.TestCase):
    def test_box_falls_at_load(self) -> None:
        engine = _engine([_box("g", "box", [[1, 0]], "good", "fixed")])
        self.assertEqual(_cells(engine, "g"), [Pos(1, 3)])

    def test_box_rests_on_a_block(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[1, 0]], "good", "fixed"),
                _ledge([[0, 2], [1, 2]]),
            ]
        )
        self.assertEqual(_cells(engine, "g"), [Pos(1, 1)])

    def test_lowering_a_block_lowers_the_box_with_it(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[1, 0]], "good", "fixed"),
                _ledge([[0, 2], [1, 2]]),
            ]
        )
        self.assertEqual(_cells(engine, "g"), [Pos(1, 1)])
        result = engine.execute_turn("move", {"position": [1, 2], "direction": "down"})
        self.assertTrue(result.accepted)
        self.assertEqual(_cells(engine, "g"), [Pos(1, 2)])

    def test_sliding_a_block_out_from_under_drops_the_box(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[1, 0]], "good", "fixed"),
                _ledge([[0, 2], [1, 2]]),
            ]
        )
        for _ in range(2):
            first = _cells(engine, "ledge")[0]
            result = engine.execute_turn(
                "move", {"position": [first.x, first.y], "direction": "right"}
            )
            self.assertTrue(result.accepted)
        self.assertEqual(_cells(engine, "g"), [Pos(1, 3)])

    def test_sideways_push_moves_then_drops_the_box(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[1, 1]], "good", "fixed"),
                _ledge([[0, 2], [1, 2], [2, 2]]),
                _pusher([0, 1]),
            ]
        )
        self.assertTrue(
            engine.execute_turn("move", {"position": [0, 1], "direction": "right"}).accepted
        )
        self.assertEqual(_cells(engine, "g"), [Pos(2, 1)])
        self.assertEqual(engine.state.variables["onTarget"], 0)

        self.assertTrue(
            engine.execute_turn("move", {"position": [1, 1], "direction": "right"}).accepted
        )
        self.assertEqual(_cells(engine, "pusher"), [Pos(2, 1)])
        self.assertEqual(_cells(engine, "g"), [Pos(3, 3)])
        self.assertEqual(engine.state.variables["onTarget"], 1)

    def test_block_cannot_move_vertically_into_a_box(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[1, 1]], "good", "fixed"),
                _ledge([[1, 2]]),
                _pusher([1, 0]),
            ]
        )
        result = engine.execute_turn("move", {"position": [1, 0], "direction": "down"})
        self.assertFalse(result.accepted)
        up = engine.execute_turn("move", {"position": [1, 2], "direction": "up"})
        self.assertFalse(up.accepted)

    def test_push_into_wall_is_refused(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[4, 1]], "good", "fixed"),
                _ledge([[4, 2]]),
                _pusher([3, 1]),
            ]
        )
        result = engine.execute_turn("move", {"position": [3, 1], "direction": "right"})
        self.assertFalse(result.accepted)
        self.assertEqual(_cells(engine, "g"), [Pos(4, 1)])

    def test_pushed_box_never_pushes_another_box(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[1, 1]], "good", "fixed"),
                _box("r", "box", [[2, 1]], "bad", "fixed"),
                _ledge([[0, 2], [1, 2], [2, 2]]),
                _pusher([0, 1]),
            ]
        )
        result = engine.execute_turn("move", {"position": [0, 1], "direction": "right"})
        self.assertFalse(result.accepted)

    def test_box_cannot_be_dragged_directly(self) -> None:
        engine = _engine([_box("g", "box", [[1, 0]], "good", "fixed")])
        result = engine.execute_turn("move", {"position": [1, 3], "direction": "left"})
        self.assertFalse(result.accepted)

    def test_l_shaped_block_pushes_a_box_in_its_row(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[2, 2]], "good", "fixed"),
                _ledge([[0, 3], [1, 3], [2, 3]]),
                _box("ell", "block", [[0, 1], [0, 2], [1, 2]], None, "both"),
            ]
        )
        # Ell rests where authored (blocks do not fall); its (1,2) cell is
        # adjacent to the box at (2,2) and pushes it to (3,2), which then falls.
        result = engine.execute_turn("move", {"position": [0, 2], "direction": "right"})
        self.assertTrue(result.accepted)
        self.assertEqual(_cells(engine, "g"), [Pos(3, 3)])
        self.assertEqual(engine.state.variables["onTarget"], 1)

    def test_absorb_consumes_the_box_and_changes_the_ground(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[1, 1]], "good", "fixed"),
                _ledge([[0, 2], [1, 2], [2, 2]]),
                _pusher([0, 1]),
            ],
            _absorbing_game(),
        )
        engine.execute_turn("move", {"position": [0, 1], "direction": "right"})
        result = engine.execute_turn("move", {"position": [1, 1], "direction": "right"})

        self.assertTrue(result.accepted)
        self.assertIsNone(engine.state.board.get_multi_cell_object("g"))
        self.assertEqual(engine.state.board.get_entity("ground", Pos(3, 3)).kind, "zone_fed")
        self.assertEqual(engine.state.variables["fed"], 1)
        types = [e["type"] for e in result.events]
        self.assertIn("multi_cell_object_absorbed", types)
        removed = [e for e in result.events if e["type"] == "object_removed"]
        self.assertEqual(
            [(e["kind"], e["animation"]) for e in removed], [("zone", "eat")]
        )

    def test_absorb_is_off_without_config(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[1, 1]], "good", "fixed"),
                _ledge([[0, 2], [1, 2], [2, 2]]),
                _pusher([0, 1]),
            ]
        )
        engine.execute_turn("move", {"position": [0, 1], "direction": "right"})
        engine.execute_turn("move", {"position": [1, 1], "direction": "right"})
        self.assertIsNotNone(engine.state.board.get_multi_cell_object("g"))


class PounceTest(unittest.TestCase):
    def _trigger(self, engine: TurnEngine) -> None:
        # Any accepted block move emits multi_cell_object_moved.
        result = engine.execute_turn("move", {"position": [0, 0], "direction": "right"})
        self.assertTrue(result.accepted)

    def test_hunter_runs_down_a_clear_row_and_eats_the_box(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[1, 3]], "good", "fixed"),
                _box("r", "box", [[4, 3]], "bad", "fixed"),
                _pusher([0, 0]),
            ],
            _pounce_game(),
        )
        self._trigger(engine)
        self.assertIsNone(engine.state.board.get_multi_cell_object("g"))
        self.assertEqual(_cells(engine, "r"), [Pos(1, 3)])
        self.assertEqual(engine.state.variables["stolen"], 1)

    def test_a_block_in_the_way_stops_the_hunter(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[1, 3]], "good", "fixed"),
                _box("r", "box", [[4, 3]], "bad", "fixed"),
                _box("wall", "block", [[2, 3]], None, "both"),
                _pusher([0, 0]),
            ],
            _pounce_game(),
        )
        self._trigger(engine)
        self.assertIsNotNone(engine.state.board.get_multi_cell_object("g"))
        self.assertEqual(engine.state.variables["stolen"], 0)

    def test_moving_the_blocker_away_opens_the_line(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[1, 3]], "good", "fixed"),
                _box("r", "box", [[4, 3]], "bad", "fixed"),
                _box("wall", "block", [[2, 3]], None, "both"),
            ],
            _pounce_game(),
        )
        result = engine.execute_turn("move", {"position": [2, 3], "direction": "up"})
        self.assertTrue(result.accepted)
        self.assertIsNone(engine.state.board.get_multi_cell_object("g"))
        self.assertEqual(engine.state.variables["stolen"], 1)
        self.assertIn("multi_cell_object_captured", [e["type"] for e in result.events])

    def test_hunter_to_the_left_also_pounces(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[3, 3]], "good", "fixed"),
                _box("r", "box", [[0, 3]], "bad", "fixed"),
                _pusher([0, 0]),
            ],
            _pounce_game(),
        )
        engine.execute_turn("move", {"position": [0, 0], "direction": "right"})
        self.assertEqual(_cells(engine, "r"), [Pos(3, 3)])

    def test_a_different_row_is_safe(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[1, 3]], "good", "fixed"),
                _box("r", "box", [[4, 1]], "bad", "fixed"),
                _ledge([[4, 2]]),
                _pusher([0, 0]),
            ],
            _pounce_game(),
        )
        self._trigger(engine)
        self.assertEqual(engine.state.variables["stolen"], 0)

    def test_the_nearest_prey_is_eaten_first(self) -> None:
        engine = _engine(
            [
                _box("near", "box", [[2, 3]], "good", "fixed"),
                _box("far", "box", [[0, 3]], "good", "fixed"),
                _box("r", "box", [[4, 3]], "bad", "fixed"),
                _pusher([0, 0]),
            ],
            _pounce_game(),
        )
        self._trigger(engine)
        # near eaten at x=2; then the hunter (now at x=2) sees far at x=0
        self.assertEqual(engine.state.variables["stolen"], 2)
        self.assertEqual(_cells(engine, "r"), [Pos(0, 3)])


class StepFallTest(unittest.TestCase):
    def _drop_past_hunter(self, game: GameDef, wall: bool) -> TurnEngine:
        objects = [
            _box("g", "box", [[1, 0]], "good", "fixed"),
            _box("s", "block", [[1, 1]], None, "both"),
            _box("r", "box", [[4, 2]], "bad", "fixed"),
            _box("post", "block", [[4, 3]], None, "both"),
        ]
        if wall:
            objects.append(_box("wall", "block", [[3, 2]], None, "both"))
        engine = _engine(objects, game)
        # Slide the support out from under the cheese; it then falls past row 2.
        result = engine.execute_turn("move", {"position": [1, 1], "direction": "right"})
        self.assertTrue(result.accepted)
        return engine

    def test_full_settle_only_looks_at_the_landing_row(self) -> None:
        engine = self._drop_past_hunter(_pounce_game(), wall=False)
        self.assertEqual(_cells(engine, "g"), [Pos(1, 3)])
        self.assertEqual(engine.state.variables["stolen"], 0)

    def test_step_mode_catches_the_cheese_in_transit(self) -> None:
        engine = self._drop_past_hunter(_step_game(), wall=False)
        self.assertIsNone(engine.state.board.get_multi_cell_object("g"))
        self.assertEqual(engine.state.variables["stolen"], 1)
        self.assertEqual(_cells(engine, "r")[0].y, 3)  # ran to row 2, then fell

    def test_a_block_in_the_row_lets_the_cheese_fall_safely(self) -> None:
        engine = self._drop_past_hunter(_step_game(), wall=True)
        self.assertEqual(_cells(engine, "g"), [Pos(1, 3)])
        self.assertEqual(engine.state.variables["stolen"], 0)

    def test_step_mode_still_absorbs_once_at_rest(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[3, 0]], "good", "fixed"),
                _box("s", "block", [[3, 1]], None, "both"),
            ],
            _step_game(absorb=True),
        )
        result = engine.execute_turn("move", {"position": [3, 1], "direction": "left"})
        self.assertTrue(result.accepted)
        self.assertIsNone(engine.state.board.get_multi_cell_object("g"))
        self.assertEqual(engine.state.variables["fed"], 1)
        self.assertEqual(engine.state.board.get_entity("ground", Pos(3, 3)).kind, "zone_fed")
        # Falling is reported one cell per pass.
        moves = [e for e in result.events if e["type"] == "multi_cell_object_moved" and e["id"] == "g"]
        self.assertEqual(len(moves), 3)
        self.assertTrue(all(abs(m["toCells"][0].y - m["fromCells"][0].y) == 1 for m in moves))


class BlockedGroundTest(unittest.TestCase):
    def test_a_block_cannot_enter_the_target_tile(self) -> None:
        engine = _engine([_box("blk", "block", [[2, 3]], None, "both")], _blocked_game())
        result = engine.execute_turn("move", {"position": [2, 3], "direction": "right"})
        self.assertFalse(result.accepted)
        self.assertEqual(_cells(engine, "blk"), [Pos(2, 3)])

    def test_the_default_still_lets_blocks_cover_it(self) -> None:
        engine = _engine([_box("blk", "block", [[2, 3]], None, "both")])
        result = engine.execute_turn("move", {"position": [2, 3], "direction": "right"})
        self.assertTrue(result.accepted)

    def test_a_pushed_box_may_still_be_pushed_onto_the_tile(self) -> None:
        engine = _engine(
            [
                _box("g", "box", [[2, 3]], "good", "fixed"),
                _box("pusher", "block", [[1, 3]], None, "both"),
            ],
            _blocked_game(),
        )
        result = engine.execute_turn("move", {"position": [1, 3], "direction": "right"})
        self.assertTrue(result.accepted)
        self.assertEqual(_cells(engine, "g"), [Pos(3, 3)])
        self.assertEqual(engine.state.variables["onTarget"], 1)
        # The pusher stops short: it cannot follow onto the tile.
        again = engine.execute_turn("move", {"position": [2, 3], "direction": "right"})
        self.assertFalse(again.accepted)


if __name__ == "__main__":
    unittest.main()
