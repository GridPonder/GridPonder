"""Parity mirror of engines/dart/test/beam_system_test.dart — regression
coverage for issues raised across two rounds of review of the Mirror Laser
engine PR:
  1. Reselecting an already-aimed source must not count as an action.
     `beam`'s NPC-resolution retrace runs unconditionally every turn, so it
     must only emit beam_traced/beam_cell_revealed when the retrace actually
     changed something — not on every turn regardless — or a pure reselect
     would misreport itself as a real move. The first fix for this instead
     excluded all of NPC resolution from the selection-only check, which
     went too far: it let a selection tap "pay" for a genuine NPC-resolution
     mutation (e.g. `turn_cycle` advancing a signal every turn) for free,
     silently bypassing max_actions. See
     test_reselecting_still_costs_an_action_when_another_npc_system_mutates
     for that repro.
  2. A splitter kind with no splitterGlowKinds/splitterBlockedKinds
     configured must show no marker on its blocked side, not fall back to a
     generic wall-hit marker as if it weren't a splitter at all.
  3. Firing must revalidate sourceTags on the stored source cell, not just
     check it's non-empty, before writing a facing param onto it.
  4. Reflector/splitter redirects must be cardinal-only — including a
     source's own level-authored initial facing, not just fire-action/
     redirect directions.

Run from the repo root:  python engines/python/test_beam.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._turn_engine import TurnEngine
from engines.python._models import Pos, Entity


def _make_game() -> GameDef:
    beam_config = {
        "selectAction": "tap_cell",
        "sourceLayer": "objects",
        "sourceTags": ["beam_source"],
        "facingParam": "facing",
        "blockingLayers": ["ground"],
        "blockingTags": ["solid"],
        "targetTags": ["goal_target"],
        "hazardTags": ["hazard"],
        "reflectors": {
            # Deliberately invalid: a reflector map may only redirect
            # cardinally.
            "mirror_diag": {"right": "up_left"},
        },
        "splitters": {
            # No splitterGlowKinds/splitterBlockedKinds configured for this
            # kind at all — its blocked side must still show no marker.
            "splitter_plain": {"right": ["right", "down"]},
            # One cardinal branch, one deliberately invalid diagonal branch.
            "splitter_diag": {"right": ["right", "up_left"]},
        },
        "hitVariable": "beamHitTarget",
        "hazardVariable": "beamHitHazard",
        "pathLayer": "markers",
        "pathKind": "seg_default",
        "blockedKinds": {
            "up": "blocked_generic",
            "down": "blocked_generic",
            "left": "blocked_generic",
            "right": "blocked_generic",
        },
        "intersectionKind": "intersection_generic",
        "splitterIntersectionKinds": {
            "splitter_plain": "intersection_splitter_plain",
        },
        "maxSteps": 50,
    }

    data = {
        "id": "com.gridponder.test_beam",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
            {"id": "objects", "occupancy": "zero_or_one"},
            {"id": "markers", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "floor": {"layer": "ground", "tags": ["walkable"]},
            "wall": {"layer": "ground", "tags": ["solid"]},
            "target": {"layer": "ground", "tags": ["goal_target"]},
            "mirror_diag": {"layer": "ground", "tags": ["reflector"]},
            "splitter_plain": {"layer": "ground", "tags": ["divider"]},
            "splitter_diag": {"layer": "ground", "tags": ["divider"]},
            "source": {"layer": "objects", "tags": ["beam_source"]},
            "decoy": {"layer": "objects", "tags": []},
            # Cycled by turn_cycle below — a stand-in for any NPC-resolution
            # system whose effect is genuine gameplay state, not decoration.
            "signal_a": {"layer": "markers", "tags": []},
            "signal_b": {"layer": "markers", "tags": []},
        },
        "actions": [
            {"id": "tap_cell", "params": {"position": {"type": "position"}}},
            {"id": "fire_up", "params": {}},
            {"id": "fire_down", "params": {}},
            {"id": "fire_left", "params": {}},
            {"id": "fire_right", "params": {}},
        ],
        "systems": [
            {"id": "beam", "type": "beam", "config": beam_config},
            # No triggerActions configured: advances every turn regardless
            # of the action, the same "unconditional every turn" shape as
            # beam's own retrace — but unlike beam, every advance is a real
            # mutation. A no-op everywhere no signal_a/signal_b entity is
            # placed, so this is inert for every other test in this file.
            {
                "id": "signal_cycle",
                "type": "turn_cycle",
                "config": {
                    "layer": "markers",
                    "cycles": {"signal_a": "signal_b", "signal_b": "signal_a"},
                },
            },
        ],
    }
    return GameDef.from_dict(data, id="test_beam")


def _make_level(
    ground: list[list] | None = None,
    objects: list[list] | None = None,
    markers: list[list] | None = None,
    size: list[int] | None = None,
    lose_conditions: list[dict] | None = None,
) -> dict:
    ground = ground or []
    objects = objects or []
    markers = markers or []
    return {
        "id": "test_level",
        "board": {
            "size": size or [6, 6],
            "layers": {
                "ground": {
                    "format": "sparse",
                    "entries": [
                        {"position": [g[0], g[1]], "kind": g[2]} for g in ground
                    ],
                },
                "objects": {
                    "format": "sparse",
                    "entries": [
                        {
                            "position": [o[0], o[1]],
                            "kind": o[2],
                            **({"facing": o[3]} if len(o) > 3 else {}),
                        }
                        for o in objects
                    ],
                },
                "markers": {
                    "format": "sparse",
                    "entries": [
                        {"position": [m[0], m[1]], "kind": m[2]} for m in markers
                    ],
                },
            },
        },
        "state": {"variables": {}},
        "goals": [],
        "loseConditions": lose_conditions or [],
    }


def _engine_for(game: GameDef, level: dict) -> TurnEngine:
    return TurnEngine(game, level)


def _tap(x: int, y: int) -> tuple[str, dict]:
    return ("tap_cell", {"position": [x, y]})


def _fire(direction: str) -> tuple[str, dict]:
    return (f"fire_{direction}", {})


def test_reselecting_an_already_aimed_source_does_not_count_as_an_action():
    engine = _engine_for(_make_game(), _make_level(objects=[[0, 0, "source"]]))

    engine.execute_turn(*_tap(0, 0))
    assert engine.state.action_count == 0, "pure selection is free"

    engine.execute_turn(*_fire("right"))
    assert engine.state.action_count == 1, "firing is a real action"

    engine.execute_turn(*_tap(0, 0))
    assert engine.state.action_count == 1, (
        "reselecting the same, already-firing source must stay free — its "
        "beam retrace reruns every turn, but the trace is identical to "
        "what is already on the board, so it must not re-emit "
        "beam_traced/beam_cell_revealed for cells that have not actually "
        "changed"
    )


def test_reselecting_still_costs_an_action_when_another_npc_system_mutates():
    engine = _engine_for(
        _make_game(),
        _make_level(
            objects=[[0, 0, "source"]],
            # turn_cycle's config above has no triggerActions, so it
            # advances this every single turn regardless of the action —
            # the same "unconditional every turn" shape as beam's own
            # retrace, but unlike beam this is a genuine mutation every
            # time it runs.
            markers=[[3, 3, "signal_a"]],
        ),
    )

    engine.execute_turn(*_tap(0, 0))
    assert engine.state.action_count == 1, (
        "a selection tap must not get turn_cycle's genuine per-turn "
        "mutation for free just because beam's own passive retrace is "
        "correctly excluded"
    )
    entity = engine.state.board.get_entity("markers", Pos(3, 3))
    assert entity is not None and entity.kind == "signal_b", (
        "the cycle really did advance this turn"
    )

    engine.execute_turn(*_tap(0, 0))
    assert engine.state.action_count == 2, (
        "and it keeps costing an action on every subsequent reselect, "
        "since the signal keeps genuinely advancing"
    )


def test_reselecting_does_not_trip_a_max_actions_loss_early():
    engine = _engine_for(
        _make_game(),
        _make_level(
            objects=[[0, 0, "source"]],
            lose_conditions=[{"type": "max_actions", "config": {"limit": 2}}],
        ),
    )

    engine.execute_turn(*_tap(0, 0))
    first_fire = engine.execute_turn(*_fire("right"))
    assert first_fire.is_lost is False
    assert engine.state.action_count == 1

    reselect = engine.execute_turn(*_tap(0, 0))
    assert reselect.is_lost is False, (
        "a free reselect must not push action_count over the limit on its own"
    )
    assert engine.state.action_count == 1

    second_fire = engine.execute_turn(*_fire("right"))
    assert engine.state.action_count == 2
    assert second_fire.is_lost is True, "the second genuine fire really does reach the limit"


def test_splitter_with_no_glow_config_paints_no_marker_on_its_blocked_side():
    engine = _engine_for(
        _make_game(),
        _make_level(
            ground=[[2, 0, "splitter_plain"]],
            objects=[[2, 1, "source", "up"]],
        ),
    )

    # Any turn triggers the retrace; the source's facing is already set in
    # the level itself, so no select/fire is needed to exercise it.
    engine.execute_turn(*_tap(5, 5))

    assert engine.state.board.get_entity("markers", Pos(2, 0)) is None, (
        'splitter_plain only maps its "right" approach — entering from '
        '"up" is its solid, unmapped side, and with no splitterGlowKinds/'
        "splitterBlockedKinds configured at all it must show no marker, "
        "not fall back to blockedKinds or pathKind as if it were a plain "
        "wall"
    )


def test_splitter_self_intersection_paints_splitter_specific_marker():
    engine = _engine_for(
        _make_game(),
        _make_level(
            ground=[[2, 2, "splitter_plain"]],
            objects=[
                [1, 2, "source", "right"],
                [3, 2, "source", "left"],
            ],
        ),
    )

    engine.execute_turn(*_tap(5, 5))

    entity = engine.state.board.get_entity("markers", Pos(2, 2))
    assert entity is not None and entity.kind == "intersection_splitter_plain", (
        "a genuine self-intersection landing on a splitter must prefer "
        "splitterIntersectionKinds for that entity kind over the generic "
        "intersectionKind, so the player can tell a divider was re-entered "
        "rather than two plain beams just crossing"
    )


def test_plain_segment_self_intersection_uses_generic_marker():
    engine = _engine_for(
        _make_game(),
        _make_level(
            objects=[
                [1, 2, "source", "right"],
                [3, 2, "source", "left"],
            ],
        ),
    )

    engine.execute_turn(*_tap(5, 5))

    entity = engine.state.board.get_entity("markers", Pos(2, 2))
    assert entity is not None and entity.kind == "intersection_generic", (
        "with no splitter involved, splitterIntersectionKinds has nothing "
        "to match, so the collision falls back to the plain intersectionKind "
        "exactly as before"
    )


def test_firing_ignores_a_selected_cell_after_it_stops_holding_a_source():
    engine = _engine_for(_make_game(), _make_level(objects=[[0, 0, "source"]]))

    engine.execute_turn(*_tap(0, 0))

    # Simulate another mechanism replacing the entity at the selected
    # position between selection and firing — beam has no such mechanism of
    # its own, so this pokes the board directly the way any other system
    # would.
    engine.state.board.set_entity("objects", Pos(0, 0), Entity("decoy", {}))

    result = engine.execute_turn(*_fire("right"))

    assert not any(e["type"] == "beam_aimed" for e in result.events), (
        "firing onto a cell that no longer holds a beam_source must be a no-op"
    )
    entity = engine.state.board.get_entity("objects", Pos(0, 0))
    assert entity.params == {}, (
        "the replacement entity must not have a facing param written onto it"
    )


def test_level_authored_diagonal_source_facing_is_never_traced():
    engine = _engine_for(
        _make_game(),
        # No fire action involved at all — mirror_diag isn't even needed;
        # this facing is set directly in the level's initial board state,
        # the same way a level can author any other starting param.
        _make_level(objects=[[0, 0, "source", "up_left"]]),
    )

    engine.execute_turn(*_tap(5, 5))

    layer = engine.state.board.layers.get("markers")
    assert layer is not None and not list(layer.entries()), (
        "a source facing diagonally must never be traced at all — a "
        "source only ever gets a cardinal facing through fire_*, but a "
        "level can author the initial facing directly and bypass that"
    )


def test_reflector_with_a_diagonal_redirect_ends_the_trace():
    engine = _engine_for(
        _make_game(),
        _make_level(
            ground=[[2, 2, "mirror_diag"]],
            objects=[[0, 2, "source", "right"]],
        ),
    )

    engine.execute_turn(*_tap(5, 5))

    assert engine.state.board.get_entity("markers", Pos(1, 1)) is None, (
        'mirror_diag maps an incoming "right" beam to "up_left" — a '
        "diagonal the engine must reject rather than silently stepping "
        "off at an angle"
    )


def test_splitter_branch_with_a_diagonal_direction_dead_ends_at_the_splitter():
    engine = _engine_for(
        _make_game(),
        _make_level(
            ground=[[2, 2, "splitter_diag"]],
            objects=[[0, 2, "source", "right"]],
        ),
    )

    engine.execute_turn(*_tap(5, 5))

    assert engine.state.board.get_entity("markers", Pos(3, 2)) is not None, (
        'the cardinal "right" branch should still trace normally'
    )
    assert engine.state.board.get_entity("markers", Pos(1, 1)) is None, (
        'the diagonal "up_left" branch must not step off at an angle'
    )


def run_all() -> bool:
    tests = [
        test_reselecting_an_already_aimed_source_does_not_count_as_an_action,
        test_reselecting_still_costs_an_action_when_another_npc_system_mutates,
        test_reselecting_does_not_trip_a_max_actions_loss_early,
        test_splitter_with_no_glow_config_paints_no_marker_on_its_blocked_side,
        test_splitter_self_intersection_paints_splitter_specific_marker,
        test_plain_segment_self_intersection_uses_generic_marker,
        test_firing_ignores_a_selected_cell_after_it_stops_holding_a_source,
        test_level_authored_diagonal_source_facing_is_never_traced,
        test_reflector_with_a_diagonal_redirect_ends_the_trace,
        test_splitter_branch_with_a_diagonal_direction_dead_ends_at_the_splitter,
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
