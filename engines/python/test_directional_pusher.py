"""
Tests for the `directional_pusher` system — see docs/dsl/04_systems.md §2.27.

Board used throughout (7x3), pusher `>` at (1, 1) facing right, so its only
trigger cell is (2, 1):

    . . . . . . .
    . > . . . . .
    . . . . . . .

Run from the repo root:  python3 engines/python/test_directional_pusher.py
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
        "id": "com.gridponder.test_directional_pusher",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "objects", "occupancy": "zero_or_one"},
            {"id": "actors", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"]},
            "pusher": {"layer": "objects", "tags": ["pusher", "solid"]},
            "crate": {"layer": "objects", "tags": []},
            "hazard": {"layer": "actors", "tags": ["npc", "solid"]},
        },
        "actions": [
            {"id": "move", "params": {"direction": {"type": "direction", "values": ["up", "down", "left", "right"]}}},
        ],
        "systems": [
            {"id": "navigation", "type": "avatar_navigation", "config": {}},
            {"id": "pushers", "type": "directional_pusher", "config": {
                "condition": {"variable": {"name": "load", "op": "eq", "value": 0}},
                "crashLayers": ["actors"],
                "crashVariable": "caught",
            }},
            {"id": "hazards", "type": "follower_npcs", "config": {
                "contactVariable": "caught",
                "behaviors": {"sweep": {"type": "patrol", "lethalContact": True}},
            }},
        ],
    }
    return GameDef.from_dict(data, id="test_directional_pusher")


def _level(
    avatar: tuple[int, int],
    extra_objects: list[dict] | None = None,
    load: int = 0,
    actors: list[dict] | None = None,
) -> dict:
    return {
        "id": "test_level",
        "board": {
            "size": [7, 3],
            "layers": {
                "objects": {"format": "sparse", "entries": [
                    {"position": [1, 1], "kind": "pusher", "direction": "right"},
                    *(extra_objects or []),
                ]},
                "actors": {"format": "sparse", "entries": actors or []},
            },
        },
        "state": {"avatar": {"enabled": True, "position": list(avatar)}, "variables": {"load": load, "caught": 0}},
        "goals": [],
        "loseConditions": [],
    }


def _move(level: dict, direction: str):
    engine = TurnEngine(_make_game(), level)
    result = engine.execute_turn("move", {"direction": direction})
    return engine, result


def _pushed(result) -> list[dict]:
    return [e for e in result.events if e["type"] == "avatar_pushed"]


def test_front_cell_slides_to_the_board_edge():
    engine, result = _move(_level((2, 0)), "down")
    assert result.accepted
    assert engine.state.avatar.position == Pos(6, 1), engine.state.avatar.position
    assert engine.state.avatar.facing == "right"
    pushed = _pushed(result)
    assert len(pushed) == 1, result.events
    assert pushed[0]["fromPosition"] == Pos(2, 1)
    assert pushed[0]["pusherPosition"] == Pos(1, 1)
    assert pushed[0]["distance"] == 4
    # One enter per cell: the step itself, then four slide cells.
    entered = [e["position"] for e in result.events if e["type"] == "avatar_entered"]
    assert entered == [Pos(2, 1), Pos(3, 1), Pos(4, 1), Pos(5, 1), Pos(6, 1)], entered


def test_push_costs_exactly_one_action():
    engine, _ = _move(_level((2, 0)), "down")
    assert engine.state.action_count == 1, engine.state.action_count


def test_cell_behind_the_pusher_does_nothing():
    engine, result = _move(_level((0, 0)), "down")
    assert engine.state.avatar.position == Pos(0, 1)
    assert not _pushed(result)


def test_same_row_but_not_adjacent_does_nothing():
    engine, result = _move(_level((4, 0)), "down")
    assert engine.state.avatar.position == Pos(4, 1)
    assert not _pushed(result)


def test_side_of_the_pusher_does_nothing():
    # (1, 0) is directly above the right-facing pusher, not in front of it.
    engine, result = _move(_level((0, 0)), "right")
    assert engine.state.avatar.position == Pos(1, 0)
    assert not _pushed(result)


def test_pusher_tile_itself_is_solid():
    engine, _ = _move(_level((1, 0)), "down")
    assert engine.state.avatar.position == Pos(1, 0)


def test_condition_false_disables_the_push():
    engine, result = _move(_level((2, 0), load=1), "down")
    assert engine.state.avatar.position == Pos(2, 1)
    assert not _pushed(result)


def test_stops_one_cell_short_of_a_stop_layer_entity():
    crate = {"position": [5, 1], "kind": "crate"}
    engine, _ = _move(_level((2, 0), [crate]), "down")
    assert engine.state.avatar.position == Pos(4, 1), engine.state.avatar.position


def test_blocked_immediately_emits_no_push():
    crate = {"position": [3, 1], "kind": "crate"}
    engine, result = _move(_level((2, 0), [crate]), "down")
    assert engine.state.avatar.position == Pos(2, 1)
    assert not _pushed(result)


def test_slide_does_not_chain_into_another_pusher():
    # A down-facing pusher at (6, 0) has (6, 1) as its trigger cell — exactly
    # where the first slide ends. It must not fire this turn.
    second = {"position": [6, 0], "kind": "pusher", "direction": "down"}
    engine, result = _move(_level((2, 0), [second]), "down")
    assert engine.state.avatar.position == Pos(6, 1), engine.state.avatar.position
    assert len(_pushed(result)) == 1


def test_standing_still_on_the_trigger_cell_does_nothing():
    # Bumping the pusher from its own trigger cell is a blocked move: the
    # avatar never arrives anywhere, so nothing fires.
    engine, result = _move(_level((2, 1)), "left")
    assert engine.state.avatar.position == Pos(2, 1)
    assert not _pushed(result)


def test_sliding_into_a_crash_layer_entity_is_a_crash():
    hazard = {"position": [4, 1], "kind": "hazard"}
    engine, result = _move(_level((2, 0), actors=[hazard]), "down")
    # The slide ends on the hazard's cell, not one short of it.
    assert engine.state.avatar.position == Pos(4, 1), engine.state.avatar.position
    assert engine.state.variables["caught"] == 1, engine.state.variables
    caught = [e for e in result.events if e["type"] == "avatar_caught"]
    assert len(caught) == 1 and caught[0]["position"] == Pos(4, 1), result.events


def test_hazard_leaving_the_landing_cell_is_not_a_crash():
    # The hazard sits on the slide's last cell but patrols up off it this
    # same turn: the two trucks never share a cell.
    hazard = {"position": [6, 1], "kind": "hazard", "behavior": "sweep", "facing": "up"}
    engine, result = _move(_level((2, 0), actors=[hazard]), "down")
    assert engine.state.avatar.position == Pos(6, 1), engine.state.avatar.position
    assert engine.state.variables["caught"] == 0, engine.state.variables
    assert not [e for e in result.events if e["type"] == "avatar_caught"]


def test_hazard_arriving_on_the_landing_cell_is_a_crash():
    hazard = {"position": [6, 0], "kind": "hazard", "behavior": "sweep", "facing": "down"}
    engine, result = _move(_level((2, 0), actors=[hazard]), "down")
    assert engine.state.avatar.position == Pos(6, 1), engine.state.avatar.position
    assert engine.state.variables["caught"] == 1, engine.state.variables
    assert len([e for e in result.events if e["type"] == "avatar_caught"]) == 1, result.events


def test_hazard_arriving_mid_slide_stops_the_slide_in_a_crash():
    # The hazard steps down onto (4, 1), a cell in the middle of the slide.
    hazard = {"position": [4, 0], "kind": "hazard", "behavior": "sweep", "facing": "down"}
    engine, result = _move(_level((2, 0), actors=[hazard]), "down")
    assert engine.state.avatar.position == Pos(4, 1), engine.state.avatar.position
    assert engine.state.variables["caught"] == 1, engine.state.variables


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
