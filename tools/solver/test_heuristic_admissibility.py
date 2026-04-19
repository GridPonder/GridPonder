"""
Empirical heuristic admissibility test.

For every game that declares has_heuristic=True in game_configs.py, and for
every level in that pack that has a gold path, this test replays the gold path
step by step and asserts:

    h(state_i) <= len(gold_path) - i   for all i in 0..len(gold_path)

An admissible heuristic must never overestimate the cost to reach the goal.
Since the gold path is a valid solution, len(gold_path) - i is an upper bound
on the true cost from state_i.  Any violation would mean h(state_i) exceeds a
known achievable cost — a clear admissibility failure.

This is not a formal proof but gives strong empirical evidence across all known
levels, especially those whose gold paths were verified by BFS or human play.

Run with:
    cd tools/solver && python -m pytest test_heuristic_admissibility.py -v
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from game_configs import GAME_CONFIGS

_SOLVER_DIR = Path(__file__).parent
_PACKS_DIR = _SOLVER_DIR.parent.parent / "packs"


def _parse_gold_actions(gold_raw: list, module: Any) -> list[str]:
    """
    Convert raw goldPath entries to a flat list of action strings.

    Handles two known formats:
      - carrot_quest:  [{"direction": "left"}, ...]
      - box_builder:     [{"action": "move", "direction": "left"}, ...]

    Entries whose "action" key is something other than "move" are skipped
    (e.g. future non-move actions).
    """
    valid = set(module.ACTIONS)
    actions: list[str] = []
    for entry in gold_raw:
        if isinstance(entry, str):
            if entry in valid:
                actions.append(entry)
        elif isinstance(entry, dict):
            action_type = entry.get("action")
            if action_type is not None and action_type != "move":
                continue
            direction = entry.get("direction")
            if direction in valid:
                actions.append(direction)
    return actions


def _collect_cases() -> list:
    """
    Yield pytest.param tuples for all (game, level) pairs that have a heuristic
    and a non-empty gold path.
    """
    cases = []
    for game_key, config in GAME_CONFIGS.items():
        if not config.get("has_heuristic"):
            continue
        module_name = config.get("game_module")
        if not module_name:
            continue

        # Pack directory name matches game_key by convention
        levels_dir = _PACKS_DIR / game_key / "levels"
        if not levels_dir.exists():
            continue

        module = importlib.import_module(f"games.{module_name}")
        if not hasattr(module, "heuristic"):
            continue  # module opted out of heuristic despite config flag

        for level_file in sorted(levels_dir.glob("*.json")):
            level_json = json.loads(level_file.read_text())
            gold_raw = level_json.get("solution", {}).get("goldPath", [])
            if not gold_raw:
                continue
            gold_actions = _parse_gold_actions(gold_raw, module)
            if not gold_actions:
                continue
            cases.append(
                pytest.param(
                    game_key,
                    level_file.stem,
                    level_json,
                    module,
                    gold_actions,
                    id=f"{game_key}/{level_file.stem}",
                )
            )
    return cases


@pytest.mark.parametrize(
    "game_key,level_id,level_json,module,gold_actions",
    _collect_cases(),
)
def test_heuristic_admissibility(
    game_key: str,
    level_id: str,
    level_json: dict,
    module: Any,
    gold_actions: list[str],
) -> None:
    """
    h(state_i) must never exceed the number of remaining gold-path steps.

    Checked at every intermediate state, not just the initial state, for
    maximum coverage.
    """
    initial, info = module.load(level_json)
    heuristic = module.heuristic
    n = len(gold_actions)

    state = initial
    for i, action in enumerate(gold_actions):
        remaining = n - i
        h = heuristic(state, info)
        assert h <= remaining, (
            f"{game_key}/{level_id}: at step {i} (action={action!r}), "
            f"h={h} > remaining={remaining} — heuristic is inadmissible here"
        )
        state, _won, _events = module.apply(state, action, info)

    # At the goal state, the heuristic must return 0
    h_goal = heuristic(state, info)
    assert h_goal == 0.0, (
        f"{game_key}/{level_id}: h(goal state) = {h_goal}, expected 0.0"
    )
