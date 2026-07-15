"""Focused behavioural tests for the generic sliding_blocks system."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine


def _game(config_overrides: dict | None = None) -> GameDef:
    config_overrides = config_overrides or {}
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
                {"id": "objects", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "floor": {"layer": "ground", "tags": ["walkable"], "symbol": "."},
                "void": {"layer": "ground", "tags": [], "symbol": "#"},
                "exit_floor": {
                    "layer": "ground",
                    "tags": ["walkable", "exit"],
                    "symbol": "E",
                },
                "slider": {
                    "layer": "structures",
                    "tags": ["sliding_block"],
                    "symbol": "S",
                },
                "stopper": {"layer": "structures", "tags": [], "symbol": "X"},
                "key": {
                    "layer": "objects",
                    "tags": ["collectible", "key"],
                    "symbol": "K",
                },
                "gate_locked": {
                    "layer": "objects",
                    "tags": ["solid", "gate"],
                    "symbol": "L",
                },
                "gate_open": {"layer": "objects", "tags": [], "symbol": "O"},
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
                        "coverableTags": ["gate"],
                        "coverableBlockedRoles": ["escapee"],
                        "lineOfSightCollect": [
                            {
                                "roles": ["escapee"],
                                "layer": "objects",
                                "tags": ["key"],
                                "variable": "keysCollected",
                                "remove": True,
                            }
                        ],
                        "objectInteractions": [
                            {
                                "layer": "objects",
                                "scope": "board",
                                "targetKinds": ["gate_locked"],
                                "requiredVariable": "keysCollected",
                                "toKind": "gate_open",
                            }
                        ],
                        **config_overrides,
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
    keys_collected: int = 0,
    system_overrides: dict | None = None,
) -> dict:
    level = {
        "id": level_id,
        "board": board,
        "state": {
            "variables": {"keysCollected": keys_collected},
            "avatar": {"enabled": False},
        },
        "goals": [],
        "rules": [],
        "solution": {"goldPath": []},
    }
    if system_overrides is not None:
        level["systemOverrides"] = system_overrides
    return level


def _transaction_board() -> dict:
    return {
        "size": [3, 2],
        "layers": {
            "ground": {"format": "sparse", "entries": []},
            "objects": {
                "format": "sparse",
                "entries": [{"position": [1, 0], "kind": "gate_locked"}],
            },
        },
        "multiCellObjects": [
            {
                "id": "moving",
                "kind": "slider",
                "cells": [{"position": [0, 0]}, {"position": [0, 1]}],
                "params": {"axis": "horizontal"},
            },
            {
                "id": "collision",
                "kind": "stopper",
                "cells": [{"position": [1, 1]}],
                "params": {"axis": "fixed"},
            },
        ],
    }


def _coverable_board(role: str | None = None) -> dict:
    params = {"axis": "horizontal"}
    if role is not None:
        params["role"] = role
    return {
        "size": [3, 1],
        "layers": {
            "ground": {"format": "sparse", "entries": []},
            "objects": {
                "format": "sparse",
                "entries": [{"position": [1, 0], "kind": "gate_locked"}],
            },
        },
        "multiCellObjects": [
            {
                "id": "moving",
                "kind": "slider",
                "cells": [{"position": [0, 0]}],
                "params": params,
            }
        ],
    }


def _sightline_board() -> dict:
    return {
        "size": [4, 4],
        "layers": {
            "ground": {"format": "sparse", "entries": []},
            "objects": {
                "format": "sparse",
                "entries": [
                    {"position": [0, 0], "kind": "key"},
                    {"position": [3, 0], "kind": "gate_locked"},
                ],
            },
        },
        "multiCellObjects": [
            {
                "id": "collector",
                "kind": "slider",
                "cells": [{"position": [0, 3]}],
                "params": {"axis": "horizontal", "role": "escapee"},
            },
            {
                "id": "key_cover",
                "kind": "slider",
                "cells": [{"position": [0, 0]}, {"position": [0, 1]}],
                "params": {"axis": "horizontal"},
            },
            {
                "id": "setup",
                "kind": "slider",
                "cells": [{"position": [3, 3]}],
                "params": {"axis": "vertical"},
            },
        ],
    }


def _single_block_board(
    *,
    axis: str = "horizontal",
    role: str | None = None,
    start: list[int] | None = None,
    ground_entries: list[dict] | None = None,
    object_entries: list[dict] | None = None,
    size: list[int] | None = None,
) -> dict:
    params = {"axis": axis}
    if role is not None:
        params["role"] = role
    return {
        "size": size or [3, 2],
        "layers": {
            "ground": {"format": "sparse", "entries": ground_entries or []},
            "objects": {"format": "sparse", "entries": object_entries or []},
        },
        "multiCellObjects": [
            {
                "id": "moving",
                "kind": "slider",
                "cells": [{"position": start or [0, 0]}],
                "params": params,
            }
        ],
    }


class SlidingBlocksTest(unittest.TestCase):
    def test_state_key_includes_multi_cell_positions(self) -> None:
        engine = TurnEngine(_game(), _level("state_key", _coverable_board()))
        moved = engine.state.copy()
        moved.board.multi_cell_objects[0].cells = [Pos(1, 0)]

        self.assertNotEqual(engine.state.to_key(), moved.to_key())

    def _assert_veto_is_transactional(self, save_history: bool) -> None:
        engine = TurnEngine(
            _game(),
            _level("transaction_veto", _transaction_board(), keys_collected=1),
        )

        result = engine.execute_turn(
            "move",
            {"position": [0, 0], "direction": "right"},
            save_history=save_history,
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.events, [])
        gate = engine.state.board.get_entity("objects", Pos(1, 0))
        self.assertIsNotNone(gate)
        self.assertEqual(gate.kind, "gate_locked")
        self.assertEqual(
            engine.state.board.multi_cell_objects[0].cells,
            [Pos(0, 0), Pos(0, 1)],
        )
        self.assertEqual(engine.state.action_count, 0)
        self.assertEqual(engine.state.turn_count, 0)
        self.assertEqual(engine.undo_depth, 0)

    def test_veto_discards_mutations_with_history(self) -> None:
        self._assert_veto_is_transactional(save_history=True)

    def test_veto_discards_mutations_without_history(self) -> None:
        self._assert_veto_is_transactional(save_history=False)

    def test_ordinary_block_can_overlap_coverable_object(self) -> None:
        engine = TurnEngine(_game(), _level("coverable", _coverable_board()))

        result = engine.execute_turn(
            "move", {"position": [0, 0], "direction": "right"}
        )

        self.assertTrue(result.accepted)
        self.assertEqual(engine.state.board.multi_cell_objects[0].cells, [Pos(1, 0)])
        gate = engine.state.board.get_entity("objects", Pos(1, 0))
        self.assertIsNotNone(gate)
        self.assertEqual(gate.kind, "gate_locked")

    def test_configured_role_remains_blocked_by_coverable_object(self) -> None:
        engine = TurnEngine(
            _game(),
            _level("protected_role", _coverable_board(role="escapee")),
        )

        result = engine.execute_turn(
            "move", {"position": [0, 0], "direction": "right"}
        )

        self.assertFalse(result.accepted)
        self.assertEqual(engine.state.board.multi_cell_objects[0].cells, [Pos(0, 0)])

    def test_uncovering_triggers_sightline_and_board_interaction(self) -> None:
        engine = TurnEngine(_game(), _level("sightline", _sightline_board()))

        setup = engine.execute_turn(
            "move", {"position": [3, 3], "direction": "up"}
        )
        self.assertTrue(setup.accepted)
        self.assertEqual(engine.state.variables["keysCollected"], 0)
        self.assertEqual(
            engine.state.board.get_entity("objects", Pos(0, 0)).kind,
            "key",
        )

        uncover = engine.execute_turn(
            "move", {"position": [0, 1], "direction": "right"}
        )
        self.assertTrue(uncover.accepted)
        self.assertEqual(engine.state.variables["keysCollected"], 1)
        self.assertIsNone(engine.state.board.get_entity("objects", Pos(0, 0)))
        self.assertEqual(
            engine.state.board.get_entity("objects", Pos(3, 0)).kind,
            "gate_open",
        )
        event = next(
            event
            for event in uncover.events
            if event["type"] == "line_of_sight_collected"
        )
        self.assertEqual(event["collectorId"], "collector")
        self.assertEqual(event["sourcePosition"], Pos(0, 3))

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
                "move", {"position": [1, 0], "direction": "right"}
            ).accepted
        )
        self.assertTrue(
            vertical.execute_turn(
                "move", {"position": [1, 0], "direction": "down"}
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
                "move", {"position": [0, 0], "direction": "right"}
            ).accepted
        )

    def test_only_escapees_can_leave_through_tagged_exits(self) -> None:
        game = _game(
            {
                "lineOfSightCollect": [],
                "revealOnUncovered": [
                    {
                        "position": [1, 0],
                        "layer": "objects",
                        "kind": "key",
                        "revealedVariable": "exitRevealed",
                    }
                ],
            }
        )
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
        result = escapee.execute_turn(
            "move", {"position": [1, 0], "direction": "right"}
        )
        self.assertTrue(result.accepted)
        self.assertEqual(escapee.state.board.multi_cell_objects, [])
        self.assertEqual(escapee.state.variables["escapedCount"], 1)
        self.assertEqual(
            escapee.state.board.get_entity("objects", Pos(1, 0)).kind, "key"
        )
        self.assertTrue(escapee.state.variables["exitRevealed"])

        ordinary = TurnEngine(
            game,
            _level(
                "ordinary_exit",
                _single_block_board(
                    start=[1, 0], size=[2, 1], ground_entries=exit_ground
                ),
            ),
        )
        self.assertFalse(
            ordinary.execute_turn(
                "move", {"position": [1, 0], "direction": "right"}
            ).accepted
        )

    def test_uncover_and_enter_collection_are_independently_configurable(self) -> None:
        reveal_game = _game(
            {
                "lineOfSightCollect": [],
                "revealOnUncovered": [
                    {
                        "position": [0, 0],
                        "layer": "objects",
                        "kind": "key",
                        "revealedVariable": "keyRevealed",
                    }
                ],
            }
        )
        reveal = TurnEngine(
            reveal_game,
            _level("reveal", _single_block_board(size=[3, 1])),
        )
        self.assertTrue(
            reveal.execute_turn(
                "move", {"position": [0, 0], "direction": "right"}
            ).accepted
        )
        self.assertEqual(
            reveal.state.board.get_entity("objects", Pos(0, 0)).kind, "key"
        )
        self.assertTrue(reveal.state.variables["keyRevealed"])

        collect_game = _game(
            {
                "lineOfSightCollect": [],
                "collectOnEnter": [
                    {
                        "roles": ["escapee"],
                        "layer": "objects",
                        "tags": ["key"],
                        "variable": "keysCollected",
                    }
                ],
            }
        )
        collect = TurnEngine(
            collect_game,
            _level(
                "collect",
                _single_block_board(
                    role="escapee",
                    size=[3, 1],
                    object_entries=[{"position": [1, 0], "kind": "key"}],
                ),
            ),
        )
        self.assertTrue(
            collect.execute_turn(
                "move", {"position": [0, 0], "direction": "right"}
            ).accepted
        )
        self.assertIsNone(collect.state.board.get_entity("objects", Pos(1, 0)))
        self.assertEqual(collect.state.variables["keysCollected"], 1)

    def test_level_system_overrides_are_applied(self) -> None:
        game = _game({"validGroundTags": ["unreachable"]})
        engine = TurnEngine(
            game,
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
                "move", {"position": [0, 0], "direction": "right"}
            ).accepted
        )


if __name__ == "__main__":
    unittest.main()
