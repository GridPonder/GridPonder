"""Tests for generic orthogonal line-of-sight detection."""
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
    *,
    visibility_config: dict | None = None,
    rules: list[dict] | None = None,
) -> GameDef:
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
                {"id": "objects", "occupancy": "zero_or_one"},
                {"id": "actors", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "floor": {
                    "layer": "ground",
                    "tags": ["walkable"],
                    "symbol": ".",
                },
                "observer": {
                    "layer": "structures",
                    "tags": ["observer", "sliding_block"],
                    "symbol": "O",
                },
                "blocker": {
                    "layer": "structures",
                    "tags": ["sliding_block"],
                    "symbol": "B",
                },
                "beacon": {
                    "layer": "objects",
                    "tags": ["visible_target"],
                    "symbol": "T",
                },
                "sensor": {
                    "layer": "actors",
                    "tags": ["sensor"],
                    "symbol": "S",
                },
                "wall": {
                    "layer": "objects",
                    "tags": ["opaque"],
                    "symbol": "#",
                },
                "gate_closed": {
                    "layer": "objects",
                    "tags": ["opaque"],
                    "symbol": "G",
                },
                "gate_open": {
                    "layer": "objects",
                    "tags": [],
                    "symbol": "g",
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
                        "validGroundTags": ["walkable"],
                        "blockingLayers": ["objects"],
                        "blockingTags": ["opaque"],
                    },
                },
                {
                    "id": "visibility",
                    "type": "line_of_sight",
                    "config": {
                        "triggerEvents": ["multi_cell_object_moved"],
                        "sourceTags": ["observer"],
                        "targetLayer": "objects",
                        "targetTags": ["visible_target"],
                        "blockingLayers": ["objects"],
                        "blockingTags": ["opaque"],
                        **(visibility_config or {}),
                    },
                },
            ],
            "rules": rules or [],
            "defaults": {
                "avatar": {"enabled": False},
                "maxCascadeDepth": 3,
            },
        },
        id="line_of_sight_test",
    )


def _level(
    *,
    objects: list[dict] | None = None,
    actors: list[dict] | None = None,
    extra_multi_cell_objects: list[dict] | None = None,
) -> dict:
    return {
        "id": "visibility",
        "board": {
            "size": [4, 4],
            "layers": {
                "ground": {"format": "sparse", "entries": []},
                "objects": {
                    "format": "sparse",
                    "entries": objects or [],
                },
                "actors": {
                    "format": "sparse",
                    "entries": actors or [],
                },
            },
            "multiCellObjects": [
                {
                    "id": "observer",
                    "kind": "observer",
                    "cells": [{"position": [0, 3]}],
                    "params": {"axis": "horizontal"},
                },
                *(extra_multi_cell_objects or []),
            ],
        },
        "state": {
            "variables": {"signalsDetected": 0},
            "avatar": {"enabled": False},
        },
        "goals": [],
        "rules": [],
        "solution": {"goldPath": []},
    }


class LineOfSightTest(unittest.TestCase):
    def test_detects_clear_orthogonal_sightline(self) -> None:
        engine = TurnEngine(
            _game(),
            _level(objects=[{"position": [1, 0], "kind": "beacon"}]),
        )

        result = engine.execute_turn(
            "move",
            {"position": [0, 3], "direction": "right"},
        )

        event = next(
            item
            for item in result.events
            if item["type"] == "line_of_sight_detected"
        )
        self.assertEqual(event["position"], Pos(1, 0))
        self.assertEqual(event["sourcePosition"], Pos(1, 3))
        self.assertEqual(event["sourceId"], "observer")
        self.assertEqual(event["sourceKind"], "observer")

    def test_multi_cell_objects_and_opaque_layers_block_sight(self) -> None:
        covered = TurnEngine(
            _game(),
            _level(
                objects=[{"position": [1, 0], "kind": "beacon"}],
                extra_multi_cell_objects=[
                    {
                        "id": "cover",
                        "kind": "blocker",
                        "cells": [{"position": [1, 0]}],
                        "params": {"axis": "vertical"},
                    }
                ],
            ),
        )
        covered_result = covered.execute_turn(
            "move",
            {"position": [0, 3], "direction": "right"},
        )
        self.assertFalse(
            any(
                item["type"] == "line_of_sight_detected"
                for item in covered_result.events
            )
        )

        opaque = TurnEngine(
            _game(),
            _level(
                objects=[
                    {"position": [1, 0], "kind": "beacon"},
                    {"position": [1, 2], "kind": "wall"},
                ]
            ),
        )
        opaque_result = opaque.execute_turn(
            "move",
            {"position": [0, 3], "direction": "right"},
        )
        self.assertFalse(
            any(
                item["type"] == "line_of_sight_detected"
                for item in opaque_result.events
            )
        )

    def test_multi_cell_object_blocking_can_be_disabled(self) -> None:
        engine = TurnEngine(
            _game(visibility_config={"multiCellObjectsBlock": False}),
            _level(
                objects=[{"position": [1, 0], "kind": "beacon"}],
                extra_multi_cell_objects=[{
                    "id": "cover",
                    "kind": "blocker",
                    "cells": [{"position": [1, 0]}],
                    "params": {"axis": "vertical"},
                }],
            ),
        )

        result = engine.execute_turn(
            "move",
            {"position": [0, 3], "direction": "right"},
        )

        self.assertTrue(any(
            item["type"] == "line_of_sight_detected"
            for item in result.events
        ))

    def test_missing_source_role_does_not_match_the_string_none(self) -> None:
        engine = TurnEngine(
            _game(visibility_config={"sourceRoles": ["None"]}),
            _level(objects=[{"position": [1, 0], "kind": "beacon"}]),
        )

        result = engine.execute_turn(
            "move",
            {"position": [0, 3], "direction": "right"},
        )

        self.assertFalse(any(
            item["type"] == "line_of_sight_detected"
            for item in result.events
        ))

    def test_layer_sources_unlimited_matches_and_trigger_filtering(self) -> None:
        visibility_config = {
            "sourceLayer": "actors",
            "sourceKinds": ["sensor"],
            "sourceTags": [],
            "maxMatches": 0,
        }
        objects = [
            {"position": [2, 1], "kind": "beacon"},
            {"position": [0, 0], "kind": "beacon"},
        ]
        actors = [{"position": [0, 1], "kind": "sensor"}]

        engine = TurnEngine(
            _game(visibility_config=visibility_config),
            _level(objects=objects, actors=actors),
        )
        result = engine.execute_turn(
            "move",
            {"position": [0, 3], "direction": "right"},
        )
        self.assertEqual(
            sum(
                item["type"] == "line_of_sight_detected"
                for item in result.events
            ),
            2,
        )

        filtered_engine = TurnEngine(
            _game(
                visibility_config={
                    **visibility_config,
                    "triggerEvents": ["variable_changed"],
                }
            ),
            _level(objects=objects, actors=actors),
        )
        filtered_result = filtered_engine.execute_turn(
            "move",
            {"position": [0, 3], "direction": "right"},
        )
        self.assertFalse(
            any(
                item["type"] == "line_of_sight_detected"
                for item in filtered_result.events
            )
        )

    def test_detection_events_compose_with_rules(self) -> None:
        rules = [
            {
                "id": "record_signal",
                "on": "line_of_sight_detected",
                "where": {"event": {"kind": "beacon"}},
                "then": [
                    {
                        "destroy": {
                            "position": "$event.position",
                            "layer": "objects",
                        }
                    },
                    {
                        "increment_variable": {
                            "name": "signalsDetected",
                            "amount": 1,
                        }
                    },
                ],
            },
            {
                "id": "open_gate",
                "on": "variable_changed",
                "where": {
                    "event": {
                        "param": "variable",
                        "equals": "signalsDetected",
                    }
                },
                "then": [
                    {
                        "transform": {
                            "position": [3, 0],
                            "layer": "objects",
                            "toKind": "gate_open",
                        }
                    }
                ],
            },
        ]
        engine = TurnEngine(
            _game(rules=rules),
            _level(
                objects=[
                    {"position": [1, 0], "kind": "beacon"},
                    {"position": [3, 0], "kind": "gate_closed"},
                ]
            ),
        )

        result = engine.execute_turn(
            "move",
            {"position": [0, 3], "direction": "right"},
        )

        self.assertTrue(result.accepted)
        self.assertEqual(engine.state.variables["signalsDetected"], 1)
        self.assertIsNone(
            engine.state.board.get_entity("objects", Pos(1, 0))
        )
        self.assertEqual(
            engine.state.board.get_entity("objects", Pos(3, 0)).kind,
            "gate_open",
        )


if __name__ == "__main__":
    unittest.main()
