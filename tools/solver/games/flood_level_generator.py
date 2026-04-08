#!/usr/bin/env python3
"""
Flood Colors — Level Generator
================================
Generates random boards, solves them, measures MC difficulty, and
outputs candidate level JSONs that hit a target difficulty tier.

Usage
-----
    python3 tools/solver/games/flood_level_generator.py \
        --tier easy --count 5 --out packs/flood_colors/levels/

Tiers
-----
    easy       MC ≥ 50%    (slack 1-2, small boards)
    medium     MC 15-50%   (tight or zero slack)
    hard       MC 5-15%    (zero slack, larger boards)
    vhard      MC < 5%     (zero/negative slack, complex boards)
"""

import argparse
import json
import random
import sys
from collections import deque
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------- #
# Core flood logic (shared with solver)                                        #
# --------------------------------------------------------------------------- #

FLOODED_KIND = "cell_flooded"
WALL_KINDS   = {"cell_wall"}
ALL_COLORS   = ["cell_red", "cell_blue", "cell_yellow",
                "cell_orange", "cell_purple", "cell_teal"]


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
    return [c for c in colours_present(state) if expand(state, w, h, c) is not state]


BFS_LIMIT = 4_000_000

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


def monte_carlo(initial: tuple, w: int, h: int, limit: int,
                n: int = 3000, seed: int = 42) -> float:
    rng = random.Random(seed)
    wins = 0
    for _ in range(n):
        state = initial
        for _ in range(limit):
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
    return wins / n


# --------------------------------------------------------------------------- #
# Board generation                                                              #
# --------------------------------------------------------------------------- #

def random_board(w: int, h: int, n_colors: int, rng: random.Random) -> tuple:
    """Pure random assignment — each cell picks a random color."""
    colors = ALL_COLORS[:n_colors]
    grid = [rng.choice(colors) for _ in range(w * h)]
    grid[0] = FLOODED_KIND
    return tuple(grid)


def regional_board(w: int, h: int, n_colors: int, rng: random.Random,
                   region_size: int = 3) -> tuple:
    """Grow random colored regions — creates smoother patches like real puzzles."""
    colors = ALL_COLORS[:n_colors]
    grid = [None] * (w * h)
    grid[0] = FLOODED_KIND

    # Seed one region per color, then flood-fill with noise
    unassigned = set(range(1, w * h))
    seeds = rng.sample(list(unassigned), min(n_colors * 2, len(unassigned)))
    for i, seed in enumerate(seeds):
        grid[seed] = colors[i % n_colors]
        unassigned.discard(seed)

    # BFS growth from seeds
    for _ in range(w * h * 3):
        if not unassigned:
            break
        # Pick a random assigned neighbour of an unassigned cell
        idx = rng.choice(list(unassigned))
        nbs = [nb for nb in neighbours(idx, w, h) if grid[nb] is not None]
        if nbs:
            grid[idx] = grid[rng.choice(nbs)]
            unassigned.discard(idx)

    # Fill any remaining gaps
    for i in unassigned:
        grid[i] = rng.choice(colors)

    return tuple(grid)


# --------------------------------------------------------------------------- #
# Tier specifications                                                           #
# --------------------------------------------------------------------------- #

TIERS = {
    "easy":   {"mc_min": 50,  "mc_max": 100, "slack_add": 1},
    "medium": {"mc_min": 15,  "mc_max": 50,  "slack_add": 0},
    "hard":   {"mc_min": 5,   "mc_max": 15,  "slack_add": 0},
    "vhard":  {"mc_min": 0,   "mc_max": 5,   "slack_add": 0},
}

# Board specs to try for each tier (w, h, n_colors)
TIER_SPECS = {
    "easy":   [(4, 4, 3), (5, 5, 3), (5, 5, 4)],
    "medium": [(6, 6, 4), (6, 6, 5), (7, 7, 5)],
    "hard":   [(7, 7, 5), (8, 8, 5), (8, 8, 6), (9, 9, 5)],
    "vhard":  [(8, 8, 6), (9, 9, 6), (10, 10, 6), (11, 11, 6)],
}


def try_generate_candidate(tier: str, rng: random.Random, mc_trials: int = 3000,
                            max_attempts: int = 500) -> Optional[dict]:
    spec_list = TIER_SPECS[tier]
    tspec = TIERS[tier]

    for attempt in range(max_attempts):
        w, h, nc = rng.choice(spec_list)
        state = regional_board(w, h, nc, rng)
        colors_in = colours_present(state)
        if len(colors_in) < nc:
            continue  # not all colors present

        # Solve
        use_bfs = w * h <= 49 or (w * h <= 64 and nc <= 5)
        if use_bfs:
            sol = solve_bfs(state, w, h)
            method = "BFS"
        else:
            sol = None
            method = "greedy"

        if sol is None:
            sol = solve_greedy(state, w, h)
            method = "greedy"

        opt = len(sol)
        if opt < 3:
            continue  # trivially simple

        limit = opt + tspec["slack_add"]

        # MC difficulty check
        mc = monte_carlo(state, w, h, limit, n=mc_trials) * 100
        if tspec["mc_min"] <= mc <= tspec["mc_max"]:
            return {
                "w": w, "h": h, "n_colors": nc,
                "state": state,
                "solution": sol,
                "opt": opt,
                "limit": limit,
                "mc_pct": mc,
                "method": method,
            }

    return None


# --------------------------------------------------------------------------- #
# Level JSON writer                                                             #
# --------------------------------------------------------------------------- #

TITLES = {
    1: "First Splash",  2: "Two Shores",    3: "Triple Cross",
    4: "Four Corners",  5: "Patchwork",     6: "Tangle",
    7: "The Squeeze",   8: "Five Fronts",   9: "Labyrinth",
    10: "Edge Case",    11: "Six Streams",  12: "The Maze",
    13: "Deep Current", 14: "Color Storm",  15: "Undertow",
    16: "Convergence",  17: "The Knot",     18: "Cascade",
    19: "Whirlpool",    20: "Flood Finale",
}

COLOR_NAMES = {
    "cell_red": "red", "cell_blue": "blue", "cell_yellow": "yellow",
    "cell_orange": "orange", "cell_purple": "purple", "cell_teal": "teal",
}


def build_level_json(idx: int, candidate: dict) -> dict:
    w, h = candidate["w"], candidate["h"]
    state = candidate["state"]
    sol = candidate["solution"]
    limit = candidate["limit"]

    # Build 2D grid
    grid_2d = []
    for y in range(h):
        row = []
        for x in range(w):
            row.append(state[y * w + x])
        grid_2d.append(row)

    colors_in = colours_present(state)
    goals = [{"id": f"no_{COLOR_NAMES[c]}", "type": "all_cleared",
              "config": {"kind": c}} for c in colors_in]

    gold_path = [{"action": f"flood_{COLOR_NAMES[c]}"} for c in sol]

    # One hint at the midpoint
    hint_stops = [len(sol) // 2] if len(sol) >= 4 else [1]

    return {
        "id": f"fl_{idx:03d}",
        "title": TITLES.get(idx, f"Level {idx}"),
        "board": {
            "size": [w, h],
            "layers": {"objects": grid_2d},
        },
        "state": {
            "avatar": {"enabled": False, "position": [0, 0], "facing": "right"},
            "variables": {},
        },
        "goals": goals,
        "loseConditions": [{"type": "max_actions", "config": {"limit": limit}}],
        "solution": {
            "goldPath": gold_path,
            "hintStops": hint_stops,
        },
        "metadata": {
            "description": f"{w}x{h} board, {len(colors_in)} colours, opt={candidate['opt']}, mc={candidate['mc_pct']:.1f}%",
            "difficulty": idx,
        },
    }


# --------------------------------------------------------------------------- #
# CLI                                                                           #
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=list(TIERS), required=True)
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--out", required=True, help="Output directory")
    ap.add_argument("--start-idx", type=int, default=1, help="First level index")
    ap.add_argument("--trials", type=int, default=3000, help="MC trials per board")
    ap.add_argument("--seed", type=int, default=12345)
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    print(f"Generating {args.count} '{args.tier}' levels starting at index {args.start_idx}...")
    found = 0
    attempts_total = 0
    while found < args.count:
        attempts_total += 1
        if attempts_total > 50000:
            print("Giving up — too many attempts. Loosen tier bounds or adjust specs.")
            break
        cand = try_generate_candidate(args.tier, rng, mc_trials=args.trials)
        if cand is None:
            continue
        idx = args.start_idx + found
        level_json = build_level_json(idx, cand)
        out_path = out_dir / f"fl_{idx:03d}.json"
        with open(out_path, "w") as f:
            json.dump(level_json, f, indent=2)
        print(f"  fl_{idx:03d}  {cand['w']}x{cand['h']} c={cand['n_colors']} "
              f"opt={cand['opt']} lim={cand['limit']} mc={cand['mc_pct']:.1f}%  [{cand['method']}]  → {out_path}")
        found += 1

    print(f"Done. {found}/{args.count} levels written.")


if __name__ == "__main__":
    main()
