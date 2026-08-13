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


def _make_taped_game(program: list[str], cycle: bool = False) -> GameDef:
    """A coupled_actors game whose direction comes from a tape, not the action."""
    data = {
        "id": "com.gridponder.test_coupled_actors_tape",
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
            {"id": "step", "params": {}},
        ],
        "systems": [
            {"id": "movement", "type": "coupled_actors",
             "config": {"tape": {"program": program, "cycle": cycle}}},
        ],
    }
    return GameDef.from_dict(data, id="test_coupled_actors_tape")


def _actor_pos(engine: TurnEngine, kind: str) -> Pos | None:
    for pos, entity in engine.state.board.layers["actors"].entries():
        if entity.kind == kind:
            return pos
    return None


def _actor_events(result) -> list[dict]:
    return [e for e in result.events if e["type"].startswith("actor_")]


# ---------------------------------------------------------------------------
# Claiming fixtures (territory layer + `claim` system config)
# ---------------------------------------------------------------------------

def _make_claim_game() -> GameDef:
    data = {
        "id": "com.gridponder.test_coupled_actors_claim",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "actors", "occupancy": "zero_or_one"},
            {"id": "territory", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"]},
            "wall":  {"layer": "ground", "tags": ["solid"]},
            "wei":   {"layer": "actors", "tags": ["actor"]},
            "shu":   {"layer": "actors", "tags": ["actor"]},
            "terr_wei": {"layer": "territory", "tags": ["territory"]},
            "terr_shu": {"layer": "territory", "tags": ["territory"]},
        },
        "actions": [
            {"id": "move", "params": {"direction": {"type": "direction", "values": ["up", "down", "left", "right"]}}},
        ],
        "systems": [
            {"id": "movement", "type": "coupled_actors", "config": {
                "claim": {"layer": "territory", "map": {"wei": "terr_wei", "shu": "terr_shu"}},
            }},
        ],
    }
    return GameDef.from_dict(data, id="test_coupled_actors_claim")


def _make_claim_level(
    actors: list[tuple[int, int, str]],
    walls: list[tuple[int, int]],
    territory: list[tuple[int, int, str]] | None = None,
    width: int = 6,
) -> dict:
    level = _make_level(actors, walls, width)
    level["board"]["layers"]["territory"] = {
        "format": "sparse",
        "entries": [{"position": [x, y], "kind": kind} for x, y, kind in (territory or [])],
    }
    return level


def _territory_kind(engine: TurnEngine, pos: Pos) -> str | None:
    entity = engine.state.board.get_entity("territory", pos)
    return entity.kind if entity else None


def _claim_events(result) -> list[dict]:
    return [e for e in result.events if e["type"] == "cell_claimed"]


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


def test_claim_marks_fresh_destination_cells_for_each_mover() -> None:
    """When `claim` is configured, each actor that successfully moves claims
    its destination cell in the territory layer using the kind mapped from
    its own kind — as long as the cell was previously unclaimed."""
    game = _make_claim_game()
    level = _make_claim_level(actors=[(1, 0, "wei"), (4, 0, "shu")], walls=[])
    engine = TurnEngine(game, level)

    result = engine.execute_turn("move", {"direction": "right"})

    assert result.accepted
    assert _territory_kind(engine, Pos(2, 0)) == "terr_wei", "wei's destination should be claimed for wei"
    assert _territory_kind(engine, Pos(5, 0)) == "terr_shu", "shu's destination should be claimed for shu"

    claims = _claim_events(result)
    assert len(claims) == 2, f"expected two cell_claimed events, got {claims}"
    by_owner = {e["ownerKind"]: e for e in claims}
    assert by_owner["wei"]["position"] == Pos(2, 0) and by_owner["wei"]["kind"] == "terr_wei"
    assert by_owner["shu"]["position"] == Pos(5, 0) and by_owner["shu"]["kind"] == "terr_shu"
    assert all(e["layer"] == "territory" for e in claims), f"expected layer='territory' on every claim, got {claims}"
    print("  OK  claim_marks_fresh_destination_cells_for_each_mover")


def test_claim_does_not_overwrite_already_owned_cell() -> None:
    """A territory cell already owned by one kingdom must survive being
    walked over by the other kingdom's actor: claiming never overwrites."""
    game = _make_claim_game()
    # (3,0) is already owned by wei's territory. shu (front actor) trains
    # onto it while wei (trailing) moves into shu's vacated, unclaimed cell.
    level = _make_claim_level(
        actors=[(1, 0, "wei"), (2, 0, "shu")],
        walls=[],
        territory=[(3, 0, "terr_wei")],
    )
    engine = TurnEngine(game, level)

    result = engine.execute_turn("move", {"direction": "right"})

    assert result.accepted
    assert _actor_pos(engine, "shu") == Pos(3, 0)
    assert _actor_pos(engine, "wei") == Pos(2, 0)

    assert _territory_kind(engine, Pos(3, 0)) == "terr_wei", "pre-owned cell must not be overwritten by shu"
    assert _territory_kind(engine, Pos(2, 0)) == "terr_wei", "wei's fresh destination should be claimed for wei"

    claims = _claim_events(result)
    assert len(claims) == 1, f"expected exactly one cell_claimed event (only the fresh claim), got {claims}"
    assert claims[0]["ownerKind"] == "wei" and claims[0]["position"] == Pos(2, 0) and claims[0]["kind"] == "terr_wei"
    print("  OK  claim_does_not_overwrite_already_owned_cell")


def test_claim_not_applied_to_blocked_actor() -> None:
    """Claiming only happens on successful moves — a blocked actor keeps its
    old cell and must not trigger any claim (there is no new destination)."""
    game = _make_claim_game()
    level = _make_claim_level(actors=[(2, 0, "shu")], walls=[(3, 0)])
    engine = TurnEngine(game, level)

    result = engine.execute_turn("move", {"direction": "right"})

    assert result.accepted
    assert _actor_pos(engine, "shu") == Pos(2, 0), "shu should stay in place (wall ahead)"
    assert _territory_kind(engine, Pos(2, 0)) is None, "no claim should be made for a blocked actor"
    assert _territory_kind(engine, Pos(3, 0)) is None, "wall cell was never a move destination, so no claim"
    assert _claim_events(result) == [], "blocked actor must not emit cell_claimed"
    print("  OK  claim_not_applied_to_blocked_actor")


# ---------------------------------------------------------------------------
# Tape tests — tape-driven movement
# ---------------------------------------------------------------------------

def test_tape_overrides_the_action_direction():
    game = _make_taped_game(["right"])
    engine = TurnEngine(game, _make_level([(0, 0, "wei")], []))
    engine.execute_turn("move", {"direction": "left"})
    assert engine.state.board.get_entity("actors", Pos(1, 0)) is not None, \
        "the tape's direction must win over the action's direction"
    assert engine.state.variables["tapeIndex"] == 1


def test_tape_advances_on_a_param_less_action():
    game = _make_taped_game(["right", "right"])
    engine = TurnEngine(game, _make_level([(0, 0, "wei")], []))
    engine.execute_turn("step")
    engine.execute_turn("step")
    assert engine.state.board.get_entity("actors", Pos(2, 0)) is not None, \
        "a tape steps the world on any accepted action, not just `move`"
    assert engine.state.variables["tapeIndex"] == 2


def test_finite_tape_stops_when_exhausted():
    game = _make_taped_game(["right"], cycle=False)
    engine = TurnEngine(game, _make_level([(0, 0, "wei")], []))
    engine.execute_turn("step")
    engine.execute_turn("step")
    assert engine.state.board.get_entity("actors", Pos(1, 0)) is not None, \
        "an exhausted finite tape must not keep stepping"
    assert engine.state.variables["tapeIndex"] == 1


def test_cyclic_tape_wraps_and_keeps_the_index_bounded():
    game = _make_taped_game(["right", "left"], cycle=True)
    engine = TurnEngine(game, _make_level([(0, 0, "wei")], []))
    for _ in range(5):
        engine.execute_turn("step")
    # right, left, right, left, right -> one cell along
    assert engine.state.board.get_entity("actors", Pos(1, 0)) is not None
    assert engine.state.variables["tapeIndex"] == 1, \
        "a cyclic index must stay bounded by the programme length"


# ---------------------------------------------------------------------------
# directionTransforms (DSL 0.8) — per-actor direction mapping
# ---------------------------------------------------------------------------

def _make_game_with_transforms(transforms: dict) -> GameDef:
    """A fresh GameDef whose `movement` system carries `directionTransforms`.

    Built per-call (not mutated in place) so tests can't leak config into
    each other.
    """
    game = _make_game()
    for s in game.systems:
        if s["id"] == "movement":
            s.setdefault("config", {})["directionTransforms"] = transforms
    return game


def test_identity_transforms_match_legacy_order() -> None:
    """COMPATIBILITY GUARANTEE: an explicit all-identity config must behave
    exactly like no config at all — one bucket, unchanged front-first sort."""
    results = []
    for game in (_make_game(),
                 _make_game_with_transforms({"wei": "identity", "shu": "identity"})):
        level = _make_level(actors=[(1, 0, "wei"), (2, 0, "shu")], walls=[])
        engine = TurnEngine(game, level)
        engine.execute_turn("move", {"direction": "right"})
        results.append({
            "wei": _actor_pos(engine, "wei"),
            "shu": _actor_pos(engine, "shu"),
        })

    assert results[0] == results[1], (
        f"identity transforms diverged from legacy behaviour: {results[0]} vs {results[1]}"
    )
    print("  OK  identity_transforms_match_legacy_order")


def test_invert_moves_actor_opposite() -> None:
    """One order, two directions: wei steps right, shu (inverted) steps left.

    Starts are 1 and 4 so the two never contend for the same destination —
    they converge to 2 and 3, staying distinct.
    """
    game = _make_game_with_transforms({"shu": "invert"})
    level = _make_level(actors=[(1, 0, "wei"), (4, 0, "shu")], walls=[])
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    assert _actor_pos(engine, "wei") == Pos(2, 0), (
        f"wei should step right to (2,0), got {_actor_pos(engine, 'wei')}"
    )
    assert _actor_pos(engine, "shu") == Pos(3, 0), (
        f"shu (inverted) should step left to (3,0), got {_actor_pos(engine, 'shu')}"
    )
    print("  OK  invert_moves_actor_opposite")


def test_inverted_actors_swapping_cells_both_block() -> None:
    """Mutual swap: wei at 2 moving right, shu at 3 inverted moving left. Each
    targets the other's occupied cell, so both stay put. Falls out of the live
    `occupied` set — no special case needed."""
    game = _make_game_with_transforms({"shu": "invert"})
    level = _make_level(actors=[(2, 0, "wei"), (3, 0, "shu")], walls=[])
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    assert _actor_pos(engine, "wei") == Pos(2, 0), (
        f"wei must stay at (2,0) in a mutual swap, got {_actor_pos(engine, 'wei')}"
    )
    assert _actor_pos(engine, "shu") == Pos(3, 0), (
        f"shu must stay at (3,0) in a mutual swap, got {_actor_pos(engine, 'shu')}"
    )
    print("  OK  inverted_actors_swapping_cells_both_block")


def run_all() -> bool:
    tests = [
        test_open_move_shifts_and_trains_both_actors,
        test_wall_blocks_one_actor_while_other_moves,
        test_wall_blocks_front_actor_and_traps_trailing_actor,
        test_out_of_bounds_blocks_actor_at_edge,
        test_claim_marks_fresh_destination_cells_for_each_mover,
        test_claim_does_not_overwrite_already_owned_cell,
        test_claim_not_applied_to_blocked_actor,
        test_tape_overrides_the_action_direction,
        test_tape_advances_on_a_param_less_action,
        test_finite_tape_stops_when_exhausted,
        test_cyclic_tape_wraps_and_keeps_the_index_bounded,
        test_identity_transforms_match_legacy_order,
        test_invert_moves_actor_opposite,
        test_inverted_actors_swapping_cells_both_block,
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
