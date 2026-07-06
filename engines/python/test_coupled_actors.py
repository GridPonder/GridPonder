"""
Smoke test for the `coupled_actors` system (movement only — no territory
claiming). Builds an inline GameDef + level (no pack files) with two actors,
`wei` and `shu`, on a 1-row board, and drives them through TurnEngine.

Run from engines/python/:  python test_coupled_actors.py
"""
from __future__ import annotations
import sys
from pathlib import Path

# Make engines/ importable
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._turn_engine import TurnEngine
from engines.python._models import Pos


def _make_game() -> GameDef:
    data = {
        "id": "com.gridponder.test_coupled_actors",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "actors", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"]},
            "wall":  {"layer": "ground", "tags": ["solid"]},
            "wei":   {"layer": "actors", "tags": ["actor"]},
            "shu":   {"layer": "actors", "tags": ["actor"]},
        },
        "actions": [
            {"id": "move", "params": {"direction": {"type": "direction", "values": ["up", "down", "left", "right"]}}},
        ],
        "systems": [
            {"id": "movement", "type": "coupled_actors", "config": {}},
        ],
    }
    return GameDef.from_dict(data, id="test_coupled_actors")


def _make_level(actors: list[tuple[int, int, str]], walls: list[tuple[int, int]], width: int = 6) -> dict:
    """actors: list of (x, y, kind); walls: list of (x, y) ground wall cells."""
    return {
        "id": "test_level",
        "board": {
            "size": [width, 1],
            "layers": {
                "ground": {
                    "format": "sparse",
                    "entries": [{"position": [x, y], "kind": "wall"} for x, y in walls],
                },
                "actors": {
                    "format": "sparse",
                    "entries": [{"position": [x, y], "kind": kind} for x, y, kind in actors],
                },
            },
        },
        "state": {},
        "goals": [],
        "loseConditions": [],
    }


def _actor_pos(engine: TurnEngine, kind: str) -> Pos | None:
    for pos, entity in engine.state.board.layers["actors"].entries():
        if entity.kind == kind:
            return pos
    return None


def _actor_events(result) -> list[dict]:
    return [e for e in result.events if e["type"].startswith("actor_")]


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_open_move_shifts_and_trains_both_actors() -> None:
    """Clear board: both actors shift one cell; the trailing actor (wei)
    trains into the cell the front actor (shu) just vacated."""
    game = _make_game()
    level = _make_level(actors=[(1, 0, "wei"), (2, 0, "shu")], walls=[])
    engine = TurnEngine(game, level)

    result = engine.execute_turn("move", {"direction": "right"})

    assert result.accepted, "move action should be accepted"
    assert _actor_pos(engine, "shu") == Pos(3, 0), (
        f"shu (front) should shift to (3,0), got {_actor_pos(engine, 'shu')}"
    )
    assert _actor_pos(engine, "wei") == Pos(2, 0), (
        f"wei (trailing) should train into shu's vacated cell (2,0), got {_actor_pos(engine, 'wei')}"
    )

    events = _actor_events(result)
    types = [e["type"] for e in events]
    assert types == ["actor_moved", "actor_entered", "actor_moved", "actor_entered"], (
        f"expected moved/entered pairs, front-first, got {types}"
    )
    # front-first resolution: shu (x=2, ahead in the travel direction) resolves before wei (x=1)
    assert events[0]["kind"] == "shu" and events[2]["kind"] == "wei", (
        f"front actor (shu) must resolve before trailing actor (wei), got order {[e['kind'] for e in events if e['type'] == 'actor_moved']}"
    )
    assert events[0]["fromPosition"] == Pos(2, 0) and events[0]["position"] == Pos(3, 0)
    assert events[2]["fromPosition"] == Pos(1, 0) and events[2]["position"] == Pos(2, 0)
    print("  OK  open_move_shifts_and_trains_both_actors")


def test_wall_blocks_one_actor_while_other_moves() -> None:
    """A wall stops only the actor in front of it; an unrelated actor
    elsewhere on the board still moves normally (blocked-stays asymmetry)."""
    game = _make_game()
    # wei is far from the wall and moves freely; shu is blocked by a wall.
    level = _make_level(actors=[(0, 0, "wei"), (2, 0, "shu")], walls=[(3, 0)])
    engine = TurnEngine(game, level)

    result = engine.execute_turn("move", {"direction": "right"})

    assert result.accepted
    assert _actor_pos(engine, "wei") == Pos(1, 0), f"wei should move freely to (1,0), got {_actor_pos(engine, 'wei')}"
    assert _actor_pos(engine, "shu") == Pos(2, 0), f"shu should stay at (2,0) (wall ahead), got {_actor_pos(engine, 'shu')}"

    events = _actor_events(result)
    blocked = [e for e in events if e["type"] == "actor_blocked"]
    moved = [e for e in events if e["type"] == "actor_moved"]
    assert len(blocked) == 1 and blocked[0]["kind"] == "shu" and blocked[0]["position"] == Pos(2, 0), (
        f"expected exactly one actor_blocked for shu at (2,0), got {blocked}"
    )
    assert len(moved) == 1 and moved[0]["kind"] == "wei", f"expected exactly one actor_moved for wei, got {moved}"
    print("  OK  wall_blocks_one_actor_while_other_moves")


def test_wall_blocks_front_actor_and_traps_trailing_actor() -> None:
    """Two adjacent actors, wall right in front of the leader: the leader
    stays (wall), and the trailing actor's target cell never frees up, so it
    stays too — no cell sharing, no phantom move."""
    game = _make_game()
    level = _make_level(actors=[(2, 0, "wei"), (3, 0, "shu")], walls=[(4, 0)])
    engine = TurnEngine(game, level)

    result = engine.execute_turn("move", {"direction": "right"})

    assert result.accepted
    assert _actor_pos(engine, "shu") == Pos(3, 0), f"shu (front) should stay at (3,0), got {_actor_pos(engine, 'shu')}"
    assert _actor_pos(engine, "wei") == Pos(2, 0), f"wei (trailing) should stay at (2,0), got {_actor_pos(engine, 'wei')}"

    events = _actor_events(result)
    assert all(e["type"] == "actor_blocked" for e in events), f"expected only actor_blocked events, got {events}"
    kinds = {e["kind"] for e in events}
    assert kinds == {"wei", "shu"}, f"expected both actors blocked, got {kinds}"
    print("  OK  wall_blocks_front_actor_and_traps_trailing_actor")


def test_out_of_bounds_blocks_actor_at_edge() -> None:
    """The board edge blocks movement just like a wall would, with no wall
    entity required."""
    game = _make_game()
    level = _make_level(actors=[(3, 0, "wei"), (4, 0, "shu")], walls=[], width=5)
    engine = TurnEngine(game, level)

    result = engine.execute_turn("move", {"direction": "right"})

    assert result.accepted
    assert _actor_pos(engine, "shu") == Pos(4, 0), f"shu should stay at the edge (4,0), got {_actor_pos(engine, 'shu')}"
    assert _actor_pos(engine, "wei") == Pos(3, 0), f"wei should stay behind shu (3,0), got {_actor_pos(engine, 'wei')}"

    events = _actor_events(result)
    assert len(events) == 2, f"expected exactly two actor_blocked events, got {events}"
    assert all(e["type"] == "actor_blocked" for e in events), f"expected only actor_blocked events, got {events}"
    print("  OK  out_of_bounds_blocks_actor_at_edge")


def run_all() -> bool:
    tests = [
        test_open_move_shifts_and_trains_both_actors,
        test_wall_blocks_one_actor_while_other_moves,
        test_wall_blocks_front_actor_and_traps_trailing_actor,
        test_out_of_bounds_blocks_actor_at_edge,
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
