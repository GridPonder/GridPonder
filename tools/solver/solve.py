#!/usr/bin/env python3
"""
GridPonder puzzle solver.

Three search modes:
  bfs (default)  BFS with state deduplication — finds the shortest solution(s)
  dfs            DFS without cross-path dedup — finds every solution up to max-depth
  astar          A* with heuristic — finds the optimal solution; best for deep levels

Usage:
    python solve.py <path/to/level.json> [options]

Options:
    --max-depth N         Maximum moves to search (default: 30)
    --mode bfs|dfs|astar  Search algorithm (default: bfs)
    --timeout N           A* wall-clock timeout in seconds (default: 60)
    --trace               Print per-step event trace for the best solution
    --constraint JSON     Constraint dict (repeatable).
                          e.g. {"type":"must_not","event":"object_removed","kind":"rock"}
    --mc-trials N         Run N random rollouts to measure difficulty (default: 0 = off)
    --mc-steps N          Max steps per Monte Carlo trial (default: 3 × gold path length)
    --all-solutions       Alias for --mode dfs
    --override-start JSON Override initial board state (box_builder only). JSON or @file.
    --partial-goal JSON   Partial intermediate goal (box_builder only). JSON or @file.

Examples:
    python solve.py ../../packs/box_builder/levels/bb_007.json --mode astar --trace
    python solve.py ../../packs/box_builder/levels/bb_016.json --mode astar --max-depth 40
    python solve.py ../../packs/box_builder/levels/bb_013.json --mc-trials 50000
    python solve.py ../../packs/box_builder/levels/bb_007.json --mode bfs --max-depth 12 \\
        --constraint '{"type":"must_not","event":"object_removed","kind":"rock"}'
"""

from __future__ import annotations

import argparse
import json
import math
import random as _random
import statistics
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
import games.number_crunch as nc
import games.rotate_flip as rf
import games.box_builder as bb
import games.flag_adventure as fa
import engine_adapter as ea
from search.astar import astar
from search.events import format_event, violates_constraint
from search.types import Solution


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
        if part == "flag_adventure":
            return "flag_adventure"
        if part == "diagonal_swipes":
            return "diagonal_swipes"
        if part == "flood_colors":
            return "flood_colors"
    return "number_crunch"


# ---------------------------------------------------------------------------
# Generic BFS / DFS
# ---------------------------------------------------------------------------

def _bfs_shortest(
    initial: Any,
    info: Any,
    module: Any,
    max_depth: int,
    is_win_fn: Optional[Callable] = None,
    constraints: Optional[List[Dict]] = None,
    prune_fn: Optional[Callable] = None,
) -> List[List[str]]:
    """BFS: returns all solutions at the shortest depth found (dedup-limited)."""
    if prune_fn is None:
        prune_fn = module.can_prune

    queue: deque = deque([(initial, [])])
    visited: Dict[Any, int] = {initial: 0}
    solutions: List[List[str]] = []
    shortest: Optional[int] = None

    while queue:
        state, path = queue.popleft()
        depth = len(path)
        if shortest is not None and depth >= shortest:
            continue
        if depth >= max_depth:
            continue
        for action in module.ACTIONS:
            new_state, module_won, step_events = module.apply(state, action, info)
            if constraints and any(violates_constraint(step_events, c) for c in constraints):
                continue
            won = module_won or (is_win_fn is not None and is_win_fn(new_state))
            new_depth = depth + 1
            new_path = path + [action]
            if won:
                solutions.append(new_path)
                if shortest is None:
                    shortest = new_depth
                continue
            if prune_fn(new_state, info, new_depth, max_depth):
                continue
            prev = visited.get(new_state)
            if prev is not None and prev <= new_depth:
                continue
            visited[new_state] = new_depth
            queue.append((new_state, new_path))

    return solutions


def _dfs_all(
    initial: Any,
    info: Any,
    module: Any,
    max_depth: int,
    is_win_fn: Optional[Callable] = None,
    constraints: Optional[List[Dict]] = None,
    prune_fn: Optional[Callable] = None,
) -> List[List[str]]:
    """DFS: finds all solutions up to max_depth (no cross-path dedup)."""
    if prune_fn is None:
        prune_fn = module.can_prune

    solutions: List[List[str]] = []

    def _dfs(state: Any, path: List[str], path_states: set) -> None:
        depth = len(path)
        for action in module.ACTIONS:
            new_state, module_won, step_events = module.apply(state, action, info)
            if constraints and any(violates_constraint(step_events, c) for c in constraints):
                continue
            won = module_won or (is_win_fn is not None and is_win_fn(new_state))
            new_depth = depth + 1
            new_path = path + [action]
            if won:
                solutions.append(new_path)
                continue
            if new_depth >= max_depth:
                continue
            if prune_fn(new_state, info, new_depth, max_depth):
                continue
            if new_state in path_states:
                continue
            _dfs(new_state, new_path, path_states | {new_state})

    _dfs(initial, [], {initial})
    return solutions


# ---------------------------------------------------------------------------
# Monte Carlo difficulty measurement
# ---------------------------------------------------------------------------

def _monte_carlo(
    initial: Any,
    info: Any,
    module: Any,
    n_trials: int,
    max_steps: int,
    is_win_fn: Optional[Callable] = None,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Run N uniform-random rollouts and measure how often the level is solved.

    Uses a purely random agent (uniform over ACTIONS at each step).  This is
    intentionally simple — it measures how "lucky-solvable" a level is, which
    is a proxy for difficulty that does not depend on search algorithms.

    Returns a dict with solve_rate, successes, n_trials, step_counts.
    """
    rng = _random.Random(seed)
    actions = module.ACTIONS
    n_actions = len(actions)

    successes = 0
    step_counts: List[int] = []

    for _ in range(n_trials):
        state = initial
        for step in range(1, max_steps + 1):
            action = actions[rng.randrange(n_actions)]
            state, module_won, _ = module.apply(state, action, info)
            won = module_won or (is_win_fn is not None and is_win_fn(state))
            if won:
                successes += 1
                step_counts.append(step)
                break

    return {
        "solve_rate": successes / n_trials,
        "successes": successes,
        "n_trials": n_trials,
        "step_counts": step_counts,
        "max_steps": max_steps,
    }


def _print_mc_results(result: Dict[str, Any], optimal_len: Optional[int] = None) -> None:
    r = result
    sr = r["solve_rate"]
    print(f"Monte Carlo ({r['n_trials']:,} trials, max {r['max_steps']} steps/trial):")
    print(f"  Solve rate:  {sr * 100:.4f}%  "
          f"({r['successes']:,} / {r['n_trials']:,})")

    if r["step_counts"]:
        avg = statistics.mean(r["step_counts"])
        med = statistics.median(r["step_counts"])
        opt_note = f"  (optimal: {optimal_len})" if optimal_len else ""
        print(f"  Steps when solved:  avg {avg:.1f},  median {med:.0f}{opt_note}")

    if sr > 0:
        bits = -math.log2(sr)
        print(f"  Difficulty:  {bits:.1f} bits  "
              f"(random agent needs ~{1/sr:,.0f} attempts on average)")
    else:
        max_bits = math.log2(r["n_trials"])
        print(f"  Difficulty:  > {max_bits:.0f} bits  "
              f"(0 solves — increase --mc-trials for a tighter bound)")
    print()


# ---------------------------------------------------------------------------
# Event trace output
# ---------------------------------------------------------------------------

def _print_trace(path: List[str], initial: Any, module: Any, info: Any) -> None:
    """Re-simulate path and print a per-step event trace."""
    state = initial
    for step, action in enumerate(path, 1):
        new_state, _won, events = module.apply(state, action, info)
        print(f"    Step {step:2d}: {action}")
        for e in events:
            print(f"             {format_event(e)}")
        state = new_state


# ---------------------------------------------------------------------------
# Result printers (shared by all games)
# ---------------------------------------------------------------------------

def _print_results(
    solutions: List[List[str]],
    max_depth: int,
    gold_actions: Optional[List[str]],
    trace: bool,
    initial: Any,
    module: Any,
    info: Any,
    mode: str = "bfs",
) -> None:
    if not solutions:
        print(f"  No solution found within {max_depth} moves.")
        return

    solutions.sort(key=len)
    min_len = len(solutions[0])
    by_depth: Dict[int, List] = {}
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
            print(f"      {' '.join(a.upper() for a in p)}")
    print()

    if trace:
        best = solutions[0]
        print(f"  Trace ({len(best)} moves):")
        _print_trace(best, initial, module, info)
        print()

    if gold_actions:
        gold_str = " ".join(a.upper() for a in gold_actions)
        if gold_actions in solutions:
            print(f"  Gold path: ✓  {gold_str}")
        else:
            note = f"(not among the {len(solutions)} solutions found)"
            print(f"  Gold path: ✗  {gold_str}  {note}")

    shortest_count = len(by_depth.get(min_len, []))
    gold_len = len(gold_actions) if gold_actions else None
    print()
    if gold_len and min_len < gold_len:
        print(f"  ⚠  WARNING: a {min_len}-move solution exists "
              f"— shorter than the declared gold path ({gold_len} moves)!")
    elif mode == "dfs":
        # DFS is exhaustive: solution count is exact
        if shortest_count == 1:
            print(f"  ✓  UNIQUE: exactly one {min_len}-move solution exists.")
        else:
            print(f"  ✗  NOT UNIQUE: {shortest_count} solutions at depth {min_len}.")
    else:
        # BFS dedup can miss solutions sharing intermediate states with other paths
        if shortest_count == 1:
            print(f"  ✓  UNIQUE (BFS): no other shortest path found — "
                  f"use --mode dfs for exact count.")
        else:
            print(f"  ✗  NOT UNIQUE: {shortest_count} shortest paths found.")


def _print_astar_result(
    sol: Solution,
    gold_actions: Optional[List[str]],
    trace: bool,
    initial: Any,
    module: Any,
    info: Any,
    elapsed: Optional[float] = None,
) -> None:
    elapsed_str = f",  {elapsed:.2f}s" if elapsed is not None else ""
    if sol.timed_out:
        print(f"  Timed out after {sol.states_explored} states explored{elapsed_str}.")
        return
    if not sol.path:
        print(f"  No solution found.  States explored: {sol.states_explored}{elapsed_str}")
        if sol.is_optimal:
            print("  (search exhausted — proven no solution exists)")
        return

    print(f"Solution found: {sol.cost} move{'s' if sol.cost != 1 else ''}  "
          f"(states explored: {sol.states_explored}{elapsed_str})")
    print()
    print(f"  Path: {' '.join(a.upper() for a in sol.path)}")
    print()

    if trace:
        print(f"  Trace ({sol.cost} moves):")
        _print_trace(sol.path, initial, module, info)
        print()

    if gold_actions:
        gold_str = " ".join(a.upper() for a in gold_actions)
        if sol.path == gold_actions:
            print(f"  Gold path: ✓  {gold_str}")
        else:
            print(f"  Gold path: ✗  {gold_str}  (A* found a different path)")

    gold_len = len(gold_actions) if gold_actions else None
    print()
    if gold_len and sol.cost < gold_len:
        print(f"  ⚠  WARNING: a {sol.cost}-move solution exists "
              f"— shorter than the declared gold path ({gold_len} moves)!")
    elif sol.is_optimal:
        print(f"  ✓  OPTIMAL: A* confirmed this is the shortest solution.")


# ---------------------------------------------------------------------------
# JSON arg helpers
# ---------------------------------------------------------------------------

def _parse_json_arg(value: Optional[str]) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if value.startswith("@"):
        with open(value[1:]) as f:
            return json.load(f)
    return json.loads(value)


# ---------------------------------------------------------------------------
# Per-game solvers
# ---------------------------------------------------------------------------

def _solve_number_crunch(
    path: Path,
    level_json: Dict[str, Any],
    mode: str,
    max_depth: int,
    timeout: float,
    trace: bool,
    constraints: List[Dict],
    mc_trials: int = 0,
    mc_steps: int = 0,
) -> None:
    initial, info = nc.load(level_json)
    level_id = info.level_id or path.stem
    print(f"Solving  {level_id}   (mode: {mode}, max depth: {max_depth})")
    print(f"  Game:     Number Crunch")
    print(f"  Board:    {info.width}×{info.height}  ({len(info.void_cells)} void cells)")
    print(f"  Pipes:    {len(info.pipes)}", end="")
    for p in info.pipes:
        print(f"  queue={p.queue}", end="")
    print()
    print(f"  Sequence: {info.sequence}")
    if info.max_turns:
        print(f"  Max turns: {info.max_turns}")
    print()

    gold_raw = level_json.get("solution", {}).get("goldPath", [])
    gold_actions = [m["direction"] for m in gold_raw] if gold_raw else None
    optimal_len = len(gold_actions) if gold_actions else None

    if mode == "astar":
        _t0 = time.monotonic()
        sol = astar(initial, info, nc, timeout, constraints, max_depth=max_depth)
        _print_astar_result(sol, gold_actions, trace, initial, nc, info,
                            elapsed=time.monotonic() - _t0)
        if sol.path:
            optimal_len = sol.cost
    elif mode == "dfs":
        solutions = _dfs_all(initial, info, nc, max_depth, constraints=constraints)
        _print_results(solutions, max_depth, gold_actions, trace, initial, nc, info,
                       mode=mode)
    else:
        solutions = _bfs_shortest(initial, info, nc, max_depth, constraints=constraints)
        if gold_actions and solutions and gold_actions not in solutions:
            sim_state = initial
            for d in gold_actions:
                sim_state, _won, _ev = nc.apply(sim_state, d, info)
            if sim_state.seq_idx >= len(info.sequence):
                print("  (gold path is valid but longer than max-depth; "
                      "use --all-solutions)")
            else:
                print(f"  (gold simulation ends at seq_idx="
                      f"{sim_state.seq_idx}/{len(info.sequence)})")
        _print_results(solutions, max_depth, gold_actions, trace, initial, nc, info,
                       mode=mode)

    if mc_trials > 0:
        steps = mc_steps or max(100, 3 * (optimal_len or 20))
        print()
        result = _monte_carlo(initial, info, nc, mc_trials, steps)
        _print_mc_results(result, optimal_len)


def _solve_rotate_flip(
    path: Path,
    level_json: Dict[str, Any],
    mode: str,
    max_depth: int,
    timeout: float,
    trace: bool,
    constraints: List[Dict],
    mc_trials: int = 0,
    mc_steps: int = 0,
) -> None:
    initial, info = rf.load(level_json)
    level_id = info.level_id or path.stem
    print(f"Solving  {level_id}   (mode: {mode}, max depth: {max_depth})")
    print(f"  Game:   Rotate & Flip")
    print(f"  Board:  {info.cols}×{info.rows}  overlay {info.overlay_w}×{info.overlay_h}")
    print()

    gold_raw = level_json.get("solution", {}).get("goldPath", [])
    gold_actions = [
        f"move_{m['direction']}" if m.get("action") == "move" else m["action"]
        for m in gold_raw
    ] if gold_raw else None
    optimal_len = len(gold_actions) if gold_actions else None

    if mode == "astar":
        _t0 = time.monotonic()
        sol = astar(initial, info, rf, timeout, constraints, max_depth=max_depth)
        _print_astar_result(sol, gold_actions, trace, initial, rf, info,
                            elapsed=time.monotonic() - _t0)
        if sol.path:
            optimal_len = sol.cost
    elif mode == "dfs":
        solutions = _dfs_all(initial, info, rf, max_depth, constraints=constraints)
        _print_results(solutions, max_depth, gold_actions, trace, initial, rf, info,
                       mode=mode)
    else:
        solutions = _bfs_shortest(initial, info, rf, max_depth, constraints=constraints)
        _print_results(solutions, max_depth, gold_actions, trace, initial, rf, info,
                       mode=mode)

    if mc_trials > 0:
        steps = mc_steps or max(100, 3 * (optimal_len or 20))
        print()
        result = _monte_carlo(initial, info, rf, mc_trials, steps)
        _print_mc_results(result, optimal_len)


def _solve_box_builder(
    path: Path,
    level_json: Dict[str, Any],
    mode: str,
    max_depth: int,
    timeout: float,
    trace: bool,
    constraints: List[Dict],
    mc_trials: int = 0,
    mc_steps: int = 0,
    override_start: Optional[str] = None,
    partial_goal: Optional[str] = None,
) -> None:
    initial, info = bb.load(level_json)

    override_json = _parse_json_arg(override_start)
    if override_json is not None:
        initial = bb.override_initial_state(initial, override_json)

    partial_goal_json = _parse_json_arg(partial_goal)
    is_win_fn = (lambda s: bb.matches_waypoint(s, partial_goal_json)
                 if partial_goal_json is not None else None)
    # Heuristic pruning is based on the full win condition — skip for partial goals
    prune_fn = (lambda *a: False) if partial_goal_json is not None else bb.can_prune

    level_id = info.level_id or path.stem
    print(f"Solving  {level_id}   (mode: {mode}, max depth: {max_depth})")
    print(f"  Game:   Box Builder")
    print(f"  Board:  {info.width}×{info.height}  "
          f"({len(info.walls)} wall cells,  {len(info.targets)} target(s))")
    if override_json:
        print(f"  Start:  overridden")
    if partial_goal_json:
        print(f"  Goal:   partial waypoint")
    print()

    gold_raw = level_json.get("solution", {}).get("goldPath", [])
    gold_actions = (
        [m["direction"] for m in gold_raw if m.get("action") == "move"]
        if gold_raw else None
    )
    optimal_len = len(gold_actions) if gold_actions else None

    if mode == "astar":
        _t0 = time.monotonic()
        sol = astar(initial, info, bb, timeout, constraints, max_depth=max_depth,
                    is_win_fn=is_win_fn)
        _print_astar_result(sol, gold_actions, trace, initial, bb, info,
                            elapsed=time.monotonic() - _t0)
        if sol.path:
            optimal_len = sol.cost
    elif mode == "dfs":
        solutions = _dfs_all(initial, info, bb, max_depth,
                             is_win_fn=is_win_fn, constraints=constraints,
                             prune_fn=prune_fn)
        _print_results(solutions, max_depth, gold_actions, trace, initial, bb, info,
                       mode=mode)
    else:
        solutions = _bfs_shortest(initial, info, bb, max_depth,
                                  is_win_fn=is_win_fn, constraints=constraints,
                                  prune_fn=prune_fn)
        _print_results(solutions, max_depth, gold_actions, trace, initial, bb, info,
                       mode=mode)

    if mc_trials > 0:
        steps = mc_steps or max(100, 3 * (optimal_len or 30))
        print()
        result = _monte_carlo(initial, info, bb, mc_trials, steps,
                              is_win_fn=is_win_fn)
        _print_mc_results(result, optimal_len)


def _solve_flag_adventure(
    path: Path,
    level_json: Dict[str, Any],
    mode: str,
    max_depth: int,
    timeout: float,
    trace: bool,
    constraints: List[Dict],
    mc_trials: int = 0,
    mc_steps: int = 0,
) -> None:
    initial, info = fa.load(level_json)
    level_id = info.level_id or path.stem
    print(f"Solving  {level_id}   (mode: {mode}, max depth: {max_depth})")
    print(f"  Game:   Flag Adventure (Carrot Quest)")
    print(f"  Board:  {info.width}×{info.height}  "
          f"({len(info.water_cells)} water cell(s),  "
          f"{len(info.portals) // 2} portal pair(s))")
    print(f"  Flag:   {info.flag}")
    print()

    gold_raw = level_json.get("solution", {}).get("goldPath", [])
    gold_actions = [m["direction"] for m in gold_raw] if gold_raw else None
    optimal_len = len(gold_actions) if gold_actions else None

    if mode == "astar":
        sol = astar(initial, info, fa, timeout, constraints, max_depth=max_depth)
        _print_astar_result(sol, gold_actions, trace, initial, fa, info)
        if sol.path:
            optimal_len = sol.cost
    elif mode == "dfs":
        solutions = _dfs_all(initial, info, fa, max_depth, constraints=constraints)
        _print_results(solutions, max_depth, gold_actions, trace, initial, fa, info,
                       mode=mode)
    else:
        solutions = _bfs_shortest(initial, info, fa, max_depth, constraints=constraints)
        _print_results(solutions, max_depth, gold_actions, trace, initial, fa, info,
                       mode=mode)

    if mc_trials > 0:
        steps = mc_steps or max(100, 3 * (optimal_len or 30))
        print()
        result = _monte_carlo(initial, info, fa, mc_trials, steps)
        _print_mc_results(result, optimal_len)


# ---------------------------------------------------------------------------
# Generic engine-backed solver (diagonal_swipes, flood_colors, …)
# ---------------------------------------------------------------------------

def _solve_generic(
    path: Path,
    level_json: Dict[str, Any],
    game_label: str,
    mode: str,
    max_depth: int,
    timeout: float,
    trace: bool,
    constraints: List[Dict],
    mc_trials: int = 0,
    mc_steps: int = 0,
) -> None:
    pack_dir = path.parent.parent  # levels/xxx.json → pack root
    initial, info = ea.load(level_json, pack_dir)
    level_id = info.level_id or path.stem
    print(f"Solving  {level_id}   (mode: {mode}, max depth: {max_depth})")
    print(f"  Game:   {game_label}")
    print(f"  Board:  {info.width}×{info.height}")
    print(f"  Actions: {', '.join(info.ACTIONS)}")
    print()

    # Build a module-like object that binds ACTIONS to this game's action list,
    # compatible with the generic BFS/DFS/A*/MC callers that use module.ACTIONS.
    class _mod:
        ACTIONS = info.ACTIONS
        apply = staticmethod(ea.apply)
        can_prune = staticmethod(ea.can_prune)

    gold_actions = ea.gold_path_actions(level_json) or None
    optimal_len = len(gold_actions) if gold_actions else None

    if mode == "astar":
        _t0 = time.monotonic()
        sol = astar(initial, info, _mod, timeout, constraints, max_depth=max_depth)
        _print_astar_result(sol, gold_actions, trace, initial, _mod, info,
                            elapsed=time.monotonic() - _t0)
        if sol.path:
            optimal_len = sol.cost
    elif mode == "dfs":
        solutions = _dfs_all(initial, info, _mod, max_depth, constraints=constraints)
        _print_results(solutions, max_depth, gold_actions, trace, initial, _mod, info,
                       mode=mode)
    else:
        solutions = _bfs_shortest(initial, info, _mod, max_depth, constraints=constraints)
        _print_results(solutions, max_depth, gold_actions, trace, initial, _mod, info,
                       mode=mode)

    if mc_trials > 0:
        steps = mc_steps or max(100, 3 * (optimal_len or 20))
        print()
        result = _monte_carlo(initial, info, _mod, mc_trials, steps)
        _print_mc_results(result, optimal_len)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def solve(
    level_path: str,
    mode: str = "bfs",
    max_depth: int = 30,
    timeout: float = 60.0,
    trace: bool = False,
    constraints: Optional[List[Dict]] = None,
    mc_trials: int = 0,
    mc_steps: int = 0,
    **kwargs,
) -> None:
    path = Path(level_path)
    with open(path) as f:
        level_json: Dict[str, Any] = json.load(f)

    if constraints is None:
        constraints = []

    mc_kw = dict(mc_trials=mc_trials, mc_steps=mc_steps)
    game = _detect_game(path)
    if game == "rotate_flip":
        _solve_rotate_flip(path, level_json, mode, max_depth, timeout, trace,
                           constraints, **mc_kw)
    elif game == "box_builder":
        _solve_box_builder(path, level_json, mode, max_depth, timeout, trace,
                           constraints, **mc_kw,
                           override_start=kwargs.get("override_start"),
                           partial_goal=kwargs.get("partial_goal"))
    elif game == "number_crunch":
        _solve_number_crunch(path, level_json, mode, max_depth, timeout, trace,
                             constraints, **mc_kw)
    elif game == "flag_adventure":
        _solve_flag_adventure(path, level_json, mode, max_depth, timeout, trace,
                              constraints, **mc_kw)
    elif game == "diagonal_swipes":
        _solve_generic(path, level_json, "Diagonal Swipes", mode, max_depth, timeout,
                       trace, constraints, **mc_kw)
    elif game == "flood_colors":
        _solve_generic(path, level_json, "Flood Colors", mode, max_depth, timeout,
                       trace, constraints, **mc_kw)
    else:
        print(f"Error: unsupported game '{game}'", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="GridPonder puzzle solver.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("level", help="Path to the level JSON file")
    parser.add_argument(
        "--max-depth", type=int, default=30, metavar="N",
        help="Maximum moves to search (default: 30)",
    )
    parser.add_argument(
        "--mode", choices=["bfs", "dfs", "astar"], default="bfs",
        help="Search algorithm: bfs (default), dfs (all solutions), astar (optimal)",
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0, metavar="S",
        help="A* wall-clock timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--trace", action="store_true",
        help="Print per-step event trace for the best solution",
    )
    parser.add_argument(
        "--constraint", action="append", default=[], metavar="JSON",
        dest="constraints",
        help='Constraint dict (repeatable). '
             '{"type":"must_not","event":"object_removed","kind":"rock"}',
    )
    parser.add_argument(
        "--mc-trials", type=int, default=0, metavar="N",
        help="Run N random rollouts to measure difficulty (0 = disabled)",
    )
    parser.add_argument(
        "--mc-steps", type=int, default=0, metavar="N",
        help="Max steps per Monte Carlo trial (default: 3 × gold path length)",
    )
    parser.add_argument(
        "--all-solutions", action="store_true",
        help="Alias for --mode dfs",
    )
    parser.add_argument(
        "--override-start", metavar="JSON",
        help="Override initial board state (box_builder). JSON string or @file.",
    )
    parser.add_argument(
        "--partial-goal", metavar="JSON",
        help="Use a partial intermediate goal (box_builder). JSON string or @file.",
    )
    args = parser.parse_args()

    mode = "dfs" if args.all_solutions else args.mode
    constraints = [json.loads(c) for c in args.constraints]

    solve(
        args.level,
        mode=mode,
        max_depth=args.max_depth,
        timeout=args.timeout,
        trace=args.trace,
        constraints=constraints,
        mc_trials=args.mc_trials,
        mc_steps=args.mc_steps,
        override_start=args.override_start,
        partial_goal=args.partial_goal,
    )


if __name__ == "__main__":
    main()
