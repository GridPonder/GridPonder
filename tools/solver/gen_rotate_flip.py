#!/usr/bin/env python3
"""Find a rotate_flip level whose SHORTEST forward gold path is exactly TARGET.

Algorithm (two-phase)
---------------------
  Phase 1  BFS outward from the goal state (using forward actions), collecting
           all reachable states up to MAX_SEARCH steps.  Any state at depth D
           is reachable FROM the goal in D steps; because the action graph is
           reversible, the goal is also reachable FROM that state in at most D
           steps (possibly fewer via a different route).

  Phase 2  For each candidate state found at depth TARGET that satisfies the
           layout constraints, run a FORWARD BFS from that state to the goal.
           Accept only those where the forward BFS confirms shortest = TARGET.
           This guarantees the gold path length is exactly TARGET and no
           shorter solution exists.

Usage (from repo root):
    python3 tools/solver/gen_rotate_flip.py
    python3 tools/solver/gen_rotate_flip.py --target 6
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from games.rotate_flip import (
    RFState, LevelInfo, Board,
    ACTIONS, apply, board_satisfies_constraints,
)

# ---------------------------------------------------------------------------
# Goal board: two clean 2×2 colour blocks
#
#   R  G  .  .
#   Y  B  .  .
#   .  .  R  G
#   .  .  Y  B
#
# 2 per row, 2 per column ✓   4 colours × 2 each ✓
# ---------------------------------------------------------------------------

COLS, ROWS = 4, 4
OW, OH = 2, 2

GOAL_GRID = [
    ["cell_red",    "cell_green", None,          None        ],
    ["cell_yellow", "cell_blue",  None,          None        ],
    [None,          None,         "cell_red",    "cell_green"],
    [None,          None,         "cell_yellow", "cell_blue" ],
]


def _grid_to_board(grid) -> Board:
    return frozenset(
        ((c, r), kind)
        for r, row in enumerate(grid)
        for c, kind in enumerate(row)
        if kind is not None
    )


def _board_to_entries(board: Board) -> list:
    return [{"position": list(pos), "kind": kind} for pos, kind in sorted(board)]


def _board_to_target_layers(board: Board) -> list:
    bd = dict(board)
    return [[bd.get((c, r)) for c in range(COLS)] for r in range(ROWS)]


# ---------------------------------------------------------------------------
# BFS helpers
# ---------------------------------------------------------------------------

def _make_info(goal_board: Board) -> LevelInfo:
    return LevelInfo(cols=COLS, rows=ROWS, overlay_w=OW, overlay_h=OH,
                     goal_board=goal_board)


def bfs_from(start: RFState, info: LevelInfo, max_depth: int
             ) -> dict[RFState, tuple[int, list[str]]]:
    """Return {state: (depth, path)} for all states reachable from start."""
    visited: dict[RFState, tuple[int, list[str]]] = {start: (0, [])}
    queue: deque = deque([(start, [])])
    while queue:
        state, path = queue.popleft()
        depth = len(path)
        if depth >= max_depth:
            continue
        for action in ACTIONS:
            ns, _ = apply(state, action, info)
            if ns not in visited:
                new_path = path + [action]
                visited[ns] = (depth + 1, new_path)
                queue.append((ns, new_path))
    return visited


def shortest_path_to_goal(
    start: RFState, info: LevelInfo, max_depth: int
) -> list[str] | None:
    """Forward BFS from start → goal.  Returns path or None if not found."""
    if start.board == info.goal_board:
        return []
    queue: deque = deque([(start, [])])
    visited: set = {start}
    while queue:
        state, path = queue.popleft()
        if len(path) >= max_depth:
            continue
        for action in ACTIONS:
            ns, won = apply(state, action, info)
            if won:
                return path + [action]
            if ns not in visited:
                visited.add(ns)
                queue.append((ns, path + [action]))
    return None


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def find_candidate(target: int, max_search: int):
    goal_board = _grid_to_board(GOAL_GRID)
    info = _make_info(goal_board)

    # Phase 1: BFS outward from goal to find candidate initial states
    goal_start = RFState(board=goal_board, ox=0, oy=0)
    reachable = bfs_from(goal_start, info, max_depth=target)

    candidates = [
        state for state, (depth, _) in reachable.items()
        if depth == target
        and state.board != goal_board
        and board_satisfies_constraints(state.board, COLS, ROWS)
    ]

    print(f"  Phase 1: {len(candidates)} layout-valid candidate(s) at depth {target}",
          flush=True)

    # Phase 2: forward BFS confirms shortest path = target
    for state in candidates:
        path = shortest_path_to_goal(state, info, max_depth=target + 1)
        if path is not None and len(path) == target:
            return state, path

    return None


def _action_to_gold_step(action: str) -> dict:
    if action.startswith("move_"):
        return {"action": "move", "direction": action[5:]}
    return {"action": action}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, default=6)
    parser.add_argument("--max-search", type=int, default=8)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    print(f"Searching for a {args.target}-step rotate_flip level…", flush=True)
    result = find_candidate(args.target, args.max_search)

    if result is None:
        print(f"No valid configuration found at depth {args.target}.")
        sys.exit(1)

    initial_state, forward_path = result
    goal_board = _grid_to_board(GOAL_GRID)

    hint_stop = len(forward_path) // 2
    level = {
        "id": "rf_003",
        "title": "Colour Cascade",
        "board": {
            "size": [COLS, ROWS],
            "layers": {
                "objects": {
                    "format": "sparse",
                    "entries": _board_to_entries(initial_state.board),
                }
            },
        },
        "state": {
            "avatar": {
                "enabled": True,
                "position": [initial_state.ox, initial_state.oy],
                "facing": "right",
            },
            "overlay": {
                "position": [initial_state.ox, initial_state.oy],
                "size": [OW, OH],
            },
        },
        "goals": [{
            "id": "match",
            "type": "board_match",
            "config": {
                "matchMode": "exact_non_null",
                "targetLayers": {
                    "objects": _board_to_target_layers(goal_board),
                },
            },
        }],
        "solution": {
            "goldPath": [_action_to_gold_step(a) for a in forward_path],
            "hintStops": [hint_stop] if hint_stop else [],
        },
    }

    output_json = json.dumps(level, indent=2)
    if args.output:
        Path(args.output).write_text(output_json)
        print(f"Written to {args.output}")
    else:
        print(output_json)

    print(f"\nGold path ({len(forward_path)} moves): {forward_path}", file=sys.stderr)
    print(f"Initial overlay: ({initial_state.ox}, {initial_state.oy})", file=sys.stderr)


if __name__ == "__main__":
    main()
