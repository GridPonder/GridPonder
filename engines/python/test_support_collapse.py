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


# Ramp kinds for the deflect tests. Solid like the deck, so they stop a
# component; tagged so `deflect` can turn that stop into a sideways step.
_RAMP_KINDS = {
    "ramp_right": {"layer": "ground", "tags": ["solid", "slope_right"], "symbol": "/"},
    "ramp_left": {"layer": "ground", "tags": ["solid", "slope_left"], "symbol": "\\"},
}


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
                **_RAMP_KINDS,
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

# Two orphans in one column. Cutting (1,1) orphans the hull at (1,2) AND the
# pod at (1,4), which has no path to a root of its own. The pod is blocked by
# the deck immediately; the hull must come to rest on top of it, not through it.
_STACKED_ORPHANS = [
    {"position": [1, 0], "kind": "anchor"},
    {"position": [1, 1], "kind": "hull"},
    {"position": [1, 2], "kind": "hull"},
    {"position": [1, 4], "kind": "pod"},
] + _DECK

_DEFLECT = {"deflect": {"slope_left": "left", "slope_right": "right"}}

#   y=0:  . A . . .
#   y=1:  . H . . .
#   y=2:  . P . . .
#   y=4:  . / . . .   ramp_right under column 1
#   y=5:  = = = = =
_ONE_RAMP = [
    {"position": [1, 0], "kind": "anchor"},
    {"position": [1, 1], "kind": "hull"},
    {"position": [1, 2], "kind": "pod"},
    {"position": [1, 4], "kind": "ramp_right"},
] + _DECK

# Same ramp, but column 2 already holds debris at the row the pod would slide
# into, so the sideways step is refused and the pod clogs the ramp.
_CLOGGED_RAMP = _ONE_RAMP + [{"position": [2, 3], "kind": "wreck"}]

# A 2-wide component whose left cell meets a ramp and whose right cell meets
# flat debris. The blockers disagree, so it rests instead of sliding.
#   y=2:  . H H . .
#   y=4:  . / w . .
_STRADDLE = [
    {"position": [1, 0], "kind": "anchor"},
    {"position": [1, 1], "kind": "hull"},
    {"position": [1, 2], "kind": "hull"},
    {"position": [2, 2], "kind": "hull"},
    {"position": [1, 4], "kind": "ramp_right"},
    {"position": [2, 4], "kind": "wreck"},
] + _DECK

# The same 2-wide component over two ramps pulling opposite ways. They cancel.
#   y=2:  . H H . .
#   y=4:  . / \ . .
_OPPOSING_RAMPS = [
    {"position": [1, 0], "kind": "anchor"},
    {"position": [1, 1], "kind": "hull"},
    {"position": [1, 2], "kind": "hull"},
    {"position": [2, 2], "kind": "hull"},
    {"position": [1, 4], "kind": "ramp_right"},
    {"position": [2, 4], "kind": "ramp_left"},
] + _DECK

# Facing ramps under a 1-wide component: it slides once, then the guard stops
# it. Without the guard it would trade back and forth forever.
_FACING_RAMPS = [
    {"position": [1, 0], "kind": "anchor"},
    {"position": [1, 1], "kind": "hull"},
    {"position": [1, 2], "kind": "pod"},
    {"position": [1, 4], "kind": "ramp_right"},
    {"position": [2, 4], "kind": "ramp_left"},
] + _DECK

# A ramp at the board edge pointing off it.
_EDGE_RAMP = [
    {"position": [4, 0], "kind": "anchor"},
    {"position": [4, 1], "kind": "hull"},
    {"position": [4, 2], "kind": "pod"},
    {"position": [4, 4], "kind": "ramp_right"},
] + _DECK


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

    def test_a_falling_component_rests_on_one_that_landed_first(self):
        game = _game()
        engine = TurnEngine(game, _level(entries=_STACKED_ORPHANS, avatar=[1, 0]))

        engine.execute_turn("cut", {"position": [1, 1]})

        board = engine.state.board
        # The pod stops on the deck; the hull stops on the pod. Neither is lost.
        self.assertEqual(board.get_entity("ground", Pos(1, 4)).kind, "pod_settled")
        self.assertEqual(board.get_entity("ground", Pos(1, 3)).kind, "wreck")

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

    def test_a_blocked_component_slides_off_a_ramp_and_keeps_falling(self):
        game = _game(collapse_config=_DEFLECT)
        engine = TurnEngine(game, _level(entries=_ONE_RAMP, avatar=[1, 0]))

        engine.execute_turn("cut", {"position": [1, 1]})

        board = engine.state.board
        # Blocked by the ramp at (1,4), the pod steps right to column 2 and
        # then falls on to the deck.
        self.assertEqual(board.get_entity("ground", Pos(2, 4)).kind, "pod_settled")
        self.assertEqual(board.get_entity("ground", Pos(1, 3)).kind, "void")

    def test_a_ramp_with_no_runoff_clogs_and_the_component_rests_on_it(self):
        game = _game(collapse_config=_DEFLECT)
        engine = TurnEngine(game, _level(entries=_CLOGGED_RAMP, avatar=[1, 0]))

        engine.execute_turn("cut", {"position": [1, 1]})

        board = engine.state.board
        # The sideways step into (2,3) is occupied, so the pod rests in the
        # cell above the ramp.
        self.assertEqual(board.get_entity("ground", Pos(1, 3)).kind, "pod_settled")

    def test_a_component_blocked_by_ramp_and_flat_ground_rests(self):
        game = _game(collapse_config=_DEFLECT)
        engine = TurnEngine(game, _level(entries=_STRADDLE, avatar=[1, 0]))

        engine.execute_turn("cut", {"position": [1, 1]})

        board = engine.state.board
        # The piece falls to row 3, where the ramp blocks column 1 and the
        # debris blocks column 2. The debris carries no slope tag, so it holds
        # the whole component and nothing slides.
        self.assertEqual(board.get_entity("ground", Pos(1, 3)).kind, "wreck")
        self.assertEqual(board.get_entity("ground", Pos(2, 3)).kind, "wreck")

    def test_ramps_pulling_opposite_ways_cancel(self):
        game = _game(collapse_config=_DEFLECT)
        engine = TurnEngine(game, _level(entries=_OPPOSING_RAMPS, avatar=[1, 0]))

        engine.execute_turn("cut", {"position": [1, 1]})

        board = engine.state.board
        # One blocker says left, the other says right, so the component rests.
        self.assertEqual(board.get_entity("ground", Pos(1, 3)).kind, "wreck")
        self.assertEqual(board.get_entity("ground", Pos(2, 3)).kind, "wreck")

    def test_facing_ramps_do_not_oscillate(self):
        game = _game(collapse_config=_DEFLECT)
        engine = TurnEngine(game, _level(entries=_FACING_RAMPS, avatar=[1, 0]))

        engine.execute_turn("cut", {"position": [1, 1]})

        board = engine.state.board
        # One slide right on to the left-pointing ramp, then the one-slide-
        # per-row guard stops it: it rests above the second ramp.
        self.assertEqual(board.get_entity("ground", Pos(2, 3)).kind, "pod_settled")

    def test_a_sideways_step_never_leaves_the_board(self):
        game = _game(collapse_config=_DEFLECT)
        engine = TurnEngine(game, _level(entries=_EDGE_RAMP, avatar=[4, 0]))

        engine.execute_turn("cut", {"position": [4, 1]})

        board = engine.state.board
        # Sliding right would leave the board, so the pod rests on the ramp.
        self.assertEqual(board.get_entity("ground", Pos(4, 3)).kind, "pod_settled")

    def test_deflect_defaults_to_off(self):
        game = _game()  # no deflect config at all
        engine = TurnEngine(game, _level(entries=_ONE_RAMP, avatar=[1, 0]))

        engine.execute_turn("cut", {"position": [1, 1]})

        board = engine.state.board
        # The ramp is just solid ground: the pod stops on top of it.
        self.assertEqual(board.get_entity("ground", Pos(1, 3)).kind, "pod_settled")

    def test_cutting_a_non_severable_cell_is_vetoed(self):
        game = _game()
        engine = TurnEngine(game, _level(entries=_HANGING, avatar=[0, 0]))

        result = engine.execute_turn("cut", {"direction": "right"})

        # A vetoed action is rejected outright — the turn does not count as a move.
        self.assertFalse(result.accepted)
        self.assertEqual(
            engine.state.board.get_entity("ground", Pos(1, 0)).kind, "anchor"
        )

    def test_sever_target_can_be_named_by_position(self):
        game = _game()
        engine = TurnEngine(game, _level(entries=_HANGING, avatar=[1, 0]))

        engine.execute_turn("cut", {"position": [1, 1]})

        board = engine.state.board
        self.assertEqual(board.get_entity("ground", Pos(1, 1)).kind, "void")
        self.assertEqual(board.get_entity("ground", Pos(1, 4)).kind, "pod_settled")

    def test_severing_a_non_adjacent_position_is_vetoed(self):
        game = _game()
        engine = TurnEngine(game, _level(entries=_HANGING, avatar=[1, 0]))

        result = engine.execute_turn("cut", {"position": [1, 2]})

        self.assertFalse(result.accepted)
        self.assertEqual(engine.state.board.get_entity("ground", Pos(1, 2)).kind, "pod")

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
