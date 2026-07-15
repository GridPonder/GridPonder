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


if __name__ == "__main__":
    unittest.main()
