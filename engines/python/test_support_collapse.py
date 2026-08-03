"""Tests for support_collapse — connectivity-to-root severance with rigid fall."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine


def _game(*, collapse_config: dict | None = None) -> GameDef:
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "void"},
            ],
            "entityKinds": {
                "void": {"layer": "ground", "tags": [], "symbol": " "},
                "anchor": {
                    "layer": "ground",
                    "tags": ["solid", "walkable", "support_root"],
                    "symbol": "A",
                },
                "hull": {
                    "layer": "ground",
                    "tags": ["solid", "walkable", "supported", "severable"],
                    "symbol": "H",
                },
                "pod": {
                    "layer": "ground",
                    "tags": ["solid", "walkable", "supported", "severable", "cargo"],
                    "symbol": "P",
                },
                "wreck": {"layer": "ground", "tags": ["solid"], "symbol": "w"},
                "pod_settled": {
                    "layer": "ground",
                    "tags": ["solid", "cargo"],
                    "symbol": "p",
                },
                "deck": {"layer": "ground", "tags": ["solid"], "symbol": "="},
            },
            "actions": [
                {
                    "id": "cut",
                    "params": {
                        "direction": {
                            "type": "direction",
                            "values": ["up", "down", "left", "right"],
                        }
                    },
                },
            ],
            "systems": [
                {
                    "id": "collapse",
                    "type": "support_collapse",
                    "config": {
                        "layer": "ground",
                        "severAction": "cut",
                        "severableTags": ["severable"],
                        "rootTags": ["support_root"],
                        "memberTags": ["supported"],
                        "restLayers": ["ground"],
                        "restTags": ["solid"],
                        "settleTransform": {"hull": "wreck", "pod": "pod_settled"},
                        "carryAvatar": True,
                        "avatarFellVariable": "wrecked",
                        **(collapse_config or {}),
                    },
                },
            ],
            "defaults": {"maxCascadeDepth": 3},
        },
        id="support_collapse_test",
    )


def _level(*, entries: list[dict], avatar: list[int]) -> dict:
    return {
        "id": "collapse_test",
        "board": {
            "size": [5, 6],
            "layers": {"ground": {"format": "sparse", "entries": entries}},
        },
        "state": {
            "variables": {"wrecked": 0},
            "avatar": {"enabled": True, "position": avatar},
        },
        "goals": [],
        "rules": [],
        "solution": {"goldPath": []},
    }


_DECK = [
    {"position": [0, 5], "kind": "deck"},
    {"position": [1, 5], "kind": "deck"},
    {"position": [2, 5], "kind": "deck"},
    {"position": [3, 5], "kind": "deck"},
    {"position": [4, 5], "kind": "deck"},
]

# Board used by most tests (x right, y down), 5 wide x 6 tall:
#   y=0:  A A . . .        anchor bar
#   y=1:  . H . . .        hull hanging under the right anchor cell
#   y=2:  . P . . .        pod under that hull
#   y=5:  = = = = =        deck
_HANGING = [
    {"position": [0, 0], "kind": "anchor"},
    {"position": [1, 0], "kind": "anchor"},
    {"position": [1, 1], "kind": "hull"},
    {"position": [1, 2], "kind": "pod"},
] + _DECK

# An L: hull(1,1) hull(1,2) hull(2,2) hanging from anchor(1,0).
_L_SHAPE = [
    {"position": [1, 0], "kind": "anchor"},
    {"position": [1, 1], "kind": "hull"},
    {"position": [1, 2], "kind": "hull"},
    {"position": [2, 2], "kind": "hull"},
] + _DECK

_HANGING_WITH_DEBRIS = _HANGING + [{"position": [1, 4], "kind": "wreck"}]

# Two anchors both holding the same hull run.
_TWO_ANCHORS = [
    {"position": [0, 0], "kind": "anchor"},
    {"position": [2, 0], "kind": "anchor"},
    {"position": [0, 1], "kind": "hull"},
    {"position": [1, 1], "kind": "hull"},
    {"position": [2, 1], "kind": "hull"},
] + _DECK

# No deck under column 3 — an orphan there falls out of the world.
_NO_DECK = [
    {"position": [3, 0], "kind": "anchor"},
    {"position": [3, 1], "kind": "hull"},
    {"position": [3, 2], "kind": "pod"},
]


class SupportCollapseTest(unittest.TestCase):
    def test_severing_the_keystone_drops_the_limb_rigidly(self):
        game = _game()
        engine = TurnEngine(game, _level(entries=_HANGING, avatar=[1, 0]))

        result = engine.execute_turn("cut", {"direction": "down"})

        board = engine.state.board
        self.assertEqual(board.get_entity("ground", Pos(1, 1)).kind, "void")
        self.assertEqual(board.get_entity("ground", Pos(1, 2)).kind, "void")
        self.assertEqual(board.get_entity("ground", Pos(1, 4)).kind, "pod_settled")
        types = [e["type"] for e in result.events]
        self.assertIn("cell_cleared", types)
        self.assertIn("object_settled", types)

    def test_rigid_component_keeps_its_shape(self):
        game = _game()
        engine = TurnEngine(game, _level(entries=_L_SHAPE, avatar=[1, 0]))

        engine.execute_turn("cut", {"direction": "down"})

        board = engine.state.board
        self.assertEqual(board.get_entity("ground", Pos(1, 4)).kind, "wreck")
        self.assertEqual(board.get_entity("ground", Pos(2, 4)).kind, "wreck")
        self.assertEqual(board.get_entity("ground", Pos(1, 2)).kind, "void")

    def test_component_rests_on_previously_landed_debris(self):
        game = _game()
        engine = TurnEngine(game, _level(entries=_HANGING_WITH_DEBRIS, avatar=[1, 0]))

        engine.execute_turn("cut", {"direction": "down"})

        board = engine.state.board
        self.assertEqual(board.get_entity("ground", Pos(1, 3)).kind, "pod_settled")

    def test_cells_still_connected_to_a_root_do_not_fall(self):
        game = _game()
        engine = TurnEngine(game, _level(entries=_TWO_ANCHORS, avatar=[0, 0]))

        engine.execute_turn("cut", {"direction": "down"})

        board = engine.state.board
        self.assertEqual(board.get_entity("ground", Pos(0, 1)).kind, "void")
        self.assertEqual(board.get_entity("ground", Pos(1, 1)).kind, "hull")
        self.assertEqual(board.get_entity("ground", Pos(2, 1)).kind, "hull")

    def test_avatar_rides_its_own_component_down_and_sets_the_variable(self):
        game = _game()
        engine = TurnEngine(game, _level(entries=_HANGING, avatar=[1, 2]))

        engine.execute_turn("cut", {"direction": "up"})

        self.assertEqual(engine.state.variables["wrecked"], 1)
        self.assertEqual(engine.state.avatar.position, Pos(1, 4))

    def test_component_falling_off_the_board_is_destroyed(self):
        game = _game()
        engine = TurnEngine(game, _level(entries=_NO_DECK, avatar=[3, 0]))

        engine.execute_turn("cut", {"direction": "down"})

        board = engine.state.board
        for y in range(6):
            self.assertEqual(
                board.get_entity("ground", Pos(3, y)).kind,
                "anchor" if y == 0 else "void",
            )

    def test_cutting_a_non_severable_cell_is_vetoed(self):
        game = _game()
        engine = TurnEngine(game, _level(entries=_HANGING, avatar=[0, 0]))

        result = engine.execute_turn("cut", {"direction": "right"})

        # A vetoed action is rejected outright — the turn does not count as a move.
        self.assertFalse(result.accepted)
        self.assertEqual(
            engine.state.board.get_entity("ground", Pos(1, 0)).kind, "anchor"
        )

    def test_cutting_empty_air_is_vetoed(self):
        game = _game()
        engine = TurnEngine(game, _level(entries=_HANGING, avatar=[0, 0]))

        result = engine.execute_turn("cut", {"direction": "down"})

        self.assertFalse(result.accepted)
        # The hull below the neighbouring anchor is untouched.
        self.assertEqual(
            engine.state.board.get_entity("ground", Pos(1, 1)).kind, "hull"
        )


if __name__ == "__main__":
    unittest.main()
