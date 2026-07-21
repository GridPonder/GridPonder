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

    def test_unsupported_balance_config_falls_back_to_plain_search(self) -> None:
        state, info = ea.load(_level(individual=True), FIXTURE_PACK)
        individual = next(
            system for system in info.game.systems
            if system["type"] == "individual_actors"
        )
        individual["config"]["budgets"] = {}

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


if __name__ == "__main__":
    unittest.main()
