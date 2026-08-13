"""Behavioural tests for the `terrain_edit` system.

Run from engines/python/:  python test_terrain_edit.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._turn_engine import TurnEngine
from engines.python._models import Pos


def _make_game() -> GameDef:
    data = {
        "id": "com.gridponder.test_terrain_edit",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"]},
            "wall":  {"layer": "ground", "tags": ["solid"]},
        },
        "actions": [
            {"id": "place_wall", "params": {"position": {"type": "position"}}},
            {"id": "other_action", "params": {"position": {"type": "position"}}},
        ],
        "systems": [
            {"id": "edit", "type": "terrain_edit", "config": {
                "action": "place_wall",
                "layer": "ground",
                "kind": "wall",
                "fromKind": "empty",
                "budgetVariable": "walls",
            }},
        ],
    }
    return GameDef.from_dict(data, id="test_terrain_edit")


def _make_level(budget: int = 1) -> dict:
    return {
        "id": "test_level",
        "board": {
            "size": [4, 1],
            "layers": {"ground": {"format": "sparse", "entries": []}},
        },
        "state": {"variables": {"walls": budget}},
        "goals": [],
        "loseConditions": [],
    }


def _kind_at(engine, x, y):
    e = engine.state.board.get_entity("ground", Pos(x, y))
    return None if e is None else e.kind


def test_places_a_wall_and_spends_budget():
    engine = TurnEngine(_make_game(), _make_level(budget=1))
    result = engine.execute_turn("place_wall", {"position": [2, 0]})
    assert _kind_at(engine, 2, 0) == "wall", "the wall must be written"
    assert engine.state.variables["walls"] == 0, "the budget must be spent"
    assert any(e["type"] == "cell_transformed" for e in result.events), \
        "a cell_transformed event must be emitted"


def test_refuses_when_budget_is_exhausted():
    engine = TurnEngine(_make_game(), _make_level(budget=0))
    engine.execute_turn("place_wall", {"position": [2, 0]})
    assert _kind_at(engine, 2, 0) == "empty", \
        "a zero budget must leave the board untouched"


def test_refuses_when_from_kind_does_not_match():
    engine = TurnEngine(_make_game(), _make_level(budget=2))
    engine.execute_turn("place_wall", {"position": [2, 0]})
    engine.execute_turn("place_wall", {"position": [2, 0]})
    assert engine.state.variables["walls"] == 1, \
        "editing a cell that is already a wall must not spend budget"


def test_ignores_out_of_bounds():
    engine = TurnEngine(_make_game(), _make_level(budget=1))
    engine.execute_turn("place_wall", {"position": [99, 0]})
    assert engine.state.variables["walls"] == 1, \
        "an out-of-bounds edit must be a no-op"


def test_ignores_other_actions():
    engine = TurnEngine(_make_game(), _make_level(budget=1))
    engine.execute_turn("other_action", {"position": [2, 0]})
    assert _kind_at(engine, 2, 0) == "empty", \
        "an action-id mismatch must leave the board untouched"
    assert engine.state.variables["walls"] == 1, \
        "an action-id mismatch must not spend budget"


def test_refuses_non_numeric_position():
    engine = TurnEngine(_make_game(), _make_level(budget=1))
    engine.execute_turn("place_wall", {"position": ["a", 0]})
    assert _kind_at(engine, 2, 0) == "empty", \
        "a non-numeric position must leave the board untouched"
    assert engine.state.variables["walls"] == 1, \
        "a non-numeric position must not spend budget"


def test_refuses_malformed_position():
    engine = TurnEngine(_make_game(), _make_level(budget=1))
    # Test missing position key
    engine.execute_turn("place_wall", {})
    assert engine.state.variables["walls"] == 1, \
        "missing position key must not spend budget"
    # Test one-element list
    engine.execute_turn("place_wall", {"position": [2]})
    assert engine.state.variables["walls"] == 1, \
        "one-element position list must not spend budget"


def run_all() -> bool:
    tests = [
        test_places_a_wall_and_spends_budget,
        test_refuses_when_budget_is_exhausted,
        test_refuses_when_from_kind_does_not_match,
        test_ignores_out_of_bounds,
        test_ignores_other_actions,
        test_refuses_non_numeric_position,
        test_refuses_malformed_position,
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
    sys.exit(0 if run_all() else 1)
