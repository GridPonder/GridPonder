"""
Behavioural tests for the `sonar` system. Builds an inline GameDef + level
(no pack files) with two diggers and two hidden seams, and drives them through
TurnEngine.

Run from the repo root:  python engines/python/test_sonar.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._turn_engine import TurnEngine


def _make_game(sonar_config: dict | None) -> GameDef:
    systems = [
        {"id": "crew", "type": "coupled_actors", "config": {}},
    ]
    if sonar_config is not None:
        systems.append({"id": "echo", "type": "sonar", "config": sonar_config})
    data = {
        "id": "com.gridponder.test_sonar",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "seams", "occupancy": "zero_or_one"},
            {"id": "actors", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty":    {"layer": "ground", "tags": ["walkable"]},
            "wall":     {"layer": "ground", "tags": ["solid"]},
            "seam_a":   {"layer": "seams", "tags": ["goal_target"]},
            "seam_b":   {"layer": "seams", "tags": ["goal_target"]},
            "seam_c":   {"layer": "seams", "tags": ["goal_target"]},
            "digger_a": {"layer": "actors", "tags": ["actor"]},
            "digger_b": {"layer": "actors", "tags": ["actor"]},
            "digger_c": {"layer": "actors", "tags": ["actor"]},
        },
        "actions": [
            {"id": "move", "params": {"direction": {"type": "direction", "values": ["up", "down", "left", "right"]}}},
        ],
        "systems": systems,
    }
    return GameDef.from_dict(data, id="test_sonar")


_PAIRED = {
    "sourceLayer": "actors",
    "targetLayer": "seams",
    "pairing": {"digger_a": "seam_a", "digger_b": "seam_b"},
}


def _make_level(actors, seams, size=(6, 3)) -> dict:
    return {
        "id": "test_level",
        "board": {
            "size": list(size),
            "layers": {
                "seams": {
                    "format": "sparse",
                    "entries": [{"position": [x, y], "kind": k} for x, y, k in seams],
                },
                "actors": {
                    "format": "sparse",
                    "entries": [{"position": [x, y], "kind": k} for x, y, k in actors],
                },
            },
        },
        "state": {},
        "goals": [],
        "loseConditions": [],
    }


def test_reading_is_written_on_the_first_turn() -> None:
    """A reading must exist after any turn, not only after the crew moves."""
    game = _make_game(_PAIRED)
    level = _make_level(actors=[(1, 1, "digger_a")], seams=[(4, 1, "seam_a")])
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    assert engine.state.variables.get("echo_digger_a") == 2, (
        f"digger at (2,1), seam at (4,1) -> 2; got {engine.state.variables}"
    )
    print("  OK  reading_is_written_on_the_first_turn")


def test_reading_shrinks_as_the_digger_approaches() -> None:
    """The whole mechanic: walking changes the reading, which is how the
    player triangulates."""
    game = _make_game(_PAIRED)
    level = _make_level(actors=[(1, 1, "digger_a")], seams=[(4, 1, "seam_a")])
    engine = TurnEngine(game, level)

    readings = []
    for _ in range(3):
        engine.execute_turn("move", {"direction": "right"})
        readings.append(engine.state.variables.get("echo_digger_a"))

    assert readings == [2, 1, 0], f"expected 2,1,0 as the digger closes; got {readings}"
    print("  OK  reading_shrinks_as_the_digger_approaches")


def test_pairing_sends_each_digger_its_own_seam() -> None:
    """Readings must be per-pair, not nearest-of-any — otherwise two diggers
    would both home on whichever seam happens to be closer."""
    game = _make_game(_PAIRED)
    level = _make_level(
        actors=[(1, 1, "digger_a"), (2, 1, "digger_b")],
        seams=[(5, 1, "seam_a"), (0, 1, "seam_b")],
    )
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    v = engine.state.variables
    # digger_a (2,1) -> seam_a (5,1) = 3;  digger_b (3,1) -> seam_b (0,1) = 3
    assert v.get("echo_digger_a") == 3, f"digger_a should read its own seam; got {v}"
    assert v.get("echo_digger_b") == 3, f"digger_b should read its own seam; got {v}"
    print("  OK  pairing_sends_each_digger_its_own_seam")


def test_reading_ignores_terrain_entirely() -> None:
    """The reading is straight-line Manhattan and deliberately says how far,
    never how to get there. That gap is the whole puzzle, so it is pinned by
    running the same geometry with and without a wall in the way and
    demanding an identical reading."""
    def read_with(walls) -> int:
        game = _make_game(_PAIRED)
        level = _make_level(actors=[(1, 1, "digger_a")], seams=[(3, 1, "seam_a")])
        if walls:
            level["board"]["layers"]["ground"] = {
                "format": "sparse",
                "entries": [{"position": [x, y], "kind": "wall"} for x, y in walls],
            }
        engine = TurnEngine(game, level)
        engine.execute_turn("move", {"direction": "down"})
        return engine.state.variables["echo_digger_a"]

    open_board = read_with([])
    walled = read_with([(2, 1), (2, 2)])

    # digger ends at (1,2); |1-3| + |2-1| = 3 either way
    assert open_board == walled == 3, (
        f"terrain must not affect the reading; open={open_board} walled={walled}"
    )
    print("  OK  reading_ignores_terrain_entirely")


def test_no_target_reads_minus_one() -> None:
    """A source with no paired target must read -1, never a stale value."""
    game = _make_game(_PAIRED)
    level = _make_level(actors=[(1, 1, "digger_b")], seams=[(4, 1, "seam_a")])
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    assert engine.state.variables.get("echo_digger_b") == -1, (
        f"digger_b has no seam_b on the board; got {engine.state.variables}"
    )
    print("  OK  no_target_reads_minus_one")


def test_unpaired_mode_reads_the_nearest_target_of_any_kind() -> None:
    game = _make_game({"sourceLayer": "actors", "targetLayer": "seams"})
    level = _make_level(
        actors=[(2, 1, "digger_a")],
        seams=[(5, 1, "seam_a"), (3, 1, "seam_b")],
    )
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "down"})

    # digger ends at (2,2); seam_b (3,1) is 2 away, seam_a (5,1) is 4
    assert engine.state.variables.get("echo_digger_a") == 2, (
        f"nearest of any kind is seam_b at distance 2; got {engine.state.variables}"
    )
    print("  OK  unpaired_mode_reads_the_nearest_target_of_any_kind")


def test_custom_variable_prefix() -> None:
    game = _make_game({**_PAIRED, "variablePrefix": "dist_"})
    level = _make_level(actors=[(1, 1, "digger_a")], seams=[(4, 1, "seam_a")])
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    assert engine.state.variables.get("dist_digger_a") == 2
    assert "echo_digger_a" not in engine.state.variables
    print("  OK  custom_variable_prefix")


def test_missing_target_layer_is_inert() -> None:
    """Tolerance contract: no targetLayer means the system writes nothing at
    all, in both engines."""
    game = _make_game({"sourceLayer": "actors"})
    level = _make_level(actors=[(1, 1, "digger_a")], seams=[(4, 1, "seam_a")])
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    assert not any(k.startswith("echo_") for k in engine.state.variables), (
        f"an inert sonar must write nothing; got {engine.state.variables}"
    )
    print("  OK  missing_target_layer_is_inert")


def test_non_object_pairing_falls_back_to_nearest() -> None:
    game = _make_game({**_PAIRED, "pairing": "digger_a:seam_a"})
    level = _make_level(
        actors=[(2, 1, "digger_a")],
        seams=[(5, 1, "seam_a"), (3, 1, "seam_b")],
    )
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "down"})

    assert engine.state.variables.get("echo_digger_a") == 2, (
        f"a malformed pairing degrades to nearest-of-any; got {engine.state.variables}"
    )
    print("  OK  non_object_pairing_falls_back_to_nearest")


def test_reading_is_a_pure_function_of_position() -> None:
    """Returning to a cell must reproduce the reading exactly — otherwise the
    variable would add spurious state and break solver dedup."""
    game = _make_game(_PAIRED)
    level = _make_level(actors=[(2, 1, "digger_a")], seams=[(5, 1, "seam_a")])
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})
    there = engine.state.variables["echo_digger_a"]
    engine.execute_turn("move", {"direction": "left"})
    engine.execute_turn("move", {"direction": "right"})
    back = engine.state.variables["echo_digger_a"]

    assert there == back == 2, f"reading must depend only on position; {there} vs {back}"
    print("  OK  reading_is_a_pure_function_of_position")


# ---------------------------------------------------------------------------
# aggregate — the crew gauge. One reading for the whole source layer.
# ---------------------------------------------------------------------------

_AGG = {**_PAIRED, "aggregate": "sum"}

# One geometry discriminates all three reductions. After a single `right`:
# digger_a (2,1) -> seam_a (3,1) = 1;  digger_b (3,1) -> seam_b (5,1) = 2.
# So sum=3, min=1, max=2 — no two reductions can be confused.
_SPLIT_ACTORS = [(1, 1, "digger_a"), (2, 1, "digger_b")]
_SPLIT_SEAMS = [(3, 1, "seam_a"), (5, 1, "seam_b")]


def test_aggregate_sum_of_two() -> None:
    game = _make_game(_AGG)
    level = _make_level(actors=_SPLIT_ACTORS, seams=_SPLIT_SEAMS)
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    assert engine.state.variables.get("echo_total") == 3, (
        f"1 + 2 = 3; got {engine.state.variables}"
    )
    print("  OK  aggregate_sum_of_two")


def test_aggregate_sum_of_three() -> None:
    """Three sources, because the crew gauge's whole point is that one number
    constrains N unknowns jointly."""
    game = _make_game({
        "sourceLayer": "actors",
        "targetLayer": "seams",
        "pairing": {"digger_a": "seam_a", "digger_b": "seam_b",
                    "digger_c": "seam_c"},
        "aggregate": "sum",
    })
    level = _make_level(
        actors=[(1, 1, "digger_a"), (2, 1, "digger_b"), (3, 1, "digger_c")],
        seams=[(6, 1, "seam_a"), (7, 1, "seam_b"), (0, 1, "seam_c")],
        size=(8, 3),
    )
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    # a(2,1)->6 = 4;  b(3,1)->7 = 4;  c(4,1)->0 = 4
    assert engine.state.variables.get("echo_total") == 12, (
        f"4 + 4 + 4 = 12; got {engine.state.variables}"
    )
    print("  OK  aggregate_sum_of_three")


def test_aggregate_min() -> None:
    game = _make_game({**_PAIRED, "aggregate": "min"})
    level = _make_level(actors=_SPLIT_ACTORS, seams=_SPLIT_SEAMS)
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    assert engine.state.variables.get("echo_total") == 1, (
        f"min(1, 2) = 1; got {engine.state.variables}"
    )
    print("  OK  aggregate_min")


def test_aggregate_max() -> None:
    game = _make_game({**_PAIRED, "aggregate": "max"})
    level = _make_level(actors=_SPLIT_ACTORS, seams=_SPLIT_SEAMS)
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    assert engine.state.variables.get("echo_total") == 2, (
        f"max(1, 2) = 2; got {engine.state.variables}"
    )
    print("  OK  aggregate_max")


def test_unrecognised_aggregate_falls_back_to_per_kind() -> None:
    """Tolerance contract: a typo must not make one engine throw while the
    other silently continues — it degrades to per-kind mode."""
    game = _make_game({**_PAIRED, "aggregate": "median"})
    level = _make_level(actors=_SPLIT_ACTORS, seams=_SPLIT_SEAMS)
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    v = engine.state.variables
    assert v.get("echo_digger_a") == 1, f"expected per-kind readings; got {v}"
    assert v.get("echo_digger_b") == 2, f"expected per-kind readings; got {v}"
    assert "echo_total" not in v, f"no aggregate should be written; got {v}"
    print("  OK  unrecognised_aggregate_falls_back_to_per_kind")


def test_sum_with_missing_target_reads_minus_one() -> None:
    """A partial sum is numerically indistinguishable from a real reading and
    would silently corrupt the player's deduction, so it must never be
    written."""
    game = _make_game(_AGG)
    level = _make_level(
        actors=_SPLIT_ACTORS,
        seams=[(3, 1, "seam_a")],       # no seam_b anywhere
    )
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    assert engine.state.variables.get("echo_total") == -1, (
        f"digger_b has no target, so the sum is unknowable; "
        f"got {engine.state.variables}"
    )
    print("  OK  sum_with_missing_target_reads_minus_one")


def test_min_skips_sources_without_targets() -> None:
    """The deliberate asymmetry with `sum`: a min over the available targets is
    a well-defined answer to the question min asks, whereas a partial sum is
    not. Both engines must pick the same side of this."""
    game = _make_game({**_PAIRED, "aggregate": "min"})
    level = _make_level(
        actors=_SPLIT_ACTORS,
        seams=[(3, 1, "seam_a")],       # no seam_b anywhere
    )
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    assert engine.state.variables.get("echo_total") == 1, (
        f"min ignores the target-less digger_b and reports 1; "
        f"got {engine.state.variables}"
    )
    print("  OK  min_skips_sources_without_targets")


def test_no_sources_reads_minus_one() -> None:
    """An empty source layer must read -1, not go unwritten. This is what
    blanks the crew chip on the levels that use the per-digger readouts."""
    game = _make_game(_AGG)
    level = _make_level(actors=[], seams=[(3, 1, "seam_a")])
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    assert engine.state.variables.get("echo_total") == -1, (
        f"no sources on the board; got {engine.state.variables}"
    )
    print("  OK  no_sources_reads_minus_one")


def test_custom_aggregate_variable() -> None:
    game = _make_game({**_PAIRED, "aggregate": "sum",
                       "aggregateVariable": "crew_total"})
    level = _make_level(actors=_SPLIT_ACTORS, seams=_SPLIT_SEAMS)
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    v = engine.state.variables
    assert v.get("crew_total") == 3, f"got {v}"
    assert "echo_total" not in v, f"default name must not also be written; {v}"
    print("  OK  custom_aggregate_variable")


def test_absent_aggregate_leaves_per_kind_behaviour_unchanged() -> None:
    """The back-compatibility guarantee that keeps the parked Echo levels
    (sp_003-sp_008, retired to spoil/levels_retired/) untouched."""
    game = _make_game(_PAIRED)
    level = _make_level(actors=_SPLIT_ACTORS, seams=_SPLIT_SEAMS)
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    v = engine.state.variables
    assert v.get("echo_digger_a") == 1, f"got {v}"
    assert v.get("echo_digger_b") == 2, f"got {v}"
    assert not any(k.endswith("total") for k in v), (
        f"no aggregate variable without an aggregate config; got {v}"
    )
    print("  OK  absent_aggregate_leaves_per_kind_behaviour_unchanged")


def test_source_kind_absent_from_pairing_is_not_sensed() -> None:
    """Two sonar instances must be able to share a source layer.

    A kind missing from a *present* pairing map is skipped entirely, not
    resolved as nearest-of-any. Without this the Spoil pack's second instance
    sensed the first instance's diggers and published a bogus crew total on
    every level of the earlier arcs.
    """
    game = _make_game({**_PAIRED, "aggregate": "sum"})
    level = _make_level(
        actors=[(1, 1, "digger_c")],            # not a key in _PAIRED
        seams=[(3, 1, "seam_a"), (5, 1, "seam_b")],
    )
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    assert engine.state.variables.get("echo_total") == -1, (
        f"digger_c is unpaired here, so this instance senses nothing; "
        f"got {engine.state.variables}"
    )
    print("  OK  source_kind_absent_from_pairing_is_not_sensed")


def test_unpaired_kind_writes_no_per_kind_variable() -> None:
    """The same rule in per-kind mode: no variable at all, not a -1 and not a
    nearest-of-any reading."""
    game = _make_game(_PAIRED)
    level = _make_level(
        actors=[(1, 1, "digger_a"), (2, 1, "digger_c")],
        seams=[(3, 1, "seam_a"), (5, 1, "seam_b")],
    )
    engine = TurnEngine(game, level)

    engine.execute_turn("move", {"direction": "right"})

    v = engine.state.variables
    assert v.get("echo_digger_a") == 1, f"paired source still reads; got {v}"
    assert "echo_digger_c" not in v, (
        f"an unpaired source must not be published at all; got {v}"
    )
    print("  OK  unpaired_kind_writes_no_per_kind_variable")


def run_all() -> bool:
    tests = [
        test_reading_is_written_on_the_first_turn,
        test_reading_shrinks_as_the_digger_approaches,
        test_pairing_sends_each_digger_its_own_seam,
        test_reading_ignores_terrain_entirely,
        test_no_target_reads_minus_one,
        test_unpaired_mode_reads_the_nearest_target_of_any_kind,
        test_custom_variable_prefix,
        test_missing_target_layer_is_inert,
        test_non_object_pairing_falls_back_to_nearest,
        test_reading_is_a_pure_function_of_position,
        test_aggregate_sum_of_two,
        test_aggregate_sum_of_three,
        test_aggregate_min,
        test_aggregate_max,
        test_unrecognised_aggregate_falls_back_to_per_kind,
        test_sum_with_missing_target_reads_minus_one,
        test_min_skips_sources_without_targets,
        test_no_sources_reads_minus_one,
        test_custom_aggregate_variable,
        test_absent_aggregate_leaves_per_kind_behaviour_unchanged,
        test_source_kind_absent_from_pairing_is_not_sensed,
        test_unpaired_kind_writes_no_per_kind_variable,
    ]
    passed = failed = 0
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
