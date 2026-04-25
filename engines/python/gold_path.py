"""
Single source of truth for parsing a level's `solution.goldPath`.

Each entry can be in one of two forms:

- Dict form: ``{"action": "<id>", "direction": "<dir>", ...other-params}``
- String shorthand: ``"up" | "down" | "left" | "right"`` for cardinal moves,
  or any other action id with no params.

All callers (engine observation, benchmark runner, gold-path tests) should
use these helpers so the schema can evolve in one place.
"""
from __future__ import annotations

_CARDINALS = frozenset({"up", "down", "left", "right"})


def gold_path_length(level_def: dict) -> int:
    """Number of moves in the gold path (0 if absent)."""
    return len(level_def.get("solution", {}).get("goldPath", []))


def gold_path_actions(level_def: dict) -> list[tuple[str, dict]]:
    """Parse the gold path into ``(action_id, params)`` tuples."""
    actions: list[tuple[str, dict]] = []
    for entry in level_def.get("solution", {}).get("goldPath", []):
        if isinstance(entry, dict):
            action_id = entry.get("action", "move")
            params = {k: v for k, v in entry.items() if k != "action"}
            actions.append((action_id, params))
        elif isinstance(entry, str):
            if entry in _CARDINALS:
                actions.append(("move", {"direction": entry}))
            else:
                actions.append((entry, {}))
    return actions
