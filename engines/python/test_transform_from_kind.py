"""transform.fromKind — a source filter for event-driven transforms.

Conditions cannot inspect a `$event` position, only effects can read one, so
without this filter a rule keyed on an event transforms its cell blindly. That
forces every cell the rule might ever touch to be authored as the same kind.

Run from the repo root:  python engines/python/test_transform_from_kind.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine


def _game(from_kind) -> GameDef:
    effect: dict = {
        "position": "$event.position",
        "layer": "ground",
        "toKind": "void",
    }
    if from_kind is not None:
        effect["fromKind"] = from_kind
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            ],
            "entityKinds": {
                "empty": {"layer": "ground", "tags": ["walkable"], "symbol": "."},
                "cracked": {"layer": "ground", "tags": ["walkable"], "symbol": "x"},
                "rotten": {"layer": "ground", "tags": ["walkable"], "symbol": "r"},
                "void": {"layer": "ground", "tags": ["solid"], "symbol": "#"},
            },
            "actions": [
                {
                    "id": "move",
                    "params": {
                        "direction": {
                            "type": "direction",
                            "values": ["up", "down", "left", "right"],
                        }
                    },
                }
            ],
            "systems": [
                {"id": "nav", "type": "avatar_navigation", "config": {}},
            ],
            "rules": [
                {
                    "id": "give_way",
                    "on": "avatar_exited",
                    "then": [{"transform": effect}],
                }
            ],
        },
        id="test_transform_from_kind",
    )


def _level() -> dict:
    # A four-cell row: cracked, rotten, ordinary, ordinary.
    return {
        "id": "test_level",
        "board": {
            "size": [4, 1],
            "layers": {
                "ground": {
                    "format": "sparse",
                    "entries": [
                        {"position": [0, 0], "kind": "cracked"},
                        {"position": [1, 0], "kind": "rotten"},
                    ],
                }
            },
        },
        "state": {"avatar": {"enabled": True, "position": [0, 0]}},
        "goals": [],
        "loseConditions": [],
    }


def _walk_right(engine, steps: int) -> list[str]:
    for _ in range(steps):
        engine.execute_turn("move", {"direction": "right"})
    return [
        engine.state.board.get_entity("ground", Pos(x, 0)).kind
        for x in range(4)
    ]


def test_unfiltered_transform_takes_every_cell() -> None:
    """The behaviour before the filter existed, kept as the baseline."""
    engine = TurnEngine(_game(None), _level())
    assert _walk_right(engine, 3) == ["void", "void", "void", "empty"]
    print("  OK  unfiltered_transform_takes_every_cell")


def test_from_kind_spares_the_other_kinds() -> None:
    engine = TurnEngine(_game("cracked"), _level())
    # Only the cracked cell gives way; rotten and ordinary floor are untouched.
    assert _walk_right(engine, 3) == ["void", "rotten", "empty", "empty"]
    print("  OK  from_kind_spares_the_other_kinds")


def test_from_kind_accepts_a_list() -> None:
    engine = TurnEngine(_game(["cracked", "rotten"]), _level())
    assert _walk_right(engine, 3) == ["void", "void", "empty", "empty"]
    print("  OK  from_kind_accepts_a_list")


def test_a_filtered_out_transform_emits_nothing() -> None:
    """No match must mean no effect *and* no event, or cascades would fire."""
    engine = TurnEngine(_game("cracked"), _level())
    engine.execute_turn("move", {"direction": "right"})   # off cracked  → fires
    result = engine.execute_turn("move", {"direction": "right"})  # off rotten
    transformed = [e for e in result.events if e["type"] == "cell_transformed"]
    assert transformed == [], transformed
    print("  OK  a_filtered_out_transform_emits_nothing")


TESTS = [
    test_unfiltered_transform_takes_every_cell,
    test_from_kind_spares_the_other_kinds,
    test_from_kind_accepts_a_list,
    test_a_filtered_out_transform_emits_nothing,
]


def run_all() -> bool:
    print("transform.fromKind tests")
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
