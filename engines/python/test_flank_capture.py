"""Tests for the generic Reversi-style flank_capture system.

The harness mirrors the Pincer pack wiring (ground empty/wall + a `pieces`
layer of alien/human, driven by individual_actors + flank_capture) so these
tests also validate that configuration end to end.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine


def _game(pairs=None, order=None) -> GameDef:
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
                {"id": "pieces", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "empty": {"layer": "ground", "tags": ["walkable"], "symbol": "."},
                "wall": {"layer": "ground", "tags": ["solid"], "symbol": "#"},
                "alien": {"layer": "pieces", "tags": ["actor"], "symbol": "A"},
                "splinter": {"layer": "pieces", "tags": ["actor"], "symbol": "S"},
                "human": {"layer": "pieces", "tags": [], "symbol": "H"},
            },
            "actions": [
                {"id": "tap_cell", "params": {"position": {"type": "position"}}},
                {
                    "id": "move",
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
                    "id": "actors",
                    "type": "individual_actors",
                    "config": {
                        "actorLayer": "pieces",
                        "actorTag": "actor",
                        "groundLayer": "ground",
                        "wallTag": "solid",
                    },
                },
                {
                    "id": "capture",
                    "type": "flank_capture",
                    "config": {
                        "pieceLayer": "pieces",
                        "pairs": pairs or {"alien": "human", "human": "alien"},
                        "order": order or ["alien", "human"],
                        "wallLayer": "ground",
                        "wallTag": "solid",
                    },
                },
            ],
            "rules": [],
            "defaults": {"avatar": {"enabled": False}, "maxCascadeDepth": 3},
        },
        id="flank_capture_test",
    )


# Three-way capture: every kind is a jaw against every other. Used by the
# list-victim tests below; the pack (Pincer arc 4) ships this exact shape.
_THREE_WAY = {
    "alien": ["human", "splinter"],
    "splinter": ["human", "alien"],
    "human": ["alien", "splinter"],
}


def _level(size, pieces, walls=None) -> dict:
    return {
        "id": "t",
        "board": {
            "size": list(size),
            "layers": {
                "ground": {
                    "format": "sparse",
                    "entries": [
                        {"position": list(p), "kind": "wall"} for p in (walls or [])
                    ],
                },
                "pieces": {
                    "format": "sparse",
                    "entries": [
                        {"position": list(pos), "kind": kind}
                        for pos, kind in pieces
                    ],
                },
            },
        },
        "state": {"avatar": {"enabled": False}},
        "goals": [{"id": "clear", "type": "all_cleared", "config": {"kind": "human"}}],
        "loseConditions": [],
        "solution": {"goldPath": []},
    }


def _piece(engine, x, y):
    e = engine.state.board.get_entity("pieces", Pos(x, y))
    return e.kind if e is not None else None


def _select_move(engine, select, direction):
    engine.execute_turn("tap_cell", {"position": list(select)})
    return engine.execute_turn("move", {"direction": direction})


class FlankCaptureTest(unittest.TestCase):
    def test_possess_between_two_aliens(self) -> None:
        # A . H A  → select left alien, step right onto (1,0):
        # A A H A becomes the bracket; the human at (2,0) flips.
        engine = TurnEngine(
            _game(),
            _level((5, 1), [((0, 0), "alien"), ((2, 0), "human"), ((3, 0), "alien")]),
        )
        result = _select_move(engine, (0, 0), "right")
        self.assertEqual(_piece(engine, 2, 0), "alien")
        self.assertTrue(
            any(e["type"] == "cell_transformed" and e["toKind"] == "alien"
                for e in result.events)
        )

    def test_wall_is_the_second_jaw(self) -> None:
        # A . H #  → drive the alien so the human is pinned human↔wall.
        engine = TurnEngine(
            _game(),
            _level((4, 1), [((0, 0), "alien"), ((2, 0), "human")], walls=[(3, 0)]),
        )
        _select_move(engine, (0, 0), "right")
        self.assertEqual(_piece(engine, 2, 0), "alien")

    def test_board_edge_is_not_a_terminal(self) -> None:
        # A . H |edge  → no far jaw, so nothing is possessed.
        engine = TurnEngine(
            _game(),
            _level((4, 1), [((1, 0), "alien"), ((3, 0), "human")]),
        )
        _select_move(engine, (1, 0), "right")  # alien 1->2
        self.assertEqual(_piece(engine, 3, 0), "human")

    def test_over_reach_exposes_the_mover(self) -> None:
        # Humans flank the column the alien steps into; the mover flips back.
        #   H . H   (row y=1)     alien starts at (1,0), steps down to (1,1)
        engine = TurnEngine(
            _game(),
            _level((3, 3), [((0, 1), "human"), ((2, 1), "human"), ((1, 0), "alien")]),
        )
        _select_move(engine, (1, 0), "down")
        self.assertEqual(_piece(engine, 1, 1), "human")

    def test_single_snapshot_possess_then_expose(self) -> None:
        # The mover B steps down into row y=2 = "human alien(B) human alien".
        # One snapshot means the human at (2,2) is possessed AND still counts as
        # B's right-hand human terminal, so B is exposed the same move:
        # possess flips human(2,2)->alien; expose (reading the pre-flip snapshot)
        # flips B(1,2)->human using human(0,2) and the still-human (2,2) as its
        # two terminals. Post-possess reading would have spared B — this pins the
        # single-snapshot rule.
        engine = TurnEngine(
            _game(),
            _level(
                (5, 5),
                [
                    ((0, 2), "human"),
                    ((2, 2), "human"),
                    ((3, 2), "alien"),
                    ((1, 1), "alien"),   # the mover, steps down to (1,2)
                ],
            ),
        )
        _select_move(engine, (1, 1), "down")  # alien (1,1)->(1,2) = B
        self.assertEqual(_piece(engine, 2, 2), "alien")   # possessed
        self.assertEqual(_piece(engine, 1, 2), "human")   # exposed (self-flip)
        self.assertEqual(_piece(engine, 0, 2), "human")   # terminal untouched
        self.assertEqual(_piece(engine, 3, 2), "alien")   # terminal untouched

    def test_capture_is_anchored_to_the_mover(self) -> None:
        # # H H # . A  : a human pair pinned between two walls is NOT possessed
        # by an alien move elsewhere on the row — captures follow the mover.
        engine = TurnEngine(
            _game(),
            _level(
                (6, 1),
                [((1, 0), "human"), ((2, 0), "human"), ((5, 0), "alien")],
                walls=[(0, 0), (3, 0)],
            ),
        )
        _select_move(engine, (5, 0), "left")  # alien 5->4, far from the pair
        self.assertEqual(_piece(engine, 1, 0), "human")
        self.assertEqual(_piece(engine, 2, 0), "human")

    def test_no_actor_move_no_capture(self) -> None:
        # A blocked move (into the human) is an accepted turn but emits
        # actor_blocked, not actor_moved — so flank_capture never fires and the
        # human between the two aliens is NOT possessed without a real step.
        engine = TurnEngine(
            _game(),
            _level((4, 1), [((0, 0), "alien"), ((1, 0), "human"), ((2, 0), "alien")]),
        )
        result = _select_move(engine, (0, 0), "right")  # blocked by human at (1,0)
        self.assertTrue(any(e["type"] == "actor_blocked" for e in result.events))
        self.assertFalse(any(e["type"] == "cell_transformed" for e in result.events))
        self.assertEqual(_piece(engine, 1, 0), "human")

    def test_list_victims_capture_each_kind(self) -> None:
        # A . S A  → the mover becomes the near jaw; the splinter is absorbed.
        engine = TurnEngine(
            _game(_THREE_WAY, ["human", "alien", "splinter"]),
            _level((5, 1), [((0, 0), "alien"), ((2, 0), "splinter"),
                            ((3, 0), "alien")]),
        )
        _select_move(engine, (0, 0), "right")
        self.assertEqual(_piece(engine, 2, 0), "alien")

        # S . H S  → the same rule read from the splinter side.
        engine = TurnEngine(
            _game(_THREE_WAY, ["human", "alien", "splinter"]),
            _level((5, 1), [((0, 0), "splinter"), ((2, 0), "human"),
                            ((3, 0), "splinter")]),
        )
        _select_move(engine, (0, 0), "right")
        self.assertEqual(_piece(engine, 2, 0), "splinter")

    def test_mixed_kind_run_is_immune(self) -> None:
        # Row y=1 becomes H A S H. Runs are homogeneous, so neither the alien
        # nor the splinter is a bracketed run and nothing flips — interleaving
        # your own colours is a shield.
        engine = TurnEngine(
            _game(_THREE_WAY, ["human", "alien", "splinter"]),
            _level(
                (5, 3),
                [
                    ((0, 1), "human"),
                    ((2, 1), "splinter"),
                    ((3, 1), "human"),
                    ((1, 0), "alien"),   # the mover, steps down to (1,1)
                ],
            ),
        )
        result = _select_move(engine, (1, 0), "down")
        self.assertEqual(_piece(engine, 1, 1), "alien")
        self.assertEqual(_piece(engine, 2, 1), "splinter")
        self.assertEqual(_piece(engine, 0, 1), "human")
        self.assertEqual(_piece(engine, 3, 1), "human")
        self.assertFalse(
            any(e["type"] == "cell_transformed" for e in result.events)
        )

    def test_order_resolves_overlapping_victims(self) -> None:
        # # S #  — a splinter in a wall-wall gap is a victim of BOTH the alien
        # pass and the human pass, so `order` decides which one claims it.
        pieces = [((1, 1), "splinter")]
        walls = [(0, 0), (2, 0)]

        engine = TurnEngine(
            _game(_THREE_WAY, ["human", "alien", "splinter"]),
            _level((3, 2), pieces, walls=walls),
        )
        _select_move(engine, (1, 1), "up")
        self.assertEqual(_piece(engine, 1, 0), "human")  # exposure beats greed

        engine = TurnEngine(
            _game(_THREE_WAY, ["alien", "human", "splinter"]),
            _level((3, 2), pieces, walls=walls),
        )
        _select_move(engine, (1, 1), "up")
        self.assertEqual(_piece(engine, 1, 0), "alien")  # first in order wins


if __name__ == "__main__":
    unittest.main()
