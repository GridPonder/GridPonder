#!/usr/bin/env python3
"""
Flood Colors — Difficulty Analyser
===================================
For each level:
  1. Finds the optimal solution length via BFS (or greedy for large boards).
  2. Runs N Monte Carlo trials: at every step pick a random non-no-op action;
     score = fraction of trials that solve within the move limit.
  3. Prints a summary table.

Usage
-----
    python3 tools/solver/games/flood_difficulty.py packs/flood_colors/levels/
    python3 tools/solver/games/flood_difficulty.py packs/flood_colors/levels/fl_010.json
"""

import json
import random
import sys
from collections import deque
from pathlib import Path
from typing import Optional

# ---- Re-use core logic from classic_flood_solver -------------------------

FLOODED_KIND = "cell_flooded"
WALL_KINDS   = {"cell_wall"}

def load_level(path: Path):
    with open(path) as f:
        data = json.load(f)
    board = data["board"]
    w, h = board["size"]
    flat = [None] * (w * h)
    obj_layer = board["layers"].get("objects")
    if obj_layer and isinstance(obj_layer, list):
        for y, row in enumerate(obj_layer):
            for x, cell in enumerate(row):
                flat[y * w + x] = cell if isinstance(cell, str) else None
    limit = None
    for lc in data.get("loseConditions", []):
        if lc.get("type") == "max_actions":
            limit = lc["config"]["limit"]
    gold_path = data.get("solution", {}).get("goldPath", [])
    return w, h, tuple(flat), limit, len(gold_path)


def neighbours(i: int, w: int, h: int):
    x, y = i % w, i // w
    if x > 0:          yield i - 1
    if x < w - 1:      yield i + 1
    if y > 0:          yield i - w
    if y < h - 1:      yield i + w


def expand(state: tuple, w: int, h: int, colour: str) -> tuple:
    grid = list(state)
    flooded = {i for i, k in enumerate(grid) if k == FLOODED_KIND}
    if not flooded:
        return state
    visited = set(flooded)
    queue: deque[int] = deque()
    for fi in flooded:
        for nb in neighbours(fi, w, h):
            if nb not in visited and grid[nb] == colour:
                visited.add(nb)
                queue.append(nb)
    if not queue:
        return state
    changed = []
    while queue:
        cur = queue.popleft()
        changed.append(cur)
        for nb in neighbours(cur, w, h):
            if nb not in visited and grid[nb] == colour:
                visited.add(nb)
                queue.append(nb)
    for i in changed:
        grid[i] = FLOODED_KIND
    return tuple(grid)


def is_solved(state: tuple) -> bool:
    return all(k is None or k == FLOODED_KIND or k in WALL_KINDS for k in state)


def colours_present(state: tuple) -> list[str]:
    return sorted({k for k in state if k and k != FLOODED_KIND and k not in WALL_KINDS})


def valid_moves(state: tuple, w: int, h: int) -> list[str]:
    """Return colours that produce a non-no-op move."""
    return [c for c in colours_present(state) if expand(state, w, h, c) is not state]


# ---- BFS solver (exact, fast for small boards) ---------------------------

BFS_LIMIT = 3_000_000

def solve_bfs(initial: tuple, w: int, h: int) -> Optional[list[str]]:
    if is_solved(initial):
        return []
    colours = colours_present(initial)
    frontier: deque = deque([(initial, [])])
    seen: dict = {initial: 0}
    explored = 0
    while frontier:
        state, path = frontier.popleft()
        explored += 1
        if explored > BFS_LIMIT:
            return None
        for c in colours:
            ns = expand(state, w, h, c)
            if ns is state:
                continue
            d = len(path) + 1
            if ns in seen and seen[ns] <= d:
                continue
            seen[ns] = d
            np = path + [c]
            if is_solved(ns):
                return np
            frontier.append((ns, np))
    return None


def solve_greedy(initial: tuple, w: int, h: int) -> list[str]:
    state, path = initial, []
    while not is_solved(state):
        colours = colours_present(state)
        if not colours:
            break
        best = max(colours,
                   key=lambda c: sum(1 for k in expand(state, w, h, c) if k == FLOODED_KIND))
        ns = expand(state, w, h, best)
        if ns is state:
            break
        state, path = ns, path + [best]
    return path


# ---- Monte Carlo estimator -----------------------------------------------

def monte_carlo(initial: tuple, w: int, h: int, limit: int,
                n_trials: int = 2000, rng: random.Random = None) -> float:
    """Return fraction of random-play trials that solve within `limit` moves."""
    if rng is None:
        rng = random.Random(42)
    wins = 0
    for _ in range(n_trials):
        state = initial
        for step in range(limit):
            if is_solved(state):
                wins += 1
                break
            moves = valid_moves(state, w, h)
            if not moves:
                break
            state = expand(state, w, h, rng.choice(moves))
        else:
            if is_solved(state):
                wins += 1
    return wins / n_trials


# ---- Entry point ---------------------------------------------------------

def analyse(path: Path, n_trials: int = 2000) -> dict:
    w, h, initial, limit, gold_len = load_level(path)
    n_colours = len(colours_present(initial))

    # Optimal solution
    use_bfs = w * h <= 49 or (w * h <= 64 and n_colours <= 5)
    if use_bfs:
        path_sol = solve_bfs(initial, w, h)
        method = "BFS"
    else:
        path_sol = None
        method = "?"
    if path_sol is None:
        path_sol = solve_greedy(initial, w, h)
        method = "greedy≥"

    opt = len(path_sol)
    eff_limit = limit if limit is not None else opt

    # Monte Carlo difficulty
    mc = monte_carlo(initial, w, h, eff_limit, n_trials=n_trials)

    return {
        "file": path.name,
        "size": f"{w}x{h}",
        "colours": n_colours,
        "optimal": opt,
        "gold_path_len": gold_len,
        "limit": eff_limit,
        "slack": eff_limit - opt,
        "mc_win_pct": mc * 100,
        "method": method,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: flood_difficulty.py <level.json | levels_dir/> [n_trials]")
        sys.exit(1)

    target = Path(sys.argv[1])
    n_trials = int(sys.argv[2]) if len(sys.argv) > 2 else 2000

    if target.is_dir():
        files = sorted(target.glob("fl_*.json"))
    else:
        files = [target]

    if not files:
        print(f"No fl_*.json files in {target}")
        sys.exit(1)

    print(f"\n{'Level':<12} {'Size':<8} {'C':>2} {'Opt':>4} {'Gold':>5} {'Lim':>4} {'Slack':>5}  {'MC%':>6}  Method")
    print("-" * 64)
    results = []
    for p in files:
        r = analyse(p, n_trials=n_trials)
        results.append(r)
        bar = "█" * int(r["mc_win_pct"] / 5)
        print(
            f"{r['file']:<12} {r['size']:<8} {r['colours']:>2} {r['optimal']:>4} "
            f"{r['gold_path_len']:>5} {r['limit']:>4} {r['slack']:>5}  "
            f"{r['mc_win_pct']:>5.1f}%  {r['method']}  {bar}"
        )

    print()
    avg = sum(r["mc_win_pct"] for r in results) / len(results)
    print(f"Average random-win %: {avg:.1f}%")
    print()
    print("Difficulty guide: >60% easy  |  30-60% medium  |  10-30% hard  |  <10% very hard")


if __name__ == "__main__":
    main()
