"""
Tests for the `cargo_gate` system — see docs/dsl/04_systems.md §2.28.

A 6x1 corridor; the avatar starts at x=2 facing a gate cell at x=3. Its
cargo is seeded directly into the trailing_body system's segment list,
straight behind it, since building it up through pickups isn't the point.

Run from the repo root:  python3 engines/python/test_cargo_gate.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine


def _make_game() -> GameDef:
    data = {
        "id": "com.gridponder.test_cargo_gate",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
            {"id": "tail", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "floor": {"layer": "ground", "tags": ["walkable"]},
            "colored_road": {"layer": "ground", "tags": ["walkable", "cargo_gate"]},
            "seg": {"layer": "tail", "tags": ["solid"]},
        },
        "actions": [
            {"id": "move", "params": {"direction": {"type": "direction", "values": ["up", "down", "left", "right"]}}},
        ],
        "systems": [
            {"id": "gates", "type": "cargo_gate", "config": {"cargoSystem": "trail", "maxCargo": 1}},
            {"id": "navigation", "type": "avatar_navigation", "config": {"solidLayers": ["tail"]}},
            {"id": "trail", "type": "trailing_body", "config": {
                "moverTag": "avatar", "bodyLayer": "tail", "segmentKindTemplate": "seg",
            }},
        ],
    }
    return GameDef.from_dict(data, id="test_cargo_gate")


def _engine(gate_color: str | None, cargo: list[str]) -> TurnEngine:
    ground = [] if gate_color is None else [{"position": [3, 0], "kind": "colored_road", "color": gate_color}]
    level = {
        "id": "test_level",
        "board": {"size": [6, 1], "layers": {"ground": {"format": "sparse", "entries": ground}}},
        "state": {"avatar": {"enabled": True, "position": [2, 0]}},
        "goals": [],
        "loseConditions": [],
    }
    engine = TurnEngine(_make_game(), level)
    engine.state.variables["_trailingBody_trail_segments"] = [
        {"position": [1 - i, 0], "color": c} for i, c in enumerate(cargo)
    ]
    return engine


def _step_right(engine: TurnEngine):
    return engine.execute_turn("move", {"direction": "right"})


def test_empty_truck_enters_any_gate():
    engine = _engine("blue", [])
    assert _step_right(engine).accepted
    assert engine.state.avatar.position == Pos(3, 0)


def test_single_matching_car_enters():
    engine = _engine("red", ["red"])
    assert _step_right(engine).accepted
    assert engine.state.avatar.position == Pos(3, 0)


def test_single_other_color_is_refused_without_spending_the_turn():
    engine = _engine("blue", ["red"])
    result = _step_right(engine)
    assert not result.accepted
    assert engine.state.avatar.position == Pos(2, 0)
    assert engine.state.action_count == 0
    blocked = [e for e in result.events if e["type"] == "cell_blocked"]
    assert blocked and blocked[0]["position"] == Pos(3, 0), result.events


def test_two_cars_are_refused_even_when_both_match():
    engine = _engine("red", ["red", "red"])
    assert not _step_right(engine).accepted
    assert engine.state.avatar.position == Pos(2, 0)


def test_plain_road_ignores_cargo():
    engine = _engine(None, ["red", "blue"])
    assert _step_right(engine).accepted
    assert engine.state.avatar.position == Pos(3, 0)


def run_all() -> bool:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  ✓ {t.__name__}")
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
