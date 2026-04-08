#!/usr/bin/env python3
"""
Classic Flood-It Solver
=======================
Reads a flood_colors level JSON (new format with cell_flooded start cell) and
finds the minimum number of colour-picks needed to flood the entire board.

The flood region starts at every cell whose kind is "cell_flooded".
Each move picks one colour; all cells of that colour reachable (via a
connected path of the same colour) from the current flood region join it.

Algorithm
---------
BFS over board states for small boards (≤ 8×8 with ≤ 5 colours, or ≤ 7×7
with 6 colours).  Falls back to a greedy heuristic for larger boards and
prints a warning.

State representation: tuple of cell kinds, row-major (y * width + x).

Usage
-----
    python3 tools/solver/games/classic_flood_solver.py packs/flood_colors/levels/fl_001.json
    python3 tools/solver/games/classic_flood_solver.py packs/flood_colors/levels/
"""

import json
import sys
from collections import deque
from pathlib import Path
from typing import Optional

FLOODED_KIND = "cell_flooded"
WALL_KINDS   = {"cell_wall"}

# --------------------------------------------------------------------------- #
# Board loading                                                                #
# --------------------------------------------------------------------------- #

def load_grid(level_path: Path) -> tuple[int, int, list[Optional[str]]]:
    """Return (width, height, flat_grid) where flat_grid[y*w+x] = kind | None."""
    with open(level_path) as f:
        data = json.load(f)

    board = data["board"]
    width, height = board["size"]
    flat: list[Optional[str]] = [None] * (width * height)

    obj_layer = board["layers"].get("objects")
    if obj_layer is None:
        return width, height, flat

    if isinstance(obj_layer, list):          # dense row-major
        for y, row in enumerate(obj_layer):
            for x, cell in enumerate(row):
                if isinstance(cell, str):
                    flat[y * width + x] = cell
                elif isinstance(cell, dict):
                    flat[y * width + x] = cell.get("kind")
    elif isinstance(obj_layer, dict):        # sparse
        for entry in obj_layer.get("entries", []):
            x, y = entry["position"]
            flat[y * width + x] = entry.get("kind")

    return width, height, flat


# --------------------------------------------------------------------------- #
# Flood-region expansion                                                       #
# --------------------------------------------------------------------------- #

def expand(state: tuple, width: int, height: int, colour: str) -> tuple:
    """Return new state after picking `colour`.  Returns same state if no-op."""
    grid = list(state)

    # Find all flooded cells.
    flooded = {i for i, k in enumerate(grid) if k == FLOODED_KIND}
    if not flooded:
        return state

    # BFS seeds: target-colour cells adjacent to flooded region.
    visited = set(flooded)
    queue: deque[int] = deque()

    def neighbours(i: int):
        x, y = i % width, i // width
        if x > 0:            yield i - 1
        if x < width - 1:    yield i + 1
        if y > 0:            yield i - width
        if y < height - 1:   yield i + width

    for fi in flooded:
        for nb in neighbours(fi):
            if nb not in visited and grid[nb] == colour:
                visited.add(nb)
                queue.append(nb)

    if not queue:
        return state  # nothing adjacent — no-op

    # BFS through connected colour cells.
    changed: list[int] = []
    while queue:
        cur = queue.popleft()
        changed.append(cur)
        for nb in neighbours(cur):
            if nb not in visited and grid[nb] == colour:
                visited.add(nb)
                queue.append(nb)

    for i in changed:
        grid[i] = FLOODED_KIND

    return tuple(grid)


def is_solved(state: tuple) -> bool:
    return all(k is None or k == FLOODED_KIND or k in WALL_KINDS
               for k in state)


def colours_present(state: tuple) -> list[str]:
    return sorted({k for k in state
                   if k and k != FLOODED_KIND and k not in WALL_KINDS})


# --------------------------------------------------------------------------- #
# BFS solver (exact, exponential)                                              #
# --------------------------------------------------------------------------- #

BFS_STATE_LIMIT = 5_000_000   # abort BFS above this many states


def solve_bfs(
    initial: tuple, width: int, height: int
) -> Optional[list[str]]:
    """Return optimal colour sequence, or None if BFS limit exceeded."""
    if is_solved(initial):
        return []

    colours = colours_present(initial)

    # BFS: state → path
    frontier: deque[tuple[tuple, list[str]]] = deque()
    frontier.append((initial, []))
    seen: dict[tuple, int] = {initial: 0}
    states_explored = 0

    while frontier:
        state, path = frontier.popleft()
        states_explored += 1

        if states_explored > BFS_STATE_LIMIT:
            return None

        for colour in colours:
            new_state = expand(state, width, height, colour)
            if new_state is state:          # no-op — skip
                continue
            depth = len(path) + 1
            if new_state in seen and seen[new_state] <= depth:
                continue
            seen[new_state] = depth
            new_path = path + [colour]
            if is_solved(new_state):
                return new_path
            frontier.append((new_state, new_path))

    return None   # unsolvable (shouldn't happen on valid levels)


# --------------------------------------------------------------------------- #
# Greedy solver (heuristic, for large boards)                                  #
# --------------------------------------------------------------------------- #

def solve_greedy(initial: tuple, width: int, height: int) -> list[str]:
    """Greedy: always pick the colour that maximises flood-region growth."""
    state = initial
    path: list[str] = []
    while not is_solved(state):
        colours = colours_present(state)
        if not colours:
            break
        best_colour = max(
            colours,
            key=lambda c: sum(
                1 for k in expand(state, width, height, c) if k == FLOODED_KIND
            ) - sum(1 for k in state if k == FLOODED_KIND)
        )
        new_state = expand(state, width, height, best_colour)
        if new_state is state:
            break   # stuck (shouldn't happen)
        state = new_state
        path.append(best_colour)
    return path


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #

def solve(level_path: Path) -> None:
    width, height, flat = load_grid(level_path)
    initial = tuple(flat)

    n_colours = len(colours_present(initial))
    board_cells = width * height

    # Heuristic BFS feasibility check (very rough).
    use_bfs = board_cells <= 49 or (board_cells <= 64 and n_colours <= 5)

    print(f"\n{'='*54}")
    print(f"Level : {level_path.name}")
    print(f"Board : {width}×{height}  ({n_colours} colours)")

    if use_bfs:
        path = solve_bfs(initial, width, height)
        if path is None:
            print("BFS limit exceeded — falling back to greedy.")
            path = solve_greedy(initial, width, height)
            method = "greedy (≥ optimal)"
        else:
            method = "optimal (BFS)"
    else:
        print("Board too large for BFS — using greedy heuristic.")
        path = solve_greedy(initial, width, height)
        method = "greedy (≥ optimal)"

    print(f"Moves : {len(path)}  [{method}]")
    print(f"Path  : {' → '.join(path)}")
    print()

    # colour is a full kind like "cell_red"; action id strips "cell_" prefix
    def action_id(c: str) -> str:
        return f'flood_{c[5:]}' if c.startswith('cell_') else f'flood_{c}'

    print("Gold path (JSON actions):")
    for colour in path:
        print(f'  {{"action": "{action_id(colour)}"}}')

    n = len(path)
    print()
    print("Suggested move limits:")
    print(f"  Tutorial (+2): {n + 2}")
    print(f"  Normal   (+1): {n + 1}")
    print(f"  Tight    (±0): {n}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: classic_flood_solver.py <level.json | levels_dir/>")
        sys.exit(1)

    target = Path(sys.argv[1])
    if target.is_dir():
        files = sorted(target.glob("fl_*.json"))
        if not files:
            print(f"No fl_*.json files in {target}")
            sys.exit(1)
        for p in files:
            solve(p)
    elif target.is_file():
        solve(target)
    else:
        print(f"Path not found: {target}")
        sys.exit(1)


if __name__ == "__main__":
    main()
