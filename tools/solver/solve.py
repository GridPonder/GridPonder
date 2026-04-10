#!/usr/bin/env python3
"""
GridPonder puzzle solver.

Enumerates solutions for a level up to a given depth and reports whether
the intended gold path is unique.

Two search modes:
  Default           BFS with state deduplication — finds the shortest solution
                    and all solutions at that same depth.
  --all-solutions   DFS without cross-path deduplication — finds every winning
                    path up to --max-depth, including longer alternatives.
                    (BFS deduplication would silently drop longer paths that
                    pass through states already seen via shorter routes.)

Currently supported games (auto-detected from pack folder name):
  number_cells  →  Number Crunch (slide-merge + queued emitters)

Usage:
    python solve.py <path/to/level.json> [options]

Options:
    --max-depth N     Search up to N moves deep (default: 8)
    --all-solutions   Find every solution up to --max-depth (uses DFS)

Examples:
    python solve.py ../../packs/number_cells/levels/nc_005.json
    python solve.py ../../packs/number_cells/levels/nc_005.json --max-depth 10 --all-solutions
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
import games.number_crunch as nc
import games.rotate_flip as rf
import games.box_builder as bb


# ---------------------------------------------------------------------------
# Game detection
# ---------------------------------------------------------------------------

def _detect_game(level_path: Path) -> str:
    for part in level_path.parts:
        if part == "number_cells":
            return "number_crunch"
        if part == "rotate_flip":
            return "rotate_flip"
        if part == "box_builder":
            return "box_builder"
    return "number_crunch"


# ---------------------------------------------------------------------------
# Search: BFS (shortest only) and DFS (all solutions)
# ---------------------------------------------------------------------------

def _bfs_shortest(
    initial: nc.NCState,
    info: nc.LevelInfo,
    max_depth: int,
) -> List[List[str]]:
    """
    BFS with state deduplication.

    Finds the minimum-length solution depth, then returns all solutions at
    that depth.  Longer alternatives are not reported.
    """
    queue: deque = deque([(initial, [])])
    visited: Dict[nc.NCState, int] = {initial: 0}
    solutions: List[List[str]] = []
    shortest: Optional[int] = None

    while queue:
        cur, path = queue.popleft()
        depth = len(path)

        if shortest is not None and depth >= shortest:
            continue
        if depth >= max_depth:
            continue

        for direction in nc.ACTIONS:
            new_state, won = nc.apply(cur, direction, info)
            new_depth = depth + 1
            new_path = path + [direction]

            if won:
                solutions.append(new_path)
                if shortest is None:
                    shortest = new_depth
                continue

            if nc.can_prune(new_state, info, new_depth, max_depth):
                continue

            prev = visited.get(new_state)
            if prev is not None and prev <= new_depth:
                continue
            visited[new_state] = new_depth
            queue.append((new_state, new_path))

    return solutions


def _dfs_all(
    initial: nc.NCState,
    info: nc.LevelInfo,
    max_depth: int,
) -> List[List[str]]:
    """
    DFS without cross-path state deduplication.

    Visits every path up to max_depth (pruning obviously dead branches).
    Cycle detection within each path prevents infinite loops.
    """
    solutions: List[List[str]] = []

    def _dfs(state: nc.NCState, path: List[str], path_states: set) -> None:
        depth = len(path)
        for direction in nc.ACTIONS:
            new_state, won = nc.apply(state, direction, info)
            new_depth = depth + 1
            new_path = path + [direction]

            if won:
                solutions.append(new_path)
                continue

            if new_depth >= max_depth:
                continue
            if nc.can_prune(new_state, info, new_depth, max_depth):
                continue
            # Avoid revisiting the same state on THIS path (cycle prevention)
            if new_state in path_states:
                continue

            _dfs(new_state, new_path, path_states | {new_state})

    _dfs(initial, [], {initial})
    return solutions


# ---------------------------------------------------------------------------
# Rotate-Flip solver (BFS only)
# ---------------------------------------------------------------------------

def _solve_rotate_flip(
    path: Path,
    level_json: Dict[str, Any],
    max_depth: int,
    all_solutions: bool,
) -> None:
    from collections import deque as _deque

    initial, info = rf.load(level_json)
    level_id = info.level_id or path.stem
    print(f"Solving  {level_id}   (max depth {max_depth})")
    print(f"  Game:   Rotate & Flip")
    print(f"  Board:  {info.cols}×{info.rows}  overlay {info.overlay_w}×{info.overlay_h}")
    print(f"  Mode:   {'DFS — all solutions' if all_solutions else 'BFS — shortest solution'}")
    print()

    # BFS
    queue: deque = _deque([(initial, [])])
    visited: Dict = {initial: 0}
    solutions: List[List[str]] = []
    shortest: Optional[int] = None

    while queue:
        state, path_so_far = queue.popleft()
        depth = len(path_so_far)
        if shortest is not None and depth >= shortest:
            continue
        if depth >= max_depth:
            continue
        for action in rf.ACTIONS:
            ns, won = rf.apply(state, action, info)
            new_depth = depth + 1
            new_path = path_so_far + [action]
            if won:
                solutions.append(new_path)
                if shortest is None:
                    shortest = new_depth
                continue
            prev = visited.get(ns)
            if prev is not None and prev <= new_depth:
                continue
            visited[ns] = new_depth
            queue.append((ns, new_path))

    if not solutions:
        print(f"No solution found within {max_depth} moves.")
        return

    min_len = len(solutions[0])
    print(f"Solutions found: {len(solutions)}  (shortest: {min_len} move{'s' if min_len != 1 else ''})")
    print()
    for sol in solutions:
        marker = "★" if len(sol) == min_len else " "
        print(f"  {marker} {len(sol)} moves: {sol}")
    print()

    gold_raw = level_json.get("solution", {}).get("goldPath", [])
    if gold_raw:
        gold = [
            m.get("direction", m.get("action", "?"))
            if m.get("action") == "move" else m.get("action", "?")
            for m in gold_raw
        ]
        gold_actions = [
            f"move_{m['direction']}" if m.get("action") == "move" else m["action"]
            for m in gold_raw
        ]
        if gold_actions in solutions:
            print(f"  Gold path: ✓  {gold_actions}")
        else:
            note = f"(not among the {len(solutions)} shortest solutions found)"
            print(f"  Gold path: ✗  {gold_actions}  {note}")

    if gold_raw and min_len < len(gold_raw):
        print(f"\n  ⚠  WARNING: a {min_len}-move solution exists "
              f"— shorter than the declared gold path ({len(gold_raw)} moves)!")
    elif len(solutions) == 1:
        print(f"\n  ✓  UNIQUE: exactly one {min_len}-move solution exists.")
    else:
        print(f"\n  ✗  NOT UNIQUE: {len(solutions)} solutions at depth {min_len}.")


# ---------------------------------------------------------------------------
# Box Builder solver
# ---------------------------------------------------------------------------

def _parse_json_arg(value: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse a JSON string or @filename argument."""
    if value is None:
        return None
    if value.startswith("@"):
        with open(value[1:]) as f:
            return json.load(f)
    return json.loads(value)


def _solve_box_builder(
    path: Path,
    level_json: Dict[str, Any],
    max_depth: int,
    all_solutions: bool,
    override_start: Optional[str] = None,
    partial_goal: Optional[str] = None,
) -> None:
    from collections import deque as _deque

    initial, info = bb.load(level_json)

    override_json = _parse_json_arg(override_start)
    if override_json is not None:
        initial = bb.override_initial_state(initial, override_json)

    partial_goal_json = _parse_json_arg(partial_goal)

    def _is_win(state: bb.BBState) -> bool:
        if partial_goal_json is not None:
            return bb.matches_waypoint(state, partial_goal_json)
        return bb._check_win(state, info)

    level_id = info.level_id or path.stem
    print(f"Solving  {level_id}   (max depth {max_depth})")
    print(f"  Game:   Box Builder")
    print(f"  Board:  {info.width}×{info.height}  "
          f"({len(info.walls)} wall cells,  {len(info.targets)} target(s))")
    if override_json:
        print(f"  Start:  overridden")
    if partial_goal_json:
        print(f"  Goal:   partial waypoint")
    print(f"  Mode:   {'DFS — all solutions' if all_solutions else 'BFS — shortest solution'}")
    print()

    solutions: List[List[str]] = []
    shortest: Optional[int] = None

    if not all_solutions:
        # BFS with deduplication
        queue: _deque = _deque([(initial, [])])
        visited: Dict = {initial: 0}

        while queue:
            state, path_so_far = queue.popleft()
            depth = len(path_so_far)
            if shortest is not None and depth >= shortest:
                continue
            if depth >= max_depth:
                continue
            for direction in bb.ACTIONS:
                ns, won = bb.apply(state, direction, info)
                new_depth = depth + 1
                new_path = path_so_far + [direction]
                if not won:
                    won = _is_win(ns)
                if won:
                    solutions.append(new_path)
                    if shortest is None:
                        shortest = new_depth
                    continue
                if partial_goal_json is None and bb.can_prune(ns, info, new_depth, max_depth):
                    continue
                prev = visited.get(ns)
                if prev is not None and prev <= new_depth:
                    continue
                visited[ns] = new_depth
                queue.append((ns, new_path))
    else:
        # DFS without cross-path deduplication
        def _dfs(state: bb.BBState, path_so_far: List[str], path_states: set) -> None:
            depth = len(path_so_far)
            for direction in bb.ACTIONS:
                ns, won = bb.apply(state, direction, info)
                new_depth = depth + 1
                new_path = path_so_far + [direction]
                if not won:
                    won = _is_win(ns)
                if won:
                    solutions.append(new_path)
                    continue
                if new_depth >= max_depth:
                    continue
                if partial_goal_json is None and bb.can_prune(ns, info, new_depth, max_depth):
                    continue
                if ns in path_states:
                    continue
                _dfs(ns, new_path, path_states | {ns})

        _dfs(initial, [], {initial})

    if not solutions:
        print(f"No solution found within {max_depth} moves.")
        return

    solutions.sort(key=len)
    min_len = len(solutions[0])
    print(f"Solutions found: {len(solutions)}  (shortest: {min_len} move{'s' if min_len != 1 else ''})")
    print()
    for sol in solutions:
        marker = "★" if len(sol) == min_len else " "
        print(f"  {marker} {len(sol)} moves: {sol}")
    print()

    gold_raw = level_json.get("solution", {}).get("goldPath", [])
    if gold_raw:
        gold = [m["direction"] for m in gold_raw if m.get("action") == "move"]
        gold_str = " ".join(d.upper() for d in gold)
        if gold in solutions:
            print(f"  Gold path: ✓  {gold_str}")
        else:
            print(f"  Gold path: ✗  {gold_str}  (not among the {len(solutions)} solutions found)")

    if gold_raw and min_len < len(gold_raw):
        print(f"\n  ⚠  WARNING: a {min_len}-move solution exists "
              f"— shorter than the declared gold path ({len(gold_raw)} moves)!")
    elif len([s for s in solutions if len(s) == min_len]) == 1:
        print(f"\n  ✓  UNIQUE: exactly one {min_len}-move solution exists.")
    else:
        count = len([s for s in solutions if len(s) == min_len])
        print(f"\n  ✗  NOT UNIQUE: {count} solutions at depth {min_len}.")


# ---------------------------------------------------------------------------
# Main solver
# ---------------------------------------------------------------------------

def solve(
    level_path: str,
    max_depth: int = 8,
    all_solutions: bool = False,
    **kwargs,
) -> None:
    path = Path(level_path)
    with open(path) as f:
        level_json: Dict[str, Any] = json.load(f)

    game = _detect_game(path)
    if game == "rotate_flip":
        _solve_rotate_flip(path, level_json, max_depth, all_solutions)
        return

    if game == "box_builder":
        _solve_box_builder(path, level_json, max_depth, all_solutions,
                           override_start=kwargs.get("override_start"),
                           partial_goal=kwargs.get("partial_goal"))
        return

    if game != "number_crunch":
        print(f"Error: unsupported game '{game}'", file=sys.stderr)
        sys.exit(1)

    initial_state, info = nc.load(level_json)

    # ── Header ──────────────────────────────────────────────────────────────
    level_id = info.level_id or path.stem
    print(f"Solving  {level_id}   (max depth {max_depth})")
    print(f"  Game:     Number Crunch")
    print(f"  Board:    {info.width}×{info.height}  "
          f"({len(info.void_cells)} void cells)")
    print(f"  Pipes:    {len(info.pipes)}", end="")
    for p in info.pipes:
        print(f"  queue={p.queue}", end="")
    print()
    print(f"  Sequence: {info.sequence}")
    if info.max_turns:
        print(f"  Max turns: {info.max_turns}")
    mode = "DFS — all solutions" if all_solutions else "BFS — shortest solutions"
    print(f"  Mode:     {mode}")
    print()

    # ── Search ──────────────────────────────────────────────────────────────
    if all_solutions:
        solutions = _dfs_all(initial_state, info, max_depth)
    else:
        solutions = _bfs_shortest(initial_state, info, max_depth)

    # ── Results ─────────────────────────────────────────────────────────────
    if not solutions:
        print(f"No solution found within {max_depth} moves.")
        return

    solutions.sort(key=len)
    min_len = len(solutions[0])

    by_depth: Dict[int, List[List[str]]] = {}
    for s in solutions:
        by_depth.setdefault(len(s), []).append(s)

    print(f"Solutions found: {len(solutions)}  "
          f"(shortest: {min_len} move{'s' if min_len != 1 else ''})")
    print()

    for depth in sorted(by_depth):
        paths = by_depth[depth]
        marker = "★" if depth == min_len else " "
        print(f"  {marker} depth {depth}: {len(paths)} solution(s)")
        for p in paths:
            print(f"      {' '.join(d.upper() for d in p)}")

    print()

    # ── Gold path validation ─────────────────────────────────────────────────
    gold_raw = level_json.get("solution", {}).get("goldPath", [])
    if gold_raw:
        gold = [m["direction"] for m in gold_raw]
        gold_str = " ".join(d.upper() for d in gold)
        if gold in solutions:
            print(f"  Gold path: ✓  {gold_str}")
        else:
            # Gold path not found — simulate to explain why
            sim_state = initial_state
            for step, d in enumerate(gold, 1):
                sim_state, won = nc.apply(sim_state, d, info)
                if won:
                    break
            if sim_state.seq_idx >= len(info.sequence):
                note = "(valid but longer than --max-depth or filtered by BFS; use --all-solutions)"
            else:
                note = f"(simulation ends at seq_idx={sim_state.seq_idx}/{len(info.sequence)})"
            print(f"  Gold path: ✗  {gold_str}  {note}")

    # ── Uniqueness verdict ───────────────────────────────────────────────────
    gold_len = len(gold_raw) if gold_raw else None
    shortest_solutions = by_depth.get(min_len, [])

    print()
    if gold_len and min_len < gold_len:
        print(f"  ⚠  WARNING: a {min_len}-move solution exists "
              f"— shorter than the declared gold path ({gold_len} moves)!")
    elif len(shortest_solutions) == 1:
        print(f"  ✓  UNIQUE: exactly one {min_len}-move solution exists.")
    else:
        print(f"  ✗  NOT UNIQUE: {len(shortest_solutions)} solutions "
              f"at depth {min_len}.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="GridPonder puzzle solver — enumerate solutions for a level.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("level", help="Path to the level JSON file")
    parser.add_argument(
        "--max-depth", type=int, default=8, metavar="N",
        help="Maximum moves to search (default: 8)",
    )
    parser.add_argument(
        "--all-solutions", action="store_true",
        help="Find all solutions up to --max-depth (uses DFS; slower but complete)",
    )
    parser.add_argument(
        "--override-start", metavar="JSON",
        help='Override initial board state. JSON string or @file. '
             'Format: {"boxes":[{"position":[x,y],"sides":N},...], '
             '"rocks":[[x,y],...], "pickaxes":[[x,y],...], '
             '"avatar":[x,y], "inventory":null}',
    )
    parser.add_argument(
        "--partial-goal", metavar="JSON",
        help='Use a partial intermediate goal instead of the level win condition. '
             'JSON string or @file. '
             'Format: {"boxes":[{"position":[x,y],"sides":N},...], '
             '"avatar":[x,y], "inventory":null}',
    )
    args = parser.parse_args()
    solve(args.level, args.max_depth, args.all_solutions,
          override_start=args.override_start,
          partial_goal=args.partial_goal)


if __name__ == "__main__":
    main()
