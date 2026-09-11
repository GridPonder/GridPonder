"""Behavioural tests for `overlay_cursor.carryLayers` and the `region_transform`
`exchange` operation.

Together they model a cursor that holds things: the second layer rides along
with the overlay, and the exchange swaps it with the layer underneath.

Run from engines/python/:  python test_overlay_exchange.py
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._turn_engine import TurnEngine
from engines.python._models import Pos

PAIRS = [
    ["ink_red", "held_red"],
    ["ink_blue", "held_blue"],
    [None, "slot_empty"],
]


def _make_game(pairs=PAIRS) -> GameDef:
    data = {
        "id": "com.gridponder.test_overlay_exchange",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "ink", "occupancy": "zero_or_one"},
            {"id": "held", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": []},
            "void": {"layer": "ground", "tags": []},
            "ink_red": {"layer": "ink", "tags": []},
            "ink_blue": {"layer": "ink", "tags": []},
            "held_red": {"layer": "held", "tags": ["carried"]},
            "held_blue": {"layer": "held", "tags": ["carried"]},
            "slot_empty": {"layer": "held", "tags": []},
        },
        "actions": [
            {"id": "move", "params": {"direction": {"type": "direction",
                                                    "values": ["up", "down", "left", "right"]}}},
            {"id": "press", "params": {}},
        ],
        "systems": [
            {"id": "cursor", "type": "overlay_cursor", "config": {
                "moveAction": "move", "size": [2, 2], "carryLayers": ["held"]}},
            {"id": "stamp", "type": "region_transform", "config": {
                "operations": {"press": {
                    "type": "exchange", "action": "press",
                    "layers": ["ink", "held"], "pairs": pairs}}}},
        ],
        "defaults": {"avatar": {"enabled": False}},
    }
    return GameDef.from_dict(data, id="test_overlay_exchange")


def _level(ink, held, overlay=(0, 0), size=(4, 3), ground=(), goals=None) -> dict:
    return {
        "id": "t",
        "board": {
            "size": list(size),
            "layers": {
                "ground": {"format": "sparse", "entries": [
                    {"position": list(p), "kind": "void"} for p in ground]},
                "ink": {"format": "sparse", "entries": [
                    {"position": list(p), "kind": k} for p, k in ink.items()]},
                "held": {"format": "sparse", "entries": [
                    {"position": list(p), "kind": k} for p, k in held.items()]},
            },
        },
        "state": {"avatar": {"enabled": False},
                  "overlay": {"position": list(overlay), "size": [2, 2]}},
        "goals": goals or [],
    }


def _slots(x=0, y=0, **kinds):
    """The four held-layer cells of a 2x2 overlay at (x, y), empty by default."""
    names = {"a": (0, 0), "b": (1, 0), "c": (0, 1), "d": (1, 1)}
    out = {}
    for name, (dx, dy) in names.items():
        out[(x + dx, y + dy)] = kinds.get(name, "slot_empty")
    return out


def _kind(engine, layer, x, y):
    e = engine.state.board.get_entity(layer, Pos(x, y))
    return None if e is None else e.kind


def _press(engine):
    return engine.execute_turn("press")


def _move(engine, d):
    return engine.execute_turn("move", {"direction": d})


class CarryTests(unittest.TestCase):
    def test_held_layer_rides_with_the_overlay(self):
        engine = TurnEngine(_make_game(), _level({(0, 0): "ink_red"}, _slots(a="held_blue")))
        _move(engine, "right")
        self.assertEqual((engine.state.overlay.x, engine.state.overlay.y), (1, 0))
        self.assertEqual(_kind(engine, "held", 1, 0), "held_blue")
        self.assertEqual(_kind(engine, "held", 2, 1), "slot_empty")
        self.assertIsNone(_kind(engine, "held", 0, 0))
        self.assertIsNone(_kind(engine, "held", 0, 1))
        # Moving never touches the layer underneath.
        self.assertEqual(_kind(engine, "ink", 0, 0), "ink_red")

    def test_blocked_move_keeps_everything_in_place(self):
        engine = TurnEngine(_make_game(), _level({}, _slots(d="held_red")))
        _move(engine, "left")
        _move(engine, "up")
        self.assertEqual((engine.state.overlay.x, engine.state.overlay.y), (0, 0))
        self.assertEqual(_kind(engine, "held", 1, 1), "held_red")

    def test_overlay_position_is_part_of_the_state_key(self):
        engine = TurnEngine(_make_game(), _level({}, _slots()))
        before = engine.state.to_key()
        _move(engine, "right")
        self.assertNotEqual(before, engine.state.to_key())


class ExchangeTests(unittest.TestCase):
    def test_all_four_cells_exchange_at_once(self):
        ink = {(0, 0): "ink_red", (1, 1): "ink_blue", (1, 0): "ink_red"}
        held = _slots(b="held_blue", c="held_red")
        engine = TurnEngine(_make_game(), _level(ink, held))
        result = _press(engine)
        # a: red lifted; b: red <-> blue swapped; c: red dropped; d: blue lifted.
        self.assertEqual(_kind(engine, "held", 0, 0), "held_red")
        self.assertIsNone(_kind(engine, "ink", 0, 0))
        self.assertEqual(_kind(engine, "ink", 1, 0), "ink_blue")
        self.assertEqual(_kind(engine, "held", 1, 0), "held_red")
        self.assertEqual(_kind(engine, "ink", 0, 1), "ink_red")
        self.assertEqual(_kind(engine, "held", 0, 1), "slot_empty")
        self.assertEqual(_kind(engine, "held", 1, 1), "held_blue")
        self.assertIsNone(_kind(engine, "ink", 1, 1))
        modes = {tuple(e["position"]): e["mode"] for e in result.events
                 if e["type"] == "cell_exchanged"}
        self.assertEqual(modes, {(0, 0): "lift", (1, 0): "swap", (0, 1): "drop", (1, 1): "lift"})

    def test_empty_on_empty_changes_nothing_and_says_nothing(self):
        engine = TurnEngine(_make_game(), _level({}, _slots()))
        result = _press(engine)
        self.assertFalse([e for e in result.events if e["type"] == "cell_exchanged"])
        for x, y in ((0, 0), (1, 0), (0, 1), (1, 1)):
            self.assertEqual(_kind(engine, "held", x, y), "slot_empty")
            self.assertIsNone(_kind(engine, "ink", x, y))

    def test_pressing_twice_restores(self):
        ink = {(0, 0): "ink_red", (1, 1): "ink_blue"}
        engine = TurnEngine(_make_game(), _level(ink, _slots(b="held_red")))
        before = engine.state.to_key()
        _press(engine)
        self.assertNotEqual(before, engine.state.to_key())
        _press(engine)
        self.assertEqual(before, engine.state.to_key())

    def test_carry_then_deposit(self):
        engine = TurnEngine(_make_game(), _level({(0, 0): "ink_red"}, _slots()))
        _press(engine)
        _move(engine, "right")
        _move(engine, "right")
        _press(engine)
        self.assertIsNone(_kind(engine, "ink", 0, 0))
        self.assertEqual(_kind(engine, "ink", 2, 0), "ink_red")
        self.assertEqual(_kind(engine, "held", 2, 0), "slot_empty")

    def test_undo_restores_cursor_and_held_layer(self):
        engine = TurnEngine(_make_game(), _level({(0, 0): "ink_red"}, _slots()))
        before = engine.state.to_key()
        _press(engine)
        _move(engine, "right")
        engine.undo()
        engine.undo()
        self.assertEqual(before, engine.state.to_key())

    def test_unpaired_kinds_cross_unchanged(self):
        engine = TurnEngine(_make_game(pairs=[]), _level({(0, 0): "ink_red"}, {}))
        _press(engine)
        self.assertEqual(_kind(engine, "held", 0, 0), "ink_red")
        self.assertIsNone(_kind(engine, "ink", 0, 0))

    def test_void_cells_do_not_exchange(self):
        ink = {(1, 0): "ink_red"}
        engine = TurnEngine(_make_game(), _level(ink, _slots(a="held_blue"), ground=[(0, 0)]))
        _press(engine)
        self.assertEqual(_kind(engine, "held", 0, 0), "held_blue")
        self.assertEqual(_kind(engine, "held", 1, 0), "held_red")

    def test_win_needs_an_empty_cursor(self):
        goals = [
            {"id": "match", "type": "board_match", "config": {
                "matchMode": "exact",
                "targetLayers": {"ink": [[None, "ink_red", None, None],
                                         [None, None, None, None],
                                         [None, None, None, None]]}}},
            {"id": "empty", "type": "all_cleared", "config": {"tag": "carried"}},
        ]
        # Red already on its target, but a second red is still held.
        ink = {(1, 0): "ink_red"}
        engine = TurnEngine(_make_game(), _level(ink, _slots(2, 1, d="held_red"),
                                                 overlay=(2, 1), goals=goals))
        _move(engine, "up")
        self.assertFalse(engine.is_won)
        engine = TurnEngine(_make_game(), _level({}, _slots(a="held_red"), goals=goals))
        _move(engine, "right")
        self.assertFalse(engine.is_won)
        _press(engine)
        self.assertTrue(engine.is_won)


if __name__ == "__main__":
    unittest.main()
