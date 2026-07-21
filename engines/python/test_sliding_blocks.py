"""Focused tests for direct multi-cell-object movement."""
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
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
                {"id": "terrain", "occupancy": "zero_or_one"},
                {"id": "objects", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "floor": {
                    "layer": "ground",
                    "tags": ["walkable"],
                    "symbol": ".",
                },
                "void": {"layer": "ground", "tags": [], "symbol": "#"},
                "exit_floor": {
                    "layer": "ground",
                    "tags": ["walkable", "exit"],
                    "symbol": "E",
                },
                "terrain_floor": {
                    "layer": "terrain",
                    "tags": ["walkable"],
                    "symbol": ",",
                },
                "terrain_exit": {
                    "layer": "terrain",
                    "tags": ["walkable", "exit"],
                    "symbol": "Q",
                },
                "slider": {
                    "layer": "structures",
                    "tags": ["sliding_block"],
                    "symbol": "S",
                },
                "fixed_piece": {
                    "layer": "structures",
                    "tags": [],
                    "symbol": "X",
                },
                "coverable_barrier": {
                    "layer": "objects",
                    "tags": ["solid", "coverable"],
                    "symbol": "C",
                },
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
                        "moveAction": "move",
                        "validGroundTags": ["walkable"],
                        "blockingLayers": ["objects"],
                        "blockingTags": ["solid"],
                        "coverableTags": ["coverable"],
                        "coverableBlockedRoles": ["protected"],
                        **(config or {}),
                    },
                }
            ],
            "rules": [],
            "defaults": {"avatar": {"enabled": False}},
        },
        id="sliding_blocks_test",
    )


def _level(
    level_id: str,
    board: dict,
    system_overrides: dict | None = None,
) -> dict:
    level = {
        "id": level_id,
        "board": board,
        "state": {
            "variables": {"escapedCount": 0},
            "avatar": {"enabled": False},
        },
        "goals": [],
        "rules": [],
        "solution": {"goldPath": []},
    }
    if system_overrides is not None:
        level["systemOverrides"] = system_overrides
    return level


def _single_block_board(
    *,
    axis: str = "horizontal",
    role: str | None = None,
    start: list[int] | None = None,
    size: list[int] | None = None,
    ground_entries: list[dict] | None = None,
    terrain_entries: list[dict] | None = None,
    object_entries: list[dict] | None = None,
    extra_blocks: list[dict] | None = None,
) -> dict:
    params = {"axis": axis}
    if role is not None:
        params["role"] = role
    return {
        "size": size or [3, 2],
        "layers": {
            "ground": {"format": "sparse", "entries": ground_entries or []},
            "terrain": {"format": "sparse", "entries": terrain_entries or []},
            "objects": {"format": "sparse", "entries": object_entries or []},
        },
        "multiCellObjects": [
            {
                "id": "moving",
                "kind": "slider",
                "cells": [{"position": start or [0, 0]}],
                "params": params,
            },
            *(extra_blocks or []),
        ],
    }


class SlidingBlocksTest(unittest.TestCase):
    def test_state_key_includes_multi_cell_positions(self) -> None:
        engine = TurnEngine(_game(), _level("state_key", _single_block_board()))
        moved = engine.state.copy()
        moved.board.multi_cell_objects[0].cells = [Pos(1, 0)]

        self.assertNotEqual(engine.state.to_key(), moved.to_key())

    def _assert_veto_is_transactional(self, save_history: bool) -> None:
        engine = TurnEngine(
            _game(),
            _level(
                "transactional_veto",
                _single_block_board(
                    extra_blocks=[
                        {
                            "id": "fixed",
                            "kind": "fixed_piece",
                            "cells": [{"position": [1, 0]}],
                            "params": {"axis": "fixed"},
                        }
                    ]
                ),
            ),
        )

        result = engine.execute_turn(
            "move",
            {"position": [0, 0], "direction": "right"},
            save_history=save_history,
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.events, [])
        self.assertEqual(
            engine.state.board.multi_cell_objects[0].cells,
            [Pos(0, 0)],
        )
        self.assertEqual(engine.state.action_count, 0)
        self.assertEqual(engine.state.turn_count, 0)
        self.assertEqual(engine.undo_depth, 0)

    def test_veto_discards_mutations_with_history(self) -> None:
        self._assert_veto_is_transactional(save_history=True)

    def test_veto_discards_mutations_without_history(self) -> None:
        self._assert_veto_is_transactional(save_history=False)

    def test_successful_move_translates_the_block(self) -> None:
        engine = TurnEngine(
            _game(),
            _level("translate", _single_block_board()),
        )

        result = engine.execute_turn(
            "move",
            {"position": [0, 0], "direction": "right"},
        )

        self.assertTrue(result.accepted)
        self.assertEqual(
            engine.state.board.multi_cell_objects[0].cells,
            [Pos(1, 0)],
        )

    def test_coverable_objects_can_block_selected_roles_only(self) -> None:
        object_entries = [
            {"position": [1, 0], "kind": "coverable_barrier"}
        ]
        ordinary = TurnEngine(
            _game(),
            _level(
                "ordinary_cover",
                _single_block_board(object_entries=object_entries),
            ),
        )
        self.assertTrue(
            ordinary.execute_turn(
                "move",
                {"position": [0, 0], "direction": "right"},
            ).accepted
        )

        protected = TurnEngine(
            _game(),
            _level(
                "protected_cover",
                _single_block_board(
                    role="protected",
                    object_entries=object_entries,
                ),
            ),
        )
        self.assertFalse(
            protected.execute_turn(
                "move",
                {"position": [0, 0], "direction": "right"},
            ).accepted
        )

    def test_axis_restrictions_and_valid_ground_are_enforced(self) -> None:
        vertical = TurnEngine(
            _game(),
            _level(
                "vertical_axis",
                _single_block_board(axis="vertical", start=[1, 0]),
            ),
        )
        self.assertFalse(
            vertical.execute_turn(
                "move",
                {"position": [1, 0], "direction": "right"},
            ).accepted
        )
        self.assertTrue(
            vertical.execute_turn(
                "move",
                {"position": [1, 0], "direction": "down"},
            ).accepted
        )

        void_blocked = TurnEngine(
            _game(),
            _level(
                "void_ground",
                _single_block_board(
                    ground_entries=[{"position": [1, 0], "kind": "void"}]
                ),
            ),
        )
        self.assertFalse(
            void_blocked.execute_turn(
                "move",
                {"position": [0, 0], "direction": "right"},
            ).accepted
        )

    def test_both_axis_blocks_reject_diagonal_and_unknown_directions(self) -> None:
        for direction in ("up_right", "sideways"):
            engine = TurnEngine(
                _game(),
                _level(
                    f"invalid_direction_{direction}",
                    _single_block_board(axis="both"),
                ),
            )

            result = engine.execute_turn(
                "move",
                {"position": [0, 0], "direction": direction},
            )

            self.assertFalse(result.accepted)
            self.assertEqual(
                engine.state.board.multi_cell_objects[0].cells,
                [Pos(0, 0)],
            )

    def test_only_configured_roles_can_leave_through_exit_cells(self) -> None:
        game = _game({"escapeRoles": ["escapee"]})
        exit_ground = [{"position": [1, 0], "kind": "exit_floor"}]
        escapee = TurnEngine(
            game,
            _level(
                "escapee_exit",
                _single_block_board(
                    role="escapee",
                    start=[1, 0],
                    size=[2, 1],
                    ground_entries=exit_ground,
                ),
            ),
        )
        self.assertTrue(
            escapee.execute_turn(
                "move",
                {"position": [1, 0], "direction": "right"},
            ).accepted
        )
        self.assertEqual(escapee.state.board.multi_cell_objects, [])
        self.assertEqual(escapee.state.variables["escapedCount"], 1)

        ordinary = TurnEngine(
            game,
            _level(
                "ordinary_exit",
                _single_block_board(
                    start=[1, 0],
                    size=[2, 1],
                    ground_entries=exit_ground,
                ),
            ),
        )
        self.assertFalse(
            ordinary.execute_turn(
                "move",
                {"position": [1, 0], "direction": "right"},
            ).accepted
        )

        missing_role = TurnEngine(
            _game({"escapeRoles": ["None"]}),
            _level(
                "missing_role_exit",
                _single_block_board(
                    start=[1, 0],
                    size=[2, 1],
                    ground_entries=exit_ground,
                ),
            ),
        )
        self.assertFalse(
            missing_role.execute_turn(
                "move",
                {"position": [1, 0], "direction": "right"},
            ).accepted
        )

    def test_custom_ground_layer_controls_movement_and_escape(self) -> None:
        engine = TurnEngine(
            _game({
                "groundLayer": "terrain",
                "escapeRoles": ["escapee"],
            }),
            _level(
                "custom_ground_layer",
                _single_block_board(
                    role="escapee",
                    size=[2, 1],
                    terrain_entries=[
                        {"position": [0, 0], "kind": "terrain_floor"},
                        {"position": [1, 0], "kind": "terrain_exit"},
                    ],
                ),
            ),
        )

        self.assertTrue(engine.execute_turn(
            "move",
            {"position": [0, 0], "direction": "right"},
        ).accepted)
        self.assertTrue(engine.execute_turn(
            "move",
            {"position": [1, 0], "direction": "right"},
        ).accepted)
        self.assertEqual(engine.state.board.multi_cell_objects, [])

    def test_level_system_overrides_replace_game_constraints(self) -> None:
        engine = TurnEngine(
            _game({"validGroundTags": ["unreachable"]}),
            _level(
                "override",
                _single_block_board(),
                system_overrides={
                    "sliding": {"validGroundTags": ["walkable"]}
                },
            ),
        )
        self.assertTrue(
            engine.execute_turn(
                "move",
                {"position": [0, 0], "direction": "right"},
            ).accepted
        )


if __name__ == "__main__":
    unittest.main()
