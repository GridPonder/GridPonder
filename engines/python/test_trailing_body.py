"""
Tests for the `trailing_body` system's unload mechanic — see
docs/dsl/04_systems.md §2.26. Structural mid-chain splice-and-reconnect
behavior a gold path exercises implicitly (ht_009) but doesn't assert on
directly, so it's covered here against internal state instead.

Run from the repo root:  python3 engines/python/test_trailing_body.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine


def _make_game(unload_config: dict | None = None) -> GameDef:
    data = {
        "id": "com.gridponder.test_trailing_body",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "objects", "occupancy": "zero_or_one"},
            {"id": "tail", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"]},
            "pickup_item": {"layer": "objects", "tags": ["pickup"]},
            "unloader": {"layer": "objects", "tags": ["unloader"]},
        },
        "actions": [
            {"id": "move", "params": {"direction": {"type": "direction", "values": ["up", "down", "left", "right"]}}},
        ],
        "systems": [
            {"id": "navigation", "type": "avatar_navigation", "config": {}},
            {"id": "trail", "type": "trailing_body", "config": {
                "moverTag": "avatar",
                "bodyLayer": "tail",
                "growthKindSource": "objects",
                "growthTriggerTag": "pickup",
                "growthColorParam": "color",
                "segmentKindTemplate": "seg_{color}_{shape}",
                **(unload_config or {}),
            }},
        ],
    }
    return GameDef.from_dict(data, id="test_trailing_body")


def _chain_level(avatar_x: int, unloader_x: int | None, unloader_color: str = "yellow") -> dict:
    """6x1 corridor. Avatar starts at (avatar_x, 0); the caller seeds the
    chain directly onto the engine after construction (see test bodies)
    since building it up through real pickup turns isn't the point here.
    An unloader tile, when unloader_x is given, sits at (unloader_x, 0)."""
    objects_entries = []
    if unloader_x is not None:
        objects_entries.append({"position": [unloader_x, 0], "kind": "unloader", "color": unloader_color})
    return {
        "id": "test_level",
        "board": {
            "size": [6, 1],
            "layers": {
                "objects": {"format": "sparse", "entries": objects_entries},
            },
        },
        "state": {"avatar": {"enabled": True, "position": [avatar_x, 0]}},
        "goals": [],
        "loseConditions": [],
    }


def _seed_chain(engine: TurnEngine, chain: list[tuple[int, str]]) -> None:
    """Directly seeds the trailing_body system's internal segment list, as
    if `chain` (closest-to-mover first) had already been picked up over
    previous turns. `prevPos` is already the avatar's starting cell, set by
    load-settle at construction — exactly where a real closest segment
    would be adjacent to."""
    engine.state.variables["_trailingBody_trail_segments"] = [
        {"position": [x, 0], "color": color} for x, color in chain
    ]


def test_unload_splices_a_middle_segment_and_reconnects_the_rest():
    """Red(closest) -> Yellow -> Blue(farthest), straight line behind an
    avatar at x=3. Yellow's unloader sits exactly where Yellow will land
    this turn (x=2). Moving right should: remove Yellow, pull Blue forward
    into Yellow's slot (x=2), leave Red's ordinary one-cell hop (x=2->x=3)
    untouched, and leave the unloader tile itself alone (only a pack rule
    reacting to body_segment_unloaded would change it)."""
    game = _make_game({"unloadLayer": "objects"})
    level = _chain_level(avatar_x=3, unloader_x=2, unloader_color="yellow")
    engine = TurnEngine(game, level)
    _seed_chain(engine, [(2, "red"), (1, "yellow"), (0, "blue")])

    result = engine.execute_turn("move", {"direction": "right"})

    assert result.accepted, result

    unloaded = [e for e in result.events if e["type"] == "body_segment_unloaded"]
    assert len(unloaded) == 1, result.events
    assert unloaded[0]["position"] == Pos(2, 0), unloaded[0]
    assert unloaded[0]["color"] == "yellow", unloaded[0]

    segments = engine.state.variables["_trailingBody_trail_segments"]
    assert [(tuple(s["position"]), s["color"]) for s in segments] == [
        ((3, 0), "red"),
        ((2, 0), "blue"),
    ], segments

    # Red's hop is a legal one-cell slide and must animate; Blue's two-cell
    # pull (closing the gap left by Yellow) must not pretend to be one.
    moved = [e for e in result.events if e["type"] == "tile_moved"]
    assert len(moved) == 1, moved
    assert moved[0]["fromPosition"] == Pos(2, 0), moved[0]
    assert moved[0]["position"] == Pos(3, 0), moved[0]

    freed = {e["position"] for e in result.events if e["type"] == "body_segment_freed"}
    assert freed == {Pos(1, 0), Pos(0, 0)}, freed

    assert engine.state.board.get_entity("tail", Pos(3, 0)).kind == "seg_red_horizontal"
    assert engine.state.board.get_entity("tail", Pos(2, 0)).kind == "seg_blue_horizontal"
    assert engine.state.board.get_entity("tail", Pos(1, 0)) is None
    assert engine.state.board.get_entity("tail", Pos(0, 0)) is None

    # The unloader tile is untouched by the engine — only a pack rule reacting
    # to body_segment_unloaded is meant to change it.
    unloader = engine.state.board.get_entity("objects", Pos(2, 0))
    assert unloader is not None and unloader.kind == "unloader", unloader


def test_unload_requires_a_matching_color():
    """The same geometry, but the unloader at x=2 is red, not yellow — the
    yellow segment landing there must NOT be spliced out."""
    game = _make_game({"unloadLayer": "objects"})
    level = _chain_level(avatar_x=3, unloader_x=2, unloader_color="red")
    engine = TurnEngine(game, level)
    _seed_chain(engine, [(2, "red"), (1, "yellow"), (0, "blue")])

    result = engine.execute_turn("move", {"direction": "right"})

    assert not any(e["type"] == "body_segment_unloaded" for e in result.events), result.events
    segments = engine.state.variables["_trailingBody_trail_segments"]
    assert [(tuple(s["position"]), s["color"]) for s in segments] == [
        ((3, 0), "red"),
        ((2, 0), "yellow"),
        ((1, 0), "blue"),
    ], segments


def test_unloading_is_opt_in():
    """Without unloadLayer configured, a segment landing on an `unloader`-
    tagged entity is just an ordinary segment passing over an ordinary
    cell — nothing is spliced, no event fires. Confirms a pack that never
    sets unloadLayer pays nothing here."""
    game = _make_game(unload_config=None)
    level = _chain_level(avatar_x=3, unloader_x=2, unloader_color="yellow")
    engine = TurnEngine(game, level)
    _seed_chain(engine, [(2, "red"), (1, "yellow"), (0, "blue")])

    result = engine.execute_turn("move", {"direction": "right"})

    assert not any(e["type"] == "body_segment_unloaded" for e in result.events), result.events
    segments = engine.state.variables["_trailingBody_trail_segments"]
    assert len(segments) == 3, segments


TESTS = [
    test_unload_splices_a_middle_segment_and_reconnects_the_rest,
    test_unload_requires_a_matching_color,
    test_unloading_is_opt_in,
]


def run_all() -> bool:
    print("trailing_body tests")
    passed = failed = 0
    for t in TESTS:
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
