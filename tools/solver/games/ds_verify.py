#!/usr/bin/env python3
"""Verify a manually designed level path works."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from tools.solver.games.diagonal_swipes_solver import (
    check_goals, apply_move, apply_swap
)

def verify(path_str: str):
    """Verify a level's gold path by loading the JSON and simulating."""
    with open(path_str) as f:
        data = json.load(f)
    board = data["board"]
    w, h = board["size"]

    # Ground
    ground = [None] * (w * h)
    gl = board.get("layers", {}).get("ground")
    if gl:
        if isinstance(gl, dict):
            for e in gl.get("entries", []):
                x, y = e["position"]
                if e.get("kind") == "void":
                    ground[y * w + x] = "void"

    # Objects
    objects_list = [None] * (w * h)
    ol = board.get("layers", {}).get("objects")
    if ol:
        if isinstance(ol, list):
            for y, row in enumerate(ol):
                for x, cell in enumerate(row):
                    if isinstance(cell, str) and cell.startswith("num_"):
                        objects_list[y * w + x] = cell
        elif isinstance(ol, dict):
            for e in ol.get("entries", []):
                x, y = e["position"]
                kind = e.get("kind")
                if kind and kind.startswith("num_"):
                    objects_list[y * w + x] = kind
    objects = tuple(objects_list)
    ground_t = tuple(ground)

    st = data.get("state", {})
    av = st.get("avatar", {})
    ax, ay = av.get("position", [0, 0])
    ov = st.get("overlay", {})
    ox, oy = ov.get("position", [0, 0])
    goals = data.get("goals", [])

    # Simulate gold path
    gold = data.get("solution", {}).get("goldPath", [])
    print(f"Level: {data['id']}, Gold path: {len(gold)} steps")
    print(f"Board: {w}×{h}, Goals: {', '.join(g['type'] for g in goals)}")

    for i, step in enumerate(gold):
        action = step["action"]
        direction = step["direction"]
        if action == "move":
            result = apply_move(objects, ground_t, w, h, ax, ay, ox, oy, direction)
            if result:
                ax, ay, ox, oy = result
        elif action == "diagonal_swap":
            new_obj = apply_swap(objects, ground_t, w, h, ox, oy, direction)
            if new_obj:
                objects = new_obj

    if check_goals(objects, w, h, goals):
        print(f"✓ Gold path verified! ({len(gold)} steps)")
        return True
    else:
        print(f"✗ Gold path does NOT reach goal!")
        # Show final board state
        for y in range(h):
            row = []
            for x in range(w):
                kind = objects[y * w + x]
                if kind: row.append(kind[4:])
                elif ground[y * w + x] == "void": row.append("#")
                else: row.append(".")
            print(f"  {'  '.join(row)}")
        return False


if __name__ == "__main__":
    for p in sys.argv[1:]:
        target = Path(p)
        if target.is_dir():
            for f in sorted(target.glob("ds_*.json")):
                verify(str(f))
                print()
        else:
            verify(p)
