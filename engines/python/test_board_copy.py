"""Board.copy — a copy must share no mutable params with its source.

Systems write entity params in place (follower_npcs assigns `facing` on every
reversal), so a copy that shares a params map, or a list or dict nested inside
one, lets play rewrite the board it was copied from. Dart's `BoardLayer.copy`
is checked by engines/dart/test/board_copy_aliasing_test.dart.

Run from the repo root:  python engines/python/test_board_copy.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._models import Board, BoardLayer, Entity, MultiCellObject, Pos


def _board() -> Board:
    actors = BoardLayer.empty(2, 1)
    actors.set(Pos(0, 0), Entity("machine", {
        "facing": "right",
        "route": [[0, 0]],
        "gear": {"teeth": 8},
    }))
    pipe = MultiCellObject("m", "pipe", [Pos(1, 0)], {"flow": [1], "ends": {"a": [0]}})
    return Board(2, 1, {"actors": actors}, [pipe])


def test_a_copied_entity_shares_no_nested_params() -> None:
    board = _board()
    copied = board.copy().layers["actors"].get(Pos(0, 0))
    copied.params["facing"] = "left"
    copied.params["route"].append([1, 0])
    copied.params["gear"]["teeth"] = 12

    source = board.layers["actors"].get(Pos(0, 0))
    assert source.params == {
        "facing": "right", "route": [[0, 0]], "gear": {"teeth": 8},
    }, source.params
    print("  OK  a_copied_entity_shares_no_nested_params")


def test_a_copied_object_shares_no_nested_params() -> None:
    board = _board()
    copied = board.copy().multi_cell_objects[0]
    copied.params["flow"].append(2)
    copied.params["ends"]["a"].append(1)

    assert board.multi_cell_objects[0].params == {
        "flow": [1], "ends": {"a": [0]},
    }, board.multi_cell_objects[0].params
    print("  OK  a_copied_object_shares_no_nested_params")


TESTS = [
    test_a_copied_entity_shares_no_nested_params,
    test_a_copied_object_shares_no_nested_params,
]


def run_all() -> bool:
    print("Board.copy tests")
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}")
            failed += 1
    print(f"\nResults: {len(TESTS) - failed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
