"""Unit tests for transform_delta — the per-actor direction transform primitive.

Run from engines/python/:  python test_direction_transform.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._models import transform_delta, dir_delta

UP, DOWN, LEFT, RIGHT = (0, -1), (0, 1), (-1, 0), (1, 0)


def test_identity_is_unchanged() -> None:
    for d in (UP, DOWN, LEFT, RIGHT):
        assert transform_delta(d, "identity") == d, f"identity changed {d}"
    print("  OK  identity_is_unchanged")


def test_missing_and_unknown_are_identity() -> None:
    """Parity-safe leniency: unrecognised values must not throw."""
    assert transform_delta(RIGHT, None) == RIGHT
    assert transform_delta(RIGHT, "not_a_transform") == RIGHT
    print("  OK  missing_and_unknown_are_identity")


def test_invert_reverses_both_axes() -> None:
    assert transform_delta(RIGHT, "invert") == LEFT
    assert transform_delta(LEFT, "invert") == RIGHT
    assert transform_delta(UP, "invert") == DOWN
    assert transform_delta(DOWN, "invert") == UP
    print("  OK  invert_reverses_both_axes")


def test_mirror_x_flips_horizontal_only() -> None:
    assert transform_delta(RIGHT, "mirror_x") == LEFT
    assert transform_delta(LEFT, "mirror_x") == RIGHT
    assert transform_delta(UP, "mirror_x") == UP
    assert transform_delta(DOWN, "mirror_x") == DOWN
    print("  OK  mirror_x_flips_horizontal_only")


def test_mirror_y_flips_vertical_only() -> None:
    assert transform_delta(UP, "mirror_y") == DOWN
    assert transform_delta(DOWN, "mirror_y") == UP
    assert transform_delta(RIGHT, "mirror_y") == RIGHT
    assert transform_delta(LEFT, "mirror_y") == LEFT
    print("  OK  mirror_y_flips_vertical_only")


def test_transform_of_cardinal_is_cardinal() -> None:
    """Bucket resolution assumes transforms map cardinals to cardinals."""
    cardinals = {UP, DOWN, LEFT, RIGHT}
    for name in ("identity", "invert", "mirror_x", "mirror_y"):
        for d in ("up", "down", "left", "right"):
            assert transform_delta(dir_delta(d), name) in cardinals
    print("  OK  transform_of_cardinal_is_cardinal")


def run_all() -> bool:
    tests = [
        test_identity_is_unchanged,
        test_missing_and_unknown_are_identity,
        test_invert_reverses_both_axes,
        test_mirror_x_flips_horizontal_only,
        test_mirror_y_flips_vertical_only,
        test_transform_of_cardinal_is_cardinal,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}")
            failed += 1
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
