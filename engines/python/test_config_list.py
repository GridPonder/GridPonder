"""config_list — the null-safe reader for list-valued system config.

`config.get(key, default)` returns `None` for an explicit JSON null and then
raises on the first iteration, while Dart's `?? default` treats the same JSON
as unset. The tempting `config.get(key) or default` fixes that and breaks `[]`,
which for these fields means "none of them" rather than "unset".

Run from the repo root:  python engines/python/test_config_list.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._systems._base import config_list
from engines.python._turn_engine import TurnEngine


def test_a_missing_key_takes_the_default() -> None:
    assert config_list({}, "tags", ["solid"]) == ["solid"]
    print("  OK  a_missing_key_takes_the_default")


def test_an_explicit_null_takes_the_default() -> None:
    """What `.get(key, default)` got wrong, and Dart always got right."""
    assert config_list({"tags": None}, "tags", ["solid"]) == ["solid"]
    print("  OK  an_explicit_null_takes_the_default")


def test_an_empty_list_is_kept() -> None:
    """`[]` means "none of them" — a different instruction from silence."""
    assert config_list({"tags": []}, "tags", ["solid"]) == []
    print("  OK  an_empty_list_is_kept")


def test_a_value_wins_over_the_default() -> None:
    assert config_list({"tags": ["npc"]}, "tags", ["solid"]) == ["npc"]
    print("  OK  a_value_wins_over_the_default")


def _null_config_game() -> GameDef:
    """Every list-valued field this touches, explicitly nulled."""
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
                {"id": "objects", "occupancy": "zero_or_one"},
                {"id": "actors", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "floor": {"layer": "ground", "tags": ["walkable"], "symbol": "."},
                "crate": {"layer": "objects", "tags": ["pushable", "solid"],
                          "symbol": "c"},
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
                {"id": "nav", "type": "avatar_navigation",
                 "config": {"solidHandling": "delegate", "solidLayers": None}},
                {"id": "push", "type": "push_objects",
                 "config": {"blockingLayers": None, "blockingTags": None}},
                {"id": "npcs", "type": "follower_npcs",
                 "config": {"npcTags": None, "behaviors": {}}},
            ],
            "rules": [],
        },
        id="test_config_list",
    )


def test_a_pack_full_of_nulls_still_runs() -> None:
    """The end-to-end version: this used to raise on the first turn."""
    level = {
        "id": "test_level",
        "board": {
            "size": [4, 1],
            "layers": {
                "objects": {"format": "sparse",
                            "entries": [{"position": [1, 0], "kind": "crate"}]},
            },
        },
        "state": {"avatar": {"enabled": True, "position": [0, 0]}},
        "goals": [],
        "loseConditions": [],
    }
    engine = TurnEngine(_null_config_game(), level)
    engine.execute_turn("move", {"direction": "right"})
    # The crate was pushed, so every nulled field fell back to its default.
    assert engine.state.avatar.position.x == 1, engine.state.avatar.position
    print("  OK  a_pack_full_of_nulls_still_runs")


TESTS = [
    test_a_missing_key_takes_the_default,
    test_an_explicit_null_takes_the_default,
    test_an_empty_list_is_kept,
    test_a_value_wins_over_the_default,
    test_a_pack_full_of_nulls_still_runs,
]


def run_all() -> bool:
    print("config_list tests")
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
