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
from engines.python._goal import _evaluate_goal, evaluate_lose


def _make_game(*, declare_ground_default: bool = True) -> GameDef:
    ground_layer = {"id": "ground", "occupancy": "exactly_one"}
    if declare_ground_default:
        ground_layer["default"] = "empty"
    data = {
        "id": "com.gridponder.test_balance_goal",
        "layers": [
            ground_layer,
            {"id": "territory", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"]},
            "wall":  {"layer": "ground", "tags": ["solid"]},
            "contested": {"layer": "ground", "tags": ["walkable", "contested"]},
            "terr_wei": {"layer": "territory", "tags": ["territory"]},
            "terr_shu": {"layer": "territory", "tags": ["territory"]},
            "terr_wu":  {"layer": "territory", "tags": ["territory"]},
        },
        "actions": [],
        "systems": [],
    }
    return GameDef.from_dict(data, id="test_balance_goal")


def _make_state(
    game: GameDef,
    territory: list[tuple[int, int, str]],
    size: int = 3,
    contested_cells: list[tuple[int, int]] | None = None,
) -> GameState:
    """3x3 ground (claimable=9 when every cell counts), territory cells as given.

    `contested_cells` marks ground cells as the `contested` kind — used by the
    list-valued `claimableKind` case and by the overwrite-guard tests, where the
    *board* carrying tagged cells (not the config) is what matters.
    """
    level = {
        "board": {
            "size": [size, size],
            "layers": {
                "ground": {
                    "format": "sparse",
                    "entries": [
                        {"position": [x, y], "kind": "contested"}
                        for x, y in (contested_cells or [])
                    ],
                },
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


def test_claimable_kind_accepts_list() -> None:
    """A board may have more than one claimable ground kind.

    3x3 with 3 `contested` cells and 6 `empty`. Territory is 3/3/3 = 9 owned.
      - claimableKind "empty"                 -> claimable=6, owned=9 -> not complete
      - claimableKind ["empty", "contested"]  -> claimable=9, owned=9 -> complete + equal
    """
    game = _make_game()
    territory = _territory({"terr_wei": 3, "terr_shu": 3, "terr_wu": 3})
    contested = [(0, 0), (1, 0), (2, 0)]
    state = _make_state(game, territory, contested_cells=contested)

    string_goal = {**_GOAL, "config": {**_GOAL["config"], "claimableKind": "empty"}}
    done, _ = _evaluate_goal(string_goal, state, game, [])
    assert not done, "string claimableKind must count only `empty` (6), so 9 owned != 6 claimable"

    list_goal = {**_GOAL, "config": {**_GOAL["config"],
                                     "claimableKind": ["empty", "contested"]}}
    done, progress = _evaluate_goal(list_goal, state, game, [])
    assert done, "list claimableKind must count empty+contested (9) -> complete + equal -> done"
    assert abs(progress - 1.0) < 1e-9, f"expected progress 1.0, got {progress}"
    print("  OK  claimable_kind_accepts_list")


def test_omitted_claimable_layer_defaults_to_ground() -> None:
    game = _make_game()
    state = _make_state(
        game,
        _territory({"terr_wei": 3, "terr_shu": 3, "terr_wu": 3}),
    )
    goal = {**_GOAL, "config": {**_GOAL["config"]}}
    del goal["config"]["claimableLayer"]

    done, progress = _evaluate_goal(goal, state, game, [])

    assert done
    assert abs(progress - 1.0) < 1e-9
    print("  OK  omitted_claimable_layer_defaults_to_ground")


def test_missing_declared_default_matches_effective_empty_kind() -> None:
    game = _make_game(declare_ground_default=False)
    state = _make_state(
        game,
        _territory({"terr_wei": 3, "terr_shu": 3, "terr_wu": 3}),
    )

    done, progress = _evaluate_goal(_GOAL_NO_CLAIMABLE_KIND, state, game, [])
    is_lost, _ = evaluate_lose(
        _LOSE_UNREACHABLE,
        state,
        [_GOAL_NO_CLAIMABLE_KIND],
        game,
    )

    assert done
    assert abs(progress - 1.0) < 1e-9
    assert not is_lost
    print("  OK  missing_declared_default_matches_effective_empty_kind")


def test_balance_lose_conditions_ignore_non_complete_or_non_equal_goals() -> None:
    game = _make_game()
    unequal_state = _make_state(
        game,
        _territory({"terr_wei": 4, "terr_shu": 3, "terr_wu": 2}),
    )
    unequal_goal = {
        **_GOAL,
        "config": {**_GOAL["config"], "requireEqual": False},
    }
    partial_state = _make_state(
        game,
        _territory({"terr_wei": 1, "terr_shu": 1, "terr_wu": 1}),
        size=4,
    )
    partial_goal = {
        **_GOAL,
        "config": {**_GOAL["config"], "requireComplete": False},
    }

    for state, goal in ((unequal_state, unequal_goal), (partial_state, partial_goal)):
        for condition in (_LOSE_UNREACHABLE, _LOSE_BUDGET):
            is_lost, _ = evaluate_lose(condition, state, [goal], game)
            assert not is_lost
    print("  OK  balance_lose_conditions_ignore_non_complete_or_non_equal_goals")


def test_require_complete_false_needs_owned_territory() -> None:
    game = _make_game()
    state = _make_state(game, [])
    goal = {
        **_GOAL,
        "config": {**_GOAL["config"], "requireComplete": False},
    }

    done, progress = _evaluate_goal(goal, state, game, [])

    assert not done
    assert progress == 0.0
    print("  OK  require_complete_false_needs_owned_territory")


def test_balance_budget_aggregates_actors_for_one_owner() -> None:
    game = _make_game()
    state = _make_state(
        game,
        _territory({"terr_wei": 1, "terr_shu": 3, "terr_wu": 3}),
    )
    state.variables["actorMovesRemaining"] = {"worker_a": 1, "worker_b": 1}
    lose = [{
        "type": "balance_budget_exhausted",
        "config": {
            "goalId": "balance_goal",
            "actorToOwner": {
                "worker_a": "terr_wei",
                "worker_b": "terr_wei",
            },
        },
    }]

    is_lost, _reason = evaluate_lose(lose, state, [_GOAL], game)

    assert not is_lost
    print("  OK  balance_budget_aggregates_actors_for_one_owner")


# Lose conditions mirroring the balance goal above (resolved via goalId).
_LOSE_UNREACHABLE = [{"type": "balance_unreachable", "config": {"goalId": "balance_goal"}}]
_LOSE_BUDGET = [{"type": "balance_budget_exhausted", "config": {"goalId": "balance_goal"}}]


# Goal counting BOTH ground kinds as claimable. The guard tests place contested
# cells on the board, which would otherwise drop `claimable` from 9 to 8 under a
# string `claimableKind: "empty"` — and 8 % 3 != 0 trips the "equal shares are
# arithmetically impossible" branch *before* the over-claim test, masking what
# these tests are actually checking.
_GOAL_CONTESTED = {
    "id": "balance_goal",
    "type": "balance",
    "config": {**_GOAL["config"], "claimableKind": ["empty", "contested"]},
}


def _with_contested_overwrite(game: GameDef, *, enabled: bool = True) -> GameDef:
    """Declare a `tagged` overwrite policy on every actor system.

    Whether the guard trips is decided by the BOARD carrying tagged cells, not
    by this config — see the two tests below, which differ only in the board.
    """
    game.systems.append({
        "id": "movement",
        "type": "coupled_actors",
        "enabled": enabled,
        "config": {
            "claim": {
                "layer": "territory",
                "map": {},
                "overwrite": {"mode": "tagged", "tag": "contested"},
            },
        },
    })
    return game


def test_balance_unreachable_fires_on_overclaim() -> None:
    """4/3/2 on a 9-cell board (target 3): wei owns more than its equal share, and
    claims are permanent, so equal thirds can never be reached -> the level is
    lost immediately via balance_unreachable."""
    game = _make_game()
    territory = _territory({"terr_wei": 4, "terr_shu": 3, "terr_wu": 2})
    state = _make_state(game, territory)

    is_lost, reason = evaluate_lose(_LOSE_UNREACHABLE, state, [_GOAL], game)

    assert is_lost, "an owner over its equal share (4/3/2) must lose"
    assert reason == "balance_unreachable", f"unexpected reason {reason!r}"
    print("  OK  balance_unreachable_fires_on_overclaim")


def test_balance_unreachable_quiet_on_valid_partial() -> None:
    """3/3/2 (one cell still unclaimed, nobody over target): still winnable, so
    balance_unreachable must stay quiet."""
    game = _make_game()
    territory = _territory({"terr_wei": 3, "terr_shu": 3, "terr_wu": 2})
    state = _make_state(game, territory)

    is_lost, reason = evaluate_lose(_LOSE_UNREACHABLE, state, [_GOAL], game)

    assert not is_lost, "a still-winnable partial (3/3/2) must not lose"
    assert reason is None, f"expected no lose reason, got {reason!r}"
    print("  OK  balance_unreachable_quiet_on_valid_partial")


def test_balance_unreachable_quiet_on_balanced_state() -> None:
    """3/3/3 fully balanced: nobody exceeds target, so balance_unreachable does
    not fire (the win is decided by the goal, not this lose condition)."""
    game = _make_game()
    territory = _territory({"terr_wei": 3, "terr_shu": 3, "terr_wu": 3})
    state = _make_state(game, territory)

    is_lost, _reason = evaluate_lose(_LOSE_UNREACHABLE, state, [_GOAL], game)

    assert not is_lost, "a balanced 3/3/3 state must not trip balance_unreachable"
    print("  OK  balance_unreachable_quiet_on_balanced_state")


# ---------------------------------------------------------------------------
# Over-claim guard under claim.overwrite (DSL 0.8)
#
# Both balance lose conditions share an over-claim test ("someone holds more
# than their equal share, and claims are permanent, so this is dead"). That
# premise fails when cells can be repainted. The guard is board-level, not
# config-level: a policy declared game-wide is inert on boards that place no
# tagged cells.
# ---------------------------------------------------------------------------

def test_balance_unreachable_suppressed_when_board_has_contested_cells() -> None:
    """4/3/2 with a contested cell on the board: the over-share owner can be
    repainted back down, so the condition must stay quiet rather than report a
    false loss."""
    game = _with_contested_overwrite(_make_game())
    territory = _territory({"terr_wei": 4, "terr_shu": 3, "terr_wu": 2})
    state = _make_state(game, territory, contested_cells=[(0, 0)])

    is_lost, reason = evaluate_lose(_LOSE_UNREACHABLE, state, [_GOAL_CONTESTED], game)

    assert not is_lost, (
        f"overclaim is recoverable while contested cells exist; must not lose "
        f"(got reason={reason!r})"
    )
    print("  OK  balance_unreachable_suppressed_when_board_has_contested_cells")


def test_balance_budget_exhausted_suppressed_when_board_has_contested_cells() -> None:
    """THE tk_015 CASE. balance_budget_exhausted carries the same over-claim test
    as balance_unreachable. tk_015 uses THIS condition, so without the guard it
    would lose the instant a kingdom steals a contested cell and transiently
    exceeds its third — the level's core action."""
    game = _with_contested_overwrite(_make_game())
    territory = _territory({"terr_wei": 4, "terr_shu": 3, "terr_wu": 2})
    state = _make_state(game, territory, contested_cells=[(0, 0)])

    is_lost, reason = evaluate_lose(_LOSE_BUDGET, state, [_GOAL_CONTESTED], game)

    assert not is_lost, (
        f"transient overclaim must not lose while contested cells exist "
        f"(got reason={reason!r})"
    )
    print("  OK  balance_budget_exhausted_suppressed_when_board_has_contested_cells")


def test_over_claim_still_fires_when_board_has_no_contested_cells() -> None:
    """A `tagged` overwrite declared game-wide must NOT disable the over-claim
    test on boards that place no tagged cells. This is what makes it safe to
    declare the policy once in game.json: without it, every level in the pack
    silently loses its fail condition and no gold-path test notices."""
    game = _with_contested_overwrite(_make_game())
    territory = _territory({"terr_wei": 4, "terr_shu": 3, "terr_wu": 2})
    state = _make_state(game, territory, contested_cells=[])

    is_lost, reason = evaluate_lose(_LOSE_UNREACHABLE, state, [_GOAL_CONTESTED], game)
    assert is_lost, "no contested cells on the board -> overclaim is still terminal"
    assert reason == "balance_unreachable", f"unexpected reason {reason!r}"

    is_lost, reason = evaluate_lose(_LOSE_BUDGET, state, [_GOAL_CONTESTED], game)
    assert is_lost, "no contested cells on the board -> overclaim is still terminal"
    assert reason == "balance_budget_exhausted", f"unexpected reason {reason!r}"
    print("  OK  over_claim_still_fires_when_board_has_no_contested_cells")


def test_disabled_actor_system_does_not_make_claims_overwritable() -> None:
    game = _with_contested_overwrite(_make_game(), enabled=False)
    territory = _territory({"terr_wei": 4, "terr_shu": 3, "terr_wu": 2})
    state = _make_state(game, territory, contested_cells=[(0, 0)])

    is_lost, reason = evaluate_lose(
        _LOSE_UNREACHABLE, state, [_GOAL_CONTESTED], game)

    assert is_lost
    assert reason == "balance_unreachable"
    print("  OK  disabled_actor_system_does_not_make_claims_overwritable")


def run_all() -> bool:
    tests = [
        test_incomplete_is_not_done,
        test_complete_but_unequal_is_not_done,
        test_complete_and_equal_is_done,
        test_omitted_claimable_kind_falls_back_to_layer_default,
        test_claimable_kind_accepts_list,
        test_omitted_claimable_layer_defaults_to_ground,
        test_missing_declared_default_matches_effective_empty_kind,
        test_balance_lose_conditions_ignore_non_complete_or_non_equal_goals,
        test_require_complete_false_needs_owned_territory,
        test_balance_budget_aggregates_actors_for_one_owner,
        test_balance_unreachable_fires_on_overclaim,
        test_balance_unreachable_quiet_on_valid_partial,
        test_balance_unreachable_quiet_on_balanced_state,
        test_balance_unreachable_suppressed_when_board_has_contested_cells,
        test_balance_budget_exhausted_suppressed_when_board_has_contested_cells,
        test_over_claim_still_fires_when_board_has_no_contested_cells,
        test_disabled_actor_system_does_not_make_claims_overwritable,
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
