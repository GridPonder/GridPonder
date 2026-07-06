"""
Smoke test for the `balance` goal type. Builds an inline GameDef (no pack
files) with a `territory` layer over a `ground` layer, constructs a Board +
GameState directly (no TurnEngine needed since goal evaluation only reads
state.board), and calls `_evaluate_goal` for a "balance" goal.

Run from engines/python/:  python test_balance_goal.py
"""
from __future__ import annotations
import sys
from pathlib import Path

# Make engines/ importable
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Board, GameState
from engines.python._goal import _evaluate_goal


def _make_game() -> GameDef:
    data = {
        "id": "com.gridponder.test_balance_goal",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "territory", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"]},
            "wall":  {"layer": "ground", "tags": ["solid"]},
            "terr_wei": {"layer": "territory", "tags": ["territory"]},
            "terr_shu": {"layer": "territory", "tags": ["territory"]},
            "terr_wu":  {"layer": "territory", "tags": ["territory"]},
        },
        "actions": [],
        "systems": [],
    }
    return GameDef.from_dict(data, id="test_balance_goal")


def _make_state(game: GameDef, territory: list[tuple[int, int, str]], size: int = 3) -> GameState:
    """3x3 all-`empty` ground (claimable=9), territory cells as given."""
    level = {
        "board": {
            "size": [size, size],
            "layers": {
                "ground": {"format": "sparse", "entries": []},
                "territory": {
                    "format": "sparse",
                    "entries": [{"position": [x, y], "kind": kind} for x, y, kind in territory],
                },
            },
        },
        "state": {},
    }
    board = Board.from_json(level["board"], game.layers)
    return GameState.from_json(level["state"], board, game.defaults)


_GOAL = {
    "id": "balance_goal",
    "type": "balance",
    "config": {
        "layer": "territory",
        "owners": ["terr_wei", "terr_shu", "terr_wu"],
        "claimableLayer": "ground",
        "claimableKind": "empty",
        "requireComplete": True,
        "requireEqual": True,
    },
}

# Same as _GOAL but with `claimableKind` OMITTED — exercises the
# `cfg.get("claimableKind", layer.default_kind)` fallback in `_count_claimable`,
# which must resolve to the `ground` layer's declared default ("empty").
_GOAL_NO_CLAIMABLE_KIND = {
    "id": "balance_goal",
    "type": "balance",
    "config": {
        "layer": "territory",
        "owners": ["terr_wei", "terr_shu", "terr_wu"],
        "claimableLayer": "ground",
        "requireComplete": True,
        "requireEqual": True,
    },
}


def _territory(counts: dict[str, int]) -> list[tuple[int, int, str]]:
    """Lay out `counts[kind]` cells of each kind along row-major positions,
    leaving any remaining cells (out of a 3x3=9 grid) unclaimed."""
    cells = []
    i = 0
    for kind, n in counts.items():
        for _ in range(n):
            x, y = i % 3, i // 3
            cells.append((x, y, kind))
            i += 1
    return cells


def test_incomplete_is_not_done() -> None:
    """3/3/2 with one empty cell: owned=8 < claimable=9 -> incomplete, not done."""
    game = _make_game()
    territory = _territory({"terr_wei": 3, "terr_shu": 3, "terr_wu": 2})
    state = _make_state(game, territory)

    done, progress = _evaluate_goal(_GOAL, state, game, [])

    assert not done, "incomplete board (8/9 owned) must not be done"
    assert abs(progress - 8 / 9) < 1e-9, f"expected progress 8/9, got {progress}"
    print("  OK  incomplete_is_not_done")


def test_complete_but_unequal_is_not_done() -> None:
    """4/3/2 fully claimed but unequal shares -> not done despite complete."""
    game = _make_game()
    territory = _territory({"terr_wei": 4, "terr_shu": 3, "terr_wu": 2})
    state = _make_state(game, territory)

    done, progress = _evaluate_goal(_GOAL, state, game, [])

    assert not done, "unequal shares (4/3/2) must not be done"
    assert abs(progress - 1.0) < 1e-9, f"expected progress 1.0 (fully claimed), got {progress}"
    print("  OK  complete_but_unequal_is_not_done")


def test_complete_and_equal_is_done() -> None:
    """3/3/3 fully claimed and equal shares -> done."""
    game = _make_game()
    territory = _territory({"terr_wei": 3, "terr_shu": 3, "terr_wu": 3})
    state = _make_state(game, territory)

    done, progress = _evaluate_goal(_GOAL, state, game, [])

    assert done, "complete (9/9) and equal shares (3/3/3) must be done"
    assert abs(progress - 1.0) < 1e-9, f"expected progress 1.0, got {progress}"
    print("  OK  complete_and_equal_is_done")


def test_omitted_claimable_kind_falls_back_to_layer_default() -> None:
    """Reuses the 3/3/3 complete-and-equal fixture but OMITS `claimableKind`
    from the goal config, so `_count_claimable` must resolve the claimable
    kind via `cfg.get("claimableKind", layer.default_kind)` -> the `ground`
    layer's declared `"default": "empty"`. That still makes claimable=9, so
    the outcome matches the explicit-`empty` case: complete + equal -> done,
    progress 1.0. If the fallback did not honor the layer default, claimable
    would be 0 -> owned(9) != claimable(0) -> complete=false -> done=false —
    so this case genuinely locks in the fallback."""
    game = _make_game()
    territory = _territory({"terr_wei": 3, "terr_shu": 3, "terr_wu": 3})
    state = _make_state(game, territory)

    done, progress = _evaluate_goal(_GOAL_NO_CLAIMABLE_KIND, state, game, [])

    assert done, "omitted claimableKind must fall back to layer default (empty) -> claimable=9 -> complete + equal -> done"
    assert abs(progress - 1.0) < 1e-9, f"expected progress 1.0, got {progress}"
    print("  OK  omitted_claimable_kind_falls_back_to_layer_default")


def run_all() -> bool:
    tests = [
        test_incomplete_is_not_done,
        test_complete_but_unequal_is_not_done,
        test_complete_and_equal_is_done,
        test_omitted_claimable_kind_falls_back_to_layer_default,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            import traceback
            print(f"  ERROR {t.__name__}: {exc}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
