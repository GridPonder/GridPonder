"""
Smoke tests for the `individual_actors` system.

Run from engines/python/:  python test_individual_actors.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine


def _make_game(config: dict | None = None) -> GameDef:
    data = {
        "id": "com.gridponder.test_individual_actors",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "actors", "occupancy": "zero_or_one"},
            {"id": "territory", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"]},
            "wall": {"layer": "ground", "tags": ["solid"]},
            "wei": {"layer": "actors", "tags": ["actor"]},
            "shu": {"layer": "actors", "tags": ["actor"]},
            "terr_wei": {"layer": "territory", "tags": ["territory"]},
            "terr_shu": {"layer": "territory", "tags": ["territory"]},
        },
        "actions": [
            {"id": "move", "params": {"direction": {"type": "direction", "values": ["up", "down", "left", "right"]}}},
            {"id": "tap_cell", "params": {"position": {"type": "position"}}},
        ],
        "systems": [
            {
                "id": "individual",
                "type": "individual_actors",
                "config": {
                    "claim": {"layer": "territory", "map": {"wei": "terr_wei", "shu": "terr_shu"}},
                    **(config or {}),
                },
            },
        ],
    }
    return GameDef.from_dict(data, id="test_individual_actors")


def _make_switch_game() -> GameDef:
    data = {
        "id": "com.gridponder.test_individual_actors_switch",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "actors", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"]},
            "wall": {"layer": "ground", "tags": ["solid"]},
            "wei": {"layer": "actors", "tags": ["actor"]},
            "shu": {"layer": "actors", "tags": ["actor"]},
        },
        "actions": [
            {"id": "move", "params": {"direction": {"type": "direction", "values": ["up", "down", "left", "right"]}}},
            {"id": "tap_cell", "params": {"position": {"type": "position"}}},
        ],
        "systems": [
            {"id": "coupled", "type": "coupled_actors", "config": {}},
            {"id": "individual", "type": "individual_actors", "enabled": False, "config": {}},
        ],
    }
    return GameDef.from_dict(data, id="test_individual_actors_switch")


def _make_level() -> dict:
    return {
        "id": "test_level",
        "board": {
            "size": [5, 1],
            "layers": {
                "ground": {"format": "sparse", "entries": []},
                "actors": {
                    "format": "sparse",
                    "entries": [
                        {"position": [1, 0], "kind": "wei"},
                        {"position": [3, 0], "kind": "shu"},
                    ],
                },
                "territory": {"format": "sparse", "entries": []},
            },
        },
        "state": {},
        "goals": [],
        "loseConditions": [],
    }


def _make_balance_budget_level() -> dict:
    return {
        "id": "test_balance_budget_level",
        "board": {
            "size": [4, 1],
            "layers": {
                "ground": {"format": "sparse", "entries": []},
                "actors": {
                    "format": "sparse",
                    "entries": [
                        {"position": [0, 0], "kind": "wei"},
                        {"position": [3, 0], "kind": "shu"},
                    ],
                },
                "territory": {
                    "format": "sparse",
                    "entries": [
                        {"position": [0, 0], "kind": "terr_wei"},
                        {"position": [3, 0], "kind": "terr_shu"},
                    ],
                },
            },
        },
        "state": {},
        "goals": [
            {
                "id": "balance_goal",
                "type": "balance",
                "config": {
                    "layer": "territory",
                    "owners": ["terr_wei", "terr_shu"],
                    "claimableLayer": "ground",
                    "claimableKind": "empty",
                    "requireComplete": True,
                    "requireEqual": True,
                },
            },
        ],
        "loseConditions": [
            {
                "type": "balance_budget_exhausted",
                "config": {"goalId": "balance_goal"},
            },
        ],
    }


def _actor_pos(engine: TurnEngine, kind: str) -> Pos | None:
    for pos, entity in engine.state.board.layers["actors"].entries():
        if entity.kind == kind:
            return pos
    return None


def _territory_kind(engine: TurnEngine, pos: Pos) -> str | None:
    entity = engine.state.board.get_entity("territory", pos)
    return entity.kind if entity else None


def test_tap_selects_actor_and_move_moves_only_selected_actor() -> None:
    game = _make_game()
    engine = TurnEngine(game, _make_level())

    selected = engine.execute_turn("tap_cell", {"position": [1, 0]})
    moved = engine.execute_turn("move", {"direction": "right"})

    assert selected.accepted
    assert moved.accepted
    assert engine.state.variables["selectedActorKind"] == "wei"
    assert _actor_pos(engine, "wei") == Pos(2, 0)
    assert _actor_pos(engine, "shu") == Pos(3, 0)
    assert _territory_kind(engine, Pos(2, 0)) == "terr_wei"
    assert [e["type"] for e in selected.events if e["type"].startswith("actor_")] == ["actor_selected"]
    assert [e["type"] for e in moved.events if e["type"].startswith("actor_")] == ["actor_moved", "actor_entered"]
    print("  OK  tap_selects_actor_and_move_moves_only_selected_actor")


def test_move_rejected_when_selected_actor_budget_is_exhausted() -> None:
    game = _make_game({"budgets": {"wei": 0, "shu": 2}})
    engine = TurnEngine(game, _make_level())

    selected = engine.execute_turn("tap_cell", {"position": [1, 0]})
    moved = engine.execute_turn("move", {"direction": "right"})

    assert selected.accepted
    assert not moved.accepted
    assert _actor_pos(engine, "wei") == Pos(1, 0)
    assert engine.state.variables["actorMovesRemaining"]["wei"] == 0
    print("  OK  move_rejected_when_selected_actor_budget_is_exhausted")


def test_selection_identifies_one_actor_when_kinds_are_duplicated() -> None:
    game = _make_game()
    level = _make_level()
    level["board"]["layers"]["actors"]["entries"] = [
        {"position": [0, 0], "kind": "wei"},
        {"position": [3, 0], "kind": "wei"},
    ]
    engine = TurnEngine(game, level)

    engine.execute_turn("tap_cell", {"position": [0, 0]})
    moved = engine.execute_turn("move", {"direction": "right"})

    assert moved.accepted
    assert engine.state.board.get_entity("actors", Pos(1, 0)).kind == "wei"
    assert engine.state.board.get_entity("actors", Pos(3, 0)).kind == "wei"
    print("  OK  selection_identifies_one_actor_when_kinds_are_duplicated")


def test_balance_budget_condition_is_inactive_without_configured_budgets() -> None:
    engine = TurnEngine(_make_game(), _make_balance_budget_level())

    result = engine.execute_turn("tap_cell", {"position": [3, 0]})

    assert result.accepted
    assert not result.is_lost
    print("  OK  balance_budget_condition_is_inactive_without_configured_budgets")


def test_explicit_empty_actor_to_owner_disables_budget_inference() -> None:
    game = _make_game({"budgets": {"wei": 0, "shu": 0}})
    level = _make_balance_budget_level()
    level["loseConditions"][0]["config"]["actorToOwner"] = {}
    engine = TurnEngine(game, level)

    result = engine.execute_turn("tap_cell", {"position": [3, 0]})

    assert result.accepted
    assert not result.is_lost
    print("  OK  explicit_empty_actor_to_owner_disables_budget_inference")


def test_balance_budget_exhausted_loses_when_actor_still_needs_claims() -> None:
    game = _make_game({"budgets": {"wei": 0, "shu": 1}})
    engine = TurnEngine(game, _make_balance_budget_level())

    result = engine.execute_turn("tap_cell", {"position": [3, 0]})

    assert result.accepted
    assert result.is_lost
    assert result.lose_reason == "balance_budget_exhausted"
    print("  OK  balance_budget_exhausted_loses_when_actor_still_needs_claims")


def test_balance_budget_exhausted_allows_actor_at_target_with_zero_budget() -> None:
    game = _make_game({"budgets": {"wei": 0, "shu": 1}})
    level = _make_balance_budget_level()
    level["board"]["layers"]["territory"]["entries"].append(
        {"position": [1, 0], "kind": "terr_wei"}
    )
    engine = TurnEngine(game, level)

    result = engine.execute_turn("tap_cell", {"position": [3, 0]})

    assert result.accepted
    assert not result.is_lost
    print("  OK  balance_budget_exhausted_allows_actor_at_target_with_zero_budget")


def test_level_overrides_can_switch_from_coupled_to_individual_movement() -> None:
    game = _make_switch_game()
    level = _make_level()
    level["systemOverrides"] = {
        "coupled": {"enabled": False},
        "individual": {"enabled": True},
    }
    engine = TurnEngine(game, level)

    engine.execute_turn("tap_cell", {"position": [1, 0]})
    moved = engine.execute_turn("move", {"direction": "right"})

    assert moved.accepted
    assert _actor_pos(engine, "wei") == Pos(2, 0)
    assert _actor_pos(engine, "shu") == Pos(3, 0)
    print("  OK  level_overrides_can_switch_from_coupled_to_individual_movement")


def _make_reactive_level() -> dict:
    return {
        "id": "test_reactive_level",
        "board": {
            "size": [7, 1],
            "layers": {
                "ground": {"format": "sparse", "entries": []},
                "actors": {
                    "format": "sparse",
                    "entries": [
                        {"position": [1, 0], "kind": "wei"},
                        {"position": [5, 0], "kind": "shu"},
                    ],
                },
                "territory": {"format": "sparse", "entries": []},
            },
        },
        "state": {},
        "goals": [],
        "loseConditions": [],
    }


def test_reactive_kinds_mirror_the_movers_direction() -> None:
    # wei is the player's piece; shu is reactive with `invert`, so a move right
    # sends shu left. The rival's step emits `actor_reacted`, never
    # `actor_moved`, so move counters keyed on player movement stay honest.
    game = _make_game({"reactiveKinds": {"shu": "invert"}})
    engine = TurnEngine(game, _make_reactive_level())

    engine.execute_turn("tap_cell", {"position": [1, 0]})
    result = engine.execute_turn("move", {"direction": "right"})

    assert result.accepted
    assert _actor_pos(engine, "wei") == Pos(2, 0)
    assert _actor_pos(engine, "shu") == Pos(4, 0)
    reacted = [e for e in result.events if e["type"] == "actor_reacted"]
    assert len(reacted) == 1, reacted
    assert reacted[0]["kind"] == "shu"
    assert reacted[0]["direction"] == "left"
    moved_kinds = {e["kind"] for e in result.events if e["type"] == "actor_moved"}
    assert moved_kinds == {"wei"}, moved_kinds
    print("  OK  reactive_kinds_mirror_the_movers_direction")


def test_reactive_actor_stays_put_when_blocked() -> None:
    # shu inverts into the wall at (6,0)'s side: a move LEFT sends shu right,
    # off the board, so it holds position and no `actor_reacted` is emitted.
    game = _make_game({"reactiveKinds": {"shu": "invert"}})
    level = _make_reactive_level()
    level["board"]["layers"]["actors"]["entries"] = [
        {"position": [1, 0], "kind": "wei"},
        {"position": [6, 0], "kind": "shu"},
    ]
    engine = TurnEngine(game, level)

    engine.execute_turn("tap_cell", {"position": [1, 0]})
    result = engine.execute_turn("move", {"direction": "left"})

    assert _actor_pos(engine, "wei") == Pos(0, 0)
    assert _actor_pos(engine, "shu") == Pos(6, 0)
    assert not [e for e in result.events if e["type"] == "actor_reacted"]
    print("  OK  reactive_actor_stays_put_when_blocked")


def test_reactive_actors_do_not_move_on_a_blocked_player_move() -> None:
    # The player walks into the board edge: no successful step, so the rival
    # does not get a free move out of a wasted attempt.
    game = _make_game({"reactiveKinds": {"shu": "invert"}})
    level = _make_reactive_level()
    level["board"]["layers"]["actors"]["entries"] = [
        {"position": [0, 0], "kind": "wei"},
        {"position": [5, 0], "kind": "shu"},
    ]
    engine = TurnEngine(game, level)

    engine.execute_turn("tap_cell", {"position": [0, 0]})
    result = engine.execute_turn("move", {"direction": "left"})

    assert _actor_pos(engine, "shu") == Pos(5, 0)
    assert not [e for e in result.events if e["type"] == "actor_reacted"]
    assert [e for e in result.events if e["type"] == "actor_blocked"]
    print("  OK  reactive_actors_do_not_move_on_a_blocked_player_move")


def run_all() -> bool:
    tests = [
        test_reactive_kinds_mirror_the_movers_direction,
        test_reactive_actor_stays_put_when_blocked,
        test_reactive_actors_do_not_move_on_a_blocked_player_move,
        test_tap_selects_actor_and_move_moves_only_selected_actor,
        test_move_rejected_when_selected_actor_budget_is_exhausted,
        test_selection_identifies_one_actor_when_kinds_are_duplicated,
        test_balance_budget_condition_is_inactive_without_configured_budgets,
        test_explicit_empty_actor_to_owner_disables_budget_inference,
        test_balance_budget_exhausted_loses_when_actor_still_needs_claims,
        test_balance_budget_exhausted_allows_actor_at_target_with_zero_budget,
        test_level_overrides_can_switch_from_coupled_to_individual_movement,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL {test.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            import traceback
            print(f"  ERROR {test.__name__}: {exc}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
