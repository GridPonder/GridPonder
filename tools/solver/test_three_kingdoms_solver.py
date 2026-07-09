from __future__ import annotations

import json
import unittest
from pathlib import Path

import engine_adapter as ea


def _private_three_kingdoms_pack() -> Path:
    return Path(__file__).resolve().parents[3] / "gridponder-private" / "three_kingdoms"


def _load_private_level(level_id: str):
    pack_dir = _private_three_kingdoms_pack()
    level_path = pack_dir / "levels" / f"{level_id}.json"
    assert level_path.exists(), f"missing private fixture: {level_path}"
    level_json = json.loads(level_path.read_text())
    return ea.load(level_json, pack_dir)


class ThreeKingdomsSolverTests(unittest.TestCase):
    def test_individual_mode_initial_actions_only_select_current_actors(self) -> None:
        state, info = _load_private_level("tk_005")

        self.assertEqual(
            ea.legal_actions(state, info),
            [
                "tap_cell_1_1",
                "tap_cell_3_2",
                "tap_cell_6_6",
            ],
        )


    def test_individual_mode_move_actions_exclude_blocked_moves_and_current_selection(self) -> None:
        state, info = _load_private_level("tk_005")
        state, _won, _events = ea.apply(state, "tap_cell_1_1", info)

        self.assertEqual(
            ea.legal_actions(state, info),
            [
                "move_down",
                "move_right",
                "tap_cell_3_2",
                "tap_cell_6_6",
            ],
        )

    def test_coupled_mode_uses_max_deficit_heuristic(self) -> None:
        state, info = _load_private_level("tk_006")

        self.assertEqual(ea.heuristic(state, info), 10.0)

    def test_individual_mode_uses_sum_deficit_plus_selection_lower_bound(self) -> None:
        state, info = _load_private_level("tk_005")

        self.assertEqual(ea.heuristic(state, info), 24.0)

    def test_individual_selection_reduces_selection_lower_bound(self) -> None:
        state, info = _load_private_level("tk_005")
        state, _won, _events = ea.apply(state, "tap_cell_1_1", info)

        self.assertEqual(ea.heuristic(state, info), 23.0)

    def test_individual_heuristic_counts_distance_to_next_claim(self) -> None:
        state, info = _load_private_level("tk_005")
        for action in ea.gold_path_actions(info.level_def)[:14]:
            state, _won, _events = ea.apply(state, action, info)

        self.assertEqual(ea.heuristic(state, info), 13.0)


if __name__ == "__main__":
    unittest.main()
