from __future__ import annotations

import unittest
from pathlib import Path

import engine_adapter as ea
import solve


FIXTURE_PACK = (
    Path(__file__).resolve().parents[2]
    / "engines"
    / "python"
    / "_fixtures"
    / "actor_balance_smoke"
)


def _level(*, individual: bool) -> dict:
    return {
        "id": "actor_balance_solver_smoke",
        "board": {
            "size": [3, 2],
            "layers": {
                "actors": {
                    "format": "sparse",
                    "entries": [
                        {"position": [0, 0], "kind": "actor_a"},
                        {"position": [2, 1], "kind": "actor_b"},
                    ],
                },
            },
        },
        "state": {},
        "systemOverrides": {
            "movement": {"enabled": not individual},
            "individual_movement": {"enabled": individual},
        },
        "goals": [
            {
                "id": "balanced",
                "type": "balance",
                "config": {
                    "layer": "territory",
                    "owners": ["territory_a", "territory_b"],
                    "claimableLayer": "ground",
                    "claimableKind": "empty",
                },
            },
        ],
        "loseConditions": [],
    }


def _sliding_state_and_info() -> tuple[ea.EngineState, ea.EngineInfo]:
    game = ea.GameDef.from_dict({
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"]},
            "block": {"layer": "ground", "tags": ["sliding_block"]},
        },
        "actions": [
            {
                "id": "move",
                "params": {
                    "position": {"type": "position"},
                    "direction": {
                        "type": "direction",
                        "values": ["up", "down", "left", "right"],
                    },
                },
            },
            {"id": "give_up", "params": {}},
        ],
        "systems": [
            {"id": "blocks", "type": "sliding_blocks", "config": {}},
        ],
    })
    level = {
        "id": "sliding_solver_smoke",
        "board": {
            "size": [3, 2],
            "layers": {},
            "multiCellObjects": [
                {
                    "id": "horizontal",
                    "kind": "block",
                    "cells": [[0, 0], [1, 0]],
                    "params": {"axis": "horizontal"},
                },
                {
                    "id": "vertical",
                    "kind": "block",
                    "cells": [[2, 0], [2, 1]],
                    "params": {"axis": "vertical"},
                },
            ],
        },
        "state": {},
        "goals": [],
        "loseConditions": [],
    }
    engine = ea.TurnEngine(game, level)
    state = ea.EngineState(engine.state.copy())
    info = ea.EngineInfo(
        game=game,
        level_def=level,
        pack_dir=Path("."),
        ACTIONS=ea._build_actions(game, 3, 2),
        level_id=level["id"],
        width=3,
        height=2,
    )
    return state, info


def _terminal_sliding_state_and_info() -> tuple[ea.EngineState, ea.EngineInfo]:
    game = ea.GameDef.from_dict({
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
        ],
        "entityKinds": {
            "floor": {"layer": "ground", "tags": ["walkable"]},
            "block": {"layer": "structures", "tags": ["sliding_block"]},
        },
        "actions": [{
            "id": "move",
            "params": {
                "position": {"type": "position"},
                "direction": {
                    "type": "direction",
                    "values": ["left", "right"],
                },
            },
        }],
        "systems": [{
            "id": "blocks",
            "type": "sliding_blocks",
            "config": {},
        }],
        "rules": [{
            "id": "count_moves",
            "on": "multi_cell_object_moved",
            "then": [{
                "increment_variable": {"name": "moves", "amount": 1},
            }],
        }],
        "defaults": {"avatar": {"enabled": False}},
    })
    level = {
        "id": "terminal_solver_smoke",
        "board": {
            "size": [3, 1],
            "layers": {},
            "multiCellObjects": [{
                "id": "moving",
                "kind": "block",
                "cells": [[0, 0]],
                "params": {"axis": "horizontal"},
            }],
        },
        "state": {
            "variables": {"moves": 0},
            "avatar": {"enabled": False},
        },
        "goals": [{
            "id": "two_moves",
            "type": "variable_threshold",
            "config": {"variable": "moves", "target": 2, "comparison": "gte"},
        }],
        "loseConditions": [{"type": "max_actions", "config": {"limit": 1}}],
    }
    engine = ea.TurnEngine(game, level)
    state = ea.EngineState(engine.state.copy())
    info = ea.EngineInfo(
        game=game,
        level_def=level,
        pack_dir=Path("."),
        ACTIONS=ea._build_actions(game, 3, 1),
        level_id=level["id"],
        width=3,
        height=1,
    )
    return state, info


class ActorBalanceSolverTests(unittest.TestCase):
    def test_unknown_standard_pack_uses_generic_dsl_solver(self) -> None:
        level_path = FIXTURE_PACK / "levels" / "actor_balance_smoke_01.json"
        self.assertEqual(solve._detect_game(level_path), "generic")

    def test_individual_actions_only_select_current_actors(self) -> None:
        state, info = ea.load(_level(individual=True), FIXTURE_PACK)

        self.assertEqual(
            ea.legal_actions(state, info),
            ["tap_cell_0_0", "tap_cell_2_1"],
        )

    def test_individual_moves_exclude_blocked_and_selected_actor(self) -> None:
        state, info = ea.load(_level(individual=True), FIXTURE_PACK)
        state, _won, _events = ea.apply(state, "tap_cell_0_0", info)

        self.assertEqual(
            ea.legal_actions(state, info),
            ["move_down", "move_right", "tap_cell_2_1"],
        )

    def test_coupled_mode_uses_max_deficit_heuristic(self) -> None:
        state, info = ea.load(_level(individual=False), FIXTURE_PACK)
        self.assertEqual(ea.heuristic(state, info), 3.0)

    def test_individual_mode_includes_selection_lower_bound(self) -> None:
        state, info = ea.load(_level(individual=True), FIXTURE_PACK)
        self.assertEqual(ea.heuristic(state, info), 8.0)

        state, _won, _events = ea.apply(state, "tap_cell_0_0", info)
        self.assertEqual(ea.heuristic(state, info), 7.0)

    def test_composite_position_direction_actions_round_trip(self) -> None:
        game = ea.GameDef.from_dict({
            "actions": [{
                "id": "move",
                "params": {
                    "position": {"type": "position"},
                    "direction": {
                        "type": "direction",
                        "values": ["up", "down", "left", "right"],
                    },
                },
            }],
        })

        actions = ea._build_actions(game, width=2, height=2)

        self.assertIn("move_1_0_left", actions)
        self.assertEqual(
            ea._parse_action("move_1_0_left", game),
            ("move", {"position": [1, 0], "direction": "left"}),
        )
        self.assertEqual(
            ea.gold_path_actions({
                "solution": {
                    "goldPath": [{
                        "action": "move",
                        "position": [1, 0],
                        "direction": "left",
                    }],
                },
            }),
            ["move_1_0_left"],
        )

    def test_sliding_actions_use_one_canonical_position_per_block(self) -> None:
        state, info = _sliding_state_and_info()

        self.assertEqual(
            ea.legal_actions(state, info),
            [
                "move_0_0_left",
                "move_0_0_right",
                "move_2_0_up",
                "move_2_0_down",
                "give_up",
            ],
        )
        self.assertEqual(
            ea.canonicalize_path(["move_1_0_right"], state, info),
            ["move_0_0_right"],
        )

    def test_unsupported_balance_config_falls_back_to_plain_search(self) -> None:
        state, info = ea.load(_level(individual=True), FIXTURE_PACK)
        individual = next(
            system for system in info.game.systems
            if system["type"] == "individual_actors"
        )
        individual["config"]["budgets"] = {}

        self.assertEqual(ea.heuristic(state, info), 0.0)
        self.assertFalse(ea.can_prune(state, info, depth=0, max_depth=20))

    def test_terminal_states_cannot_be_extended_into_false_solutions(self) -> None:
        state, info = _terminal_sliding_state_and_info()

        lost_state, won, _events = ea.apply(state, "move_0_0_right", info)

        self.assertFalse(won)
        self.assertTrue(lost_state.game_state.is_lost)
        self.assertEqual(ea.legal_actions(lost_state, info), [])

        unchanged, won, events = ea.apply(
            lost_state,
            "move_1_0_right",
            info,
        )
        self.assertIs(unchanged, lost_state)
        self.assertFalse(won)
        self.assertEqual(events, [])
        self.assertEqual(unchanged.game_state.variables["moves"], 1)

    def test_reactive_rules_disable_actor_pruning_and_balance_heuristics(self) -> None:
        level = _level(individual=True)
        level["rules"] = [{
            "id": "observe_blocked_move",
            "on": "actor_blocked",
            "then": [],
        }]
        state, info = ea.load(level, FIXTURE_PACK)

        self.assertEqual(ea.legal_actions(state, info), info.ACTIONS)
        self.assertEqual(ea.heuristic(state, info), 0.0)
        self.assertFalse(ea.can_prune(state, info, depth=0, max_depth=20))

    def test_actor_at_target_can_still_move_out_of_the_way(self) -> None:
        level = _level(individual=True)
        level["board"]["layers"]["territory"] = {
            "format": "sparse",
            "entries": [
                {"position": [0, 0], "kind": "territory_a"},
                {"position": [1, 0], "kind": "territory_a"},
                {"position": [2, 0], "kind": "territory_a"},
            ],
        }
        state, info = ea.load(level, FIXTURE_PACK)
        state, _won, _events = ea.apply(state, "tap_cell_0_0", info)

        actions = ea.legal_actions(state, info)

        self.assertIn("move_down", actions)
        self.assertIn("move_right", actions)

    def test_custom_actor_layer_keeps_balance_optimization_sound(self) -> None:
        state, info = ea.load(_level(individual=True), FIXTURE_PACK)
        individual = next(
            system for system in info.game.systems
            if system["type"] == "individual_actors"
        )
        individual["config"]["actorLayer"] = "pieces"
        state.game_state.board.layers["pieces"] = (
            state.game_state.board.layers.pop("actors")
        )

        self.assertEqual(ea.heuristic(state, info), 8.0)
        self.assertFalse(ea.can_prune(state, info, depth=0, max_depth=20))

    def test_mismatched_claimable_and_movement_layers_disable_optimization(self) -> None:
        state, info = ea.load(_level(individual=True), FIXTURE_PACK)
        individual = next(
            system for system in info.game.systems
            if system["type"] == "individual_actors"
        )
        individual["config"]["groundLayer"] = "territory"

        self.assertEqual(ea.heuristic(state, info), 0.0)
        self.assertFalse(ea.can_prune(state, info, depth=0, max_depth=20))


if __name__ == "__main__":
    unittest.main()
