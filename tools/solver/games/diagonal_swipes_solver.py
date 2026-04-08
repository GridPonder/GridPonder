#!/usr/bin/env python3
"""
Diagonal Swipes BFS Solver
===========================
State: (objects_flat_tuple, overlay_x, overlay_y, avatar_x, avatar_y)

Usage:
    python3 tools/solver/games/diagonal_swipes_solver.py packs/diagonal_swipes/levels/ds_002.json
    python3 tools/solver/games/diagonal_swipes_solver.py packs/diagonal_swipes/levels/  # all levels
"""

import json, sys
from collections import deque
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------- #
# Board loading                                                                #
# --------------------------------------------------------------------------- #

def load_level(path: Path) -> dict:
    with open(path) as f:
        data = json.load(f)

    board = data["board"]
    w, h = board["size"]

    # Ground layer (for voids)
    ground = [None] * (w * h)  # None = empty (walkable)
    ground_layer = board.get("layers", {}).get("ground")
    if ground_layer:
        if isinstance(ground_layer, list):  # dense
            for y, row in enumerate(ground_layer):
                for x, cell in enumerate(row):
                    if cell == "void":
                        ground[y * w + x] = "void"
        elif isinstance(ground_layer, dict):  # sparse
            for entry in ground_layer.get("entries", []):
                x, y = entry["position"]
                if entry.get("kind") == "void":
                    ground[y * w + x] = "void"

    # Objects layer
    objects = [None] * (w * h)
    obj_layer = board.get("layers", {}).get("objects")
    if obj_layer:
        if isinstance(obj_layer, list):  # dense
            for y, row in enumerate(obj_layer):
                for x, cell in enumerate(row):
                    if isinstance(cell, str) and cell.startswith("num_"):
                        objects[y * w + x] = cell
                    elif isinstance(cell, dict) and cell.get("kind", "").startswith("num_"):
                        objects[y * w + x] = cell["kind"]
        elif isinstance(obj_layer, dict):  # sparse
            for entry in obj_layer.get("entries", []):
                x, y = entry["position"]
                kind = entry.get("kind")
                if kind and kind.startswith("num_"):
                    objects[y * w + x] = kind

    # Start state
    st = data.get("state", {})
    av = st.get("avatar", {})
    ax, ay = av.get("position", [0, 0])
    ov = st.get("overlay", {})
    ox, oy = ov.get("position", [0, 0])

    # Goals
    goals = data.get("goals", [])

    # Move limit
    limit = None
    for lc in data.get("loseConditions", []):
        if lc.get("type") == "max_actions":
            limit = lc["config"]["limit"]

    return {
        "w": w, "h": h,
        "ground": tuple(ground),
        "objects": tuple(objects),
        "ax": ax, "ay": ay,
        "ox": ox, "oy": oy,
        "goals": goals,
        "limit": limit,
        "gold_path": data.get("solution", {}).get("goldPath", []),
    }


# --------------------------------------------------------------------------- #
# Goal evaluation                                                              #
# --------------------------------------------------------------------------- #

def check_goals(objects: tuple, w: int, h: int, goals: list) -> bool:
    for goal in goals:
        if goal["type"] == "board_match":
            if not _check_board_match(objects, w, h, goal["config"]):
                return False
        elif goal["type"] == "sum_constraint":
            if not _check_sum_constraint(objects, w, h, goal["config"]):
                return False
        elif goal["type"] == "count_constraint":
            if not _check_count_constraint(objects, w, h, goal["config"]):
                return False
    return True


def _check_board_match(objects: tuple, w: int, h: int, config: dict) -> bool:
    target_layers = config.get("targetLayers", {})
    mode = config.get("matchMode", "exact_non_null")
    target = target_layers.get("objects")
    if target is None:
        return True
    for y, row in enumerate(target):
        for x, cell in enumerate(row):
            if mode == "exact_non_null" and cell is None:
                continue
            actual = objects[y * w + x]
            target_kind = cell if isinstance(cell, str) else (cell.get("kind") if isinstance(cell, dict) else None)
            if actual != target_kind:
                return False
    return True


def _check_sum_constraint(objects: tuple, w: int, h: int, config: dict) -> bool:
    scope = config.get("scope", "board")
    target = config["target"]
    cmp = config.get("comparison", "eq")

    def cell_val(x, y):
        kind = objects[y * w + x]
        if kind and kind.startswith("num_"):
            return int(kind[4:])
        return 0

    def check(s):
        if cmp == "eq": return s == target
        if cmp == "gte": return s >= target
        if cmp == "lte": return s <= target
        return False

    if scope == "all_rows":
        return all(check(sum(cell_val(x, y) for x in range(w))) for y in range(h))
    elif scope == "all_cols":
        return all(check(sum(cell_val(x, y) for y in range(h))) for x in range(w))
    elif scope == "row":
        idx = config.get("index", 0)
        return check(sum(cell_val(x, idx) for x in range(w)))
    elif scope == "col":
        idx = config.get("index", 0)
        return check(sum(cell_val(idx, y) for y in range(h)))
    return False


def _check_count_constraint(objects: tuple, w: int, h: int, config: dict) -> bool:
    scope = config.get("scope", "all_rows")
    predicate = config.get("predicate", "even")
    target = config["target"]
    cmp = config.get("comparison", "eq")

    def cell_val(x, y):
        kind = objects[y * w + x]
        if kind and kind.startswith("num_"):
            return int(kind[4:])
        return 0

    def matches_pred(value):
        if predicate == "even": return value % 2 == 0
        if predicate == "odd": return value % 2 != 0
        if predicate.startswith("gte_"): return value >= int(predicate[4:])
        if predicate.startswith("lte_"): return value <= int(predicate[4:])
        if predicate.startswith("eq_"): return value == int(predicate[3:])
        return False

    def has_entity(x, y):
        kind = objects[y * w + x]
        return kind is not None

    def row_count(y):
        return sum(1 for x in range(w) if has_entity(x, y) and matches_pred(cell_val(x, y)))

    def col_count(x):
        return sum(1 for y in range(h) if has_entity(x, y) and matches_pred(cell_val(x, y)))

    def check(c):
        if cmp == "eq": return c == target
        if cmp == "gte": return c >= target
        if cmp == "lte": return c <= target
        return False

    if scope == "all_rows":
        return all(check(row_count(y)) for y in range(h))
    elif scope == "all_cols":
        return all(check(col_count(x)) for x in range(w))
    elif scope == "row":
        idx = config.get("index", 0)
        return check(row_count(idx))
    elif scope == "col":
        idx = config.get("index", 0)
        return check(col_count(idx))
    return False


# --------------------------------------------------------------------------- #
# State transitions                                                            #
# --------------------------------------------------------------------------- #

DIRECTIONS = {
    "up":    (0, -1),
    "down":  (0,  1),
    "left":  (-1, 0),
    "right": (1,  0),
}


def apply_move(objects, ground, w, h, ax, ay, ox, oy, direction):
    """Apply a move action. Returns (new_ax, new_ay, new_ox, new_oy) or None if no-op."""
    dx, dy = DIRECTIONS[direction]

    # Avatar movement (blocked by bounds and void)
    nax, nay = ax + dx, ay + dy
    if not (0 <= nax < w and 0 <= nay < h) or ground[nay * w + nax] == "void":
        nax, nay = ax, ay  # blocked

    # Overlay movement (clamped to bounds)
    nox = max(0, min(w - 2, ox + dx))
    noy = max(0, min(h - 2, oy + dy))

    if nax == ax and nay == ay and nox == ox and noy == oy:
        return None  # complete no-op
    return (nax, nay, nox, noy)


def apply_swap(objects, ground, w, h, ox, oy, swap_dir):
    """Apply a diagonal swap. Returns new objects tuple or None if no-op."""
    if swap_dir in ("down_right", "up_left"):
        a_idx = oy * w + ox              # top-left
        b_idx = (oy + 1) * w + (ox + 1)  # bottom-right
    else:  # down_left / up_right
        a_idx = oy * w + (ox + 1)        # top-right
        b_idx = (oy + 1) * w + ox        # bottom-left

    # Check void
    if ground[a_idx] == "void" or ground[b_idx] == "void":
        return None

    # Check if swap changes anything
    if objects[a_idx] == objects[b_idx]:
        return None  # no-op (same values or both empty)

    lst = list(objects)
    lst[a_idx], lst[b_idx] = lst[b_idx], lst[a_idx]
    return tuple(lst)


# --------------------------------------------------------------------------- #
# BFS solver                                                                   #
# --------------------------------------------------------------------------- #

BFS_LIMIT = 5_000_000

def solve(level: dict, max_depth: int = 30) -> Optional[list]:
    w, h = level["w"], level["h"]
    ground = level["ground"]
    goals = level["goals"]

    if not goals:
        return None

    initial_objects = level["objects"]
    initial_state = (initial_objects, level["ox"], level["oy"], level["ax"], level["ay"])

    if check_goals(initial_objects, w, h, goals):
        return []  # already solved

    # BFS
    frontier = deque([(initial_state, [])])
    seen = {initial_state}
    explored = 0

    while frontier:
        state, path = frontier.popleft()
        explored += 1

        if explored > BFS_LIMIT:
            print(f"  BFS limit ({BFS_LIMIT:,}) exceeded at depth {len(path)}")
            return None

        if len(path) >= max_depth:
            continue

        objects, ox, oy, ax, ay = state

        # Try moves
        for direction in ("up", "down", "left", "right"):
            result = apply_move(objects, ground, w, h, ax, ay, ox, oy, direction)
            if result is None:
                continue
            nax, nay, nox, noy = result
            new_state = (objects, nox, noy, nax, nay)
            if new_state not in seen:
                seen.add(new_state)
                new_path = path + [("move", direction)]
                frontier.append((new_state, new_path))

        # Try swaps
        for swap_dir in ("down_right", "down_left"):
            new_objects = apply_swap(objects, ground, w, h, ox, oy, swap_dir)
            if new_objects is None:
                continue
            new_state = (new_objects, ox, oy, ax, ay)
            if new_state not in seen:
                seen.add(new_state)
                new_path = path + [("diagonal_swap", swap_dir)]
                if check_goals(new_objects, w, h, goals):
                    return new_path
                frontier.append((new_state, new_path))

    return None  # no solution


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #

def solve_level(path: Path):
    level = load_level(path)
    w, h = level["w"], level["h"]

    print(f"\n{'='*50}")
    print(f"Level: {path.name}")
    print(f"Board: {w}×{h}")
    print(f"Goals: {', '.join(g['type'] for g in level['goals'])}")

    result = solve(level)
    if result is None:
        print("No solution found (BFS limit or no path)")
        return

    n_moves = sum(1 for a, _ in result if a == "move")
    n_swaps = sum(1 for a, _ in result if a == "diagonal_swap")
    print(f"Gold path: {len(result)} steps ({n_moves} moves + {n_swaps} swaps)")

    existing = level.get("gold_path", [])
    if existing:
        print(f"Existing gold path: {len(existing)} steps")

    print(f"\nJSON gold path:")
    for action, direction in result:
        print(f'  {{"action": "{action}", "direction": "{direction}"}}')


def main():
    if len(sys.argv) < 2:
        print("Usage: diagonal_swipes_solver.py <level.json | levels_dir/>")
        sys.exit(1)

    target = Path(sys.argv[1])
    if target.is_dir():
        files = sorted(target.glob("ds_*.json"))
        for p in files:
            solve_level(p)
    else:
        solve_level(target)


if __name__ == "__main__":
    main()
