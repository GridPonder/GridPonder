"""
Fast Twinseed solver — per-cell byte-state encoding.

State representation (bytes of length W*H + 3):
  cells[i]      = (obj_kind << 3) | ground_kind   for i in 0..W*H-1
  cells[W*H]    = avatar_pos  (0..W*H-1)
  cells[W*H+1]  = clone_pos   (0..W*H-1; CLONE_INACTIVE=255 means no clone)
  cells[W*H+2]  = inventory   (INV_NONE=0, INV_TORCH=1, INV_PICKAXE=2)

Ground kind indices (bits 0-2 of cell byte):
  VOID=0, EMPTY=1, GARDEN_PLOT=2, PLANTED=3, WATER=4, BRIDGE=5, ICE=6

Object kind indices (bits 3-5 of cell byte, stored left-shifted by 3):
  NONE=0, SEED_BASKET=1, ROCK=2, WOOD=3, METAL_CRATE=4, TORCH=5, PICKAXE=6

Neighbours: neighbors[pos] = [up_pos, down_pos, left_pos, right_pos]
  -1 means out-of-bounds (void cell check is done via cell byte).

Actions: move_up(0), move_down(1), move_left(2), move_right(3), clone(4)
"""

from __future__ import annotations

import array as _array
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_SOLVER = Path(__file__).parent.parent
if str(_SOLVER) not in sys.path:
    sys.path.insert(0, str(_SOLVER))

# Reuse the heuristic table from the original twinseed solver
import games.twinseed as _tw

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GROUND_VOID        = 0
GROUND_EMPTY       = 1
GROUND_GARDEN_PLOT = 2
GROUND_PLANTED     = 3
GROUND_WATER       = 4
GROUND_BRIDGE      = 5
GROUND_ICE         = 6

OBJ_NONE        = 0
OBJ_SEED_BASKET = 1
OBJ_ROCK        = 2
OBJ_WOOD        = 3
OBJ_METAL_CRATE = 4
OBJ_TORCH       = 5
OBJ_PICKAXE     = 6

INV_NONE    = 0
INV_TORCH   = 1
INV_PICKAXE = 2

CLONE_INACTIVE = 255

# Frozenset lookups (O(1) membership)
_WALKABLE  = frozenset({GROUND_EMPTY, GROUND_GARDEN_PLOT, GROUND_PLANTED,
                        GROUND_WATER, GROUND_BRIDGE, GROUND_ICE})
_SOLID     = frozenset({OBJ_SEED_BASKET, OBJ_ROCK, OBJ_WOOD, OBJ_METAL_CRATE})
_PUSHABLE  = frozenset({OBJ_SEED_BASKET, OBJ_WOOD, OBJ_METAL_CRATE})
_PICKUP    = frozenset({OBJ_TORCH, OBJ_PICKAXE})

_GROUND_STR = {
    "void":           GROUND_VOID,
    "empty":          GROUND_EMPTY,
    "garden_plot":    GROUND_GARDEN_PLOT,
    "planted_garden": GROUND_PLANTED,
    "water":          GROUND_WATER,
    "bridge":         GROUND_BRIDGE,
    "ice":            GROUND_ICE,
}
_OBJ_STR = {
    "seed_basket": OBJ_SEED_BASKET,
    "rock":        OBJ_ROCK,
    "wood":        OBJ_WOOD,
    "metal_crate": OBJ_METAL_CRATE,
    "torch":       OBJ_TORCH,
    "pickaxe":     OBJ_PICKAXE,
}
_INV_STR = {"torch": INV_TORCH, "pickaxe": INV_PICKAXE}

ACTIONS: List[str] = ["move_up", "move_down", "move_left", "move_right", "clone"]

# Direction index → neighbors array index (must match ACTIONS order)
_DIR_OF = {"move_up": 0, "move_down": 1, "move_left": 2, "move_right": 3}


# ---------------------------------------------------------------------------
# FastInfo
# ---------------------------------------------------------------------------

@dataclass
class FastInfo:
    width: int
    height: int
    cells_len: int
    neighbors: List[List[int]]          # neighbors[pos] = [up, down, left, right]
    htable: _tw._HeuristicTable
    level_id: Optional[str] = None
    # Flat cost table: cost_table[plot_pos * cells_len + basket_pos] = Dijkstra cost.
    # Stored as array.array('d') for O(1) C-level access from Cython.
    cost_table: object = None           # array.array('d', ...)
    # Flat neighbor list for Cython (cells_len * 4 ints, order: up/down/left/right)
    neighbors_flat: object = None       # array.array('i', ...)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load(level_json: Dict[str, Any]) -> Tuple[bytes, FastInfo]:
    """Parse level JSON into (initial_state: bytes, FastInfo)."""
    board_json  = level_json.get("board", {})
    width, height = board_json.get("size", [0, 0])
    cells_len = width * height

    # Start with all cells as GROUND_EMPTY, OBJ_NONE
    cells = bytearray(cells_len)
    for i in range(cells_len):
        cells[i] = GROUND_EMPTY  # (OBJ_NONE << 3) | GROUND_EMPTY

    layers = board_json.get("layers", {})

    # Ground layer
    ground_layer = layers.get("ground", {})
    for entry in ground_layer.get("entries", []):
        x, y = entry["position"]
        kind = _GROUND_STR.get(entry["kind"], GROUND_EMPTY)
        pos = y * width + x
        cells[pos] = (cells[pos] & ~7) | kind  # keep obj bits, set ground

    # Objects layer
    obj_layer = layers.get("objects", {})
    for entry in obj_layer.get("entries", []):
        x, y = entry["position"]
        kind = _OBJ_STR.get(entry["kind"], OBJ_NONE)
        pos = y * width + x
        cells[pos] = (cells[pos] & 7) | (kind << 3)  # keep ground bits, set obj

    # Neighbours (accounting for board bounds; void check done at runtime)
    neighbors: List[List[int]] = []
    for pos in range(cells_len):
        x = pos % width
        y = pos // width
        neighbors.append([
            pos - width if y > 0 else -1,              # up
            pos + width if y < height - 1 else -1,     # down
            pos - 1     if x > 0 else -1,              # left
            pos + 1     if x < width - 1 else -1,      # right
        ])

    # Avatar state
    avatar_json = level_json.get("state", {}).get("avatar", {})
    ax, ay = avatar_json.get("position", [0, 0])
    avatar_pos = ay * width + ax
    item_str = avatar_json.get("item")
    inventory = _INV_STR.get(item_str, INV_NONE) if item_str else INV_NONE

    initial = bytes(cells) + bytes([avatar_pos, CLONE_INACTIVE, inventory])

    # Reuse precomputed heuristic table from original solver
    _, tw_info = _tw.load(level_json)
    htable = tw_info.htable

    # Build flat cost table: cost_table[plot_pos * cells_len + basket_pos]
    # Stored as C-accessible array.array('d') for O(1) access in Cython.
    inf = float("inf")
    cost_table = _array.array("d", [inf] * (cells_len * cells_len))
    for (gx, gy), dist_map in htable.push_dist.items():
        plot_pos = gy * width + gx
        for (bx, by), cost in dist_map.items():
            basket_pos = by * width + bx
            cost_table[plot_pos * cells_len + basket_pos] = cost

    # Flat neighbor list for Cython: neighbors_flat[pos*4 + dir]
    neighbors_flat = _array.array("i")
    for nb in neighbors:
        neighbors_flat.extend(nb)

    info = FastInfo(
        width=width,
        height=height,
        cells_len=cells_len,
        neighbors=neighbors,
        htable=htable,
        level_id=level_json.get("id"),
        cost_table=cost_table,
        neighbors_flat=neighbors_flat,
    )

    return initial, info


# ---------------------------------------------------------------------------
# Ice-slide helpers
# ---------------------------------------------------------------------------

def _slide_obj(cells: bytearray, pos: int, obj: int, dir_idx: int,
               neighbors: List[List[int]]) -> None:
    """Slide an object from pos in dir_idx direction (modifies cells in place)."""
    while True:
        nxt = neighbors[pos][dir_idx]
        if nxt < 0:
            break
        ng = cells[nxt] & 7
        if ng == GROUND_VOID or ng not in _WALKABLE:
            break
        no = (cells[nxt] >> 3) & 7
        if no != OBJ_NONE:      # blocked by another object
            break
        # Move object
        cells[pos] &= 7         # clear object at current pos
        cells[nxt] = (cells[nxt] & 7) | (obj << 3)
        pos = nxt

        # Apply cascade rules at new position
        pg = cells[pos] & 7
        if obj == OBJ_SEED_BASKET and pg == GROUND_GARDEN_PLOT:
            cells[pos] = (cells[pos] & ~7) | GROUND_PLANTED
            cells[pos] &= 7     # clear object (basket consumed)
            break               # seed is planted, stop sliding
        elif obj == OBJ_METAL_CRATE and pg == GROUND_WATER:
            cells[pos] = (cells[pos] & ~7) | GROUND_BRIDGE
            cells[pos] &= 7     # clear object
            break
        elif pg != GROUND_ICE:
            break               # left ice, stop


def _slide_avatar(cells: bytearray, pos: int, dir_idx: int,
                  neighbors: List[List[int]], inventory: int,
                  cells_len: int) -> Tuple[int, int]:
    """Slide avatar on ice in dir_idx direction. Returns (new_pos, new_inventory)."""
    while True:
        nxt = neighbors[pos][dir_idx]
        if nxt < 0:
            break
        ng = cells[nxt] & 7
        if ng == GROUND_VOID or ng not in _WALKABLE:
            break
        no = (cells[nxt] >> 3) & 7
        if no in _SOLID:
            # Try to push solid object during slide (only if pushable)
            if no in _PUSHABLE:
                push_dest = neighbors[nxt][dir_idx]
                if push_dest < 0:
                    break
                pdg = cells[push_dest] & 7
                if pdg == GROUND_VOID or pdg not in _WALKABLE:
                    break
                pdo = (cells[push_dest] >> 3) & 7
                if pdo != OBJ_NONE:
                    break
                # Push
                cells[push_dest] = (cells[push_dest] & 7) | (no << 3)
                cells[nxt] &= 7
                pos = nxt
                # Cascade rules for pushed object
                pg = cells[push_dest] & 7
                if no == OBJ_SEED_BASKET and pg == GROUND_GARDEN_PLOT:
                    cells[push_dest] = (cells[push_dest] & ~7) | GROUND_PLANTED
                    cells[push_dest] &= 7
                elif no == OBJ_METAL_CRATE and pg == GROUND_WATER:
                    cells[push_dest] = (cells[push_dest] & ~7) | GROUND_BRIDGE
                    cells[push_dest] &= 7
                elif pg == GROUND_ICE:
                    _slide_obj(cells, push_dest, no, dir_idx, neighbors)
            break   # stop sliding (hit solid, push succeeded or not)
        # Walk to next cell
        pos = nxt
        # Water clears inventory
        pg = cells[pos] & 7
        if pg == GROUND_WATER and inventory != INV_NONE:
            inventory = INV_NONE
        # Also handle pickup during slide
        if no in _PICKUP:
            inventory = INV_TORCH if no == OBJ_TORCH else INV_PICKAXE
            cells[pos] &= 7     # clear pickup
        if pg != GROUND_ICE:
            break               # left ice, stop
    return pos, inventory


# ---------------------------------------------------------------------------
# Core apply functions
# ---------------------------------------------------------------------------

def _apply_move(state: bytes, dir_idx: int, info: FastInfo) -> Tuple[bytes, bool, list]:
    cells_len = info.cells_len
    cells = bytearray(state[:cells_len])
    avatar_pos = state[cells_len]
    clone_pos  = state[cells_len + 1]
    inventory  = state[cells_len + 2]
    neighbors  = info.neighbors

    target = neighbors[avatar_pos][dir_idx]
    if target < 0:
        return state, False, []

    tg = cells[target] & 7
    if tg == GROUND_VOID:
        return state, False, []

    to = (cells[target] >> 3) & 7

    if to in _SOLID:
        # --- Tool interactions (checked before pushability) ---
        if inventory == INV_TORCH and to == OBJ_WOOD:
            # Torch burns wood
            cells[target] &= 7
            avatar_pos = target
        elif inventory == INV_PICKAXE and to == OBJ_ROCK:
            # Pickaxe breaks rock
            cells[target] &= 7
            avatar_pos = target
            inventory = INV_NONE
        elif to in _PUSHABLE:
            # Push
            push_dest = neighbors[target][dir_idx]
            if push_dest < 0:
                return state, False, []
            pdg = cells[push_dest] & 7
            if pdg == GROUND_VOID or pdg not in _WALKABLE:
                return state, False, []
            pdo = (cells[push_dest] >> 3) & 7
            if pdo != OBJ_NONE:
                return state, False, []
            # Move object
            cells[push_dest] = (cells[push_dest] & 7) | (to << 3)
            cells[target] &= 7
            avatar_pos = target
            # Cascade rules for pushed object at push_dest
            pg = cells[push_dest] & 7
            if to == OBJ_SEED_BASKET and pg == GROUND_GARDEN_PLOT:
                cells[push_dest] = (cells[push_dest] & ~7) | GROUND_PLANTED
                cells[push_dest] &= 7           # remove basket
            elif to == OBJ_METAL_CRATE and pg == GROUND_WATER:
                cells[push_dest] = (cells[push_dest] & ~7) | GROUND_BRIDGE
                cells[push_dest] &= 7           # remove crate
            elif pg == GROUND_ICE:
                _slide_obj(cells, push_dest, to, dir_idx, neighbors)
        else:
            return state, False, []  # blocked (e.g. rock without pickaxe)

    elif to in _PICKUP:
        # Walk onto pickup item
        inventory = INV_TORCH if to == OBJ_TORCH else INV_PICKAXE
        cells[target] &= 7
        avatar_pos = target

    else:
        # Empty cell (to == OBJ_NONE)
        avatar_pos = target

    # Post-move ground effects
    tg_now = cells[avatar_pos] & 7
    if tg_now == GROUND_WATER and inventory != INV_NONE:
        inventory = INV_NONE
    if tg_now == GROUND_ICE:
        avatar_pos, inventory = _slide_avatar(
            cells, avatar_pos, dir_idx, neighbors, inventory, cells_len)

    # Win: no garden_plot cells remain
    won = not any((cells[i] & 7) == GROUND_GARDEN_PLOT for i in range(cells_len))

    new_state = bytes(cells) + bytes([avatar_pos, clone_pos, inventory])
    return new_state, won, []


def _apply_clone(state: bytes, info: FastInfo) -> Tuple[bytes, bool, list]:
    cells_len  = info.cells_len
    avatar_pos = state[cells_len]
    clone_pos  = state[cells_len + 1]
    inventory  = state[cells_len + 2]

    if clone_pos == CLONE_INACTIVE:
        # Place clone at avatar's current position
        new_clone = avatar_pos
        new_avatar = avatar_pos
    else:
        # Teleport: check if clone cell is blocked by a solid object
        obj_at_clone = (state[clone_pos] >> 3) & 7
        if obj_at_clone in _SOLID:
            return state, False, []  # destination blocked — keep clone
        new_avatar = clone_pos
        new_clone  = CLONE_INACTIVE

    cells = state[:cells_len]
    new_state = cells + bytes([new_avatar, new_clone, inventory])
    won = not any((state[i] & 7) == GROUND_GARDEN_PLOT for i in range(cells_len))
    return new_state, won, []


# ---------------------------------------------------------------------------
# Public solver interface
# ---------------------------------------------------------------------------

def apply(state: bytes, action: str, info: FastInfo) -> Tuple[bytes, bool, list]:
    if action == "clone":
        return _apply_clone(state, info)
    return _apply_move(state, _DIR_OF[action], info)


def heuristic(state: bytes, info: FastInfo) -> float:
    """Admissible heuristic: optimal basket-to-plot assignment cost."""
    cells_len = info.cells_len
    width     = info.width

    baskets: List[Tuple[int, int]] = []
    plots:   List[Tuple[int, int]] = []

    for i in range(cells_len):
        c = state[i]
        g = c & 7
        o = (c >> 3) & 7
        if g == GROUND_GARDEN_PLOT:
            plots.append((i % width, i // width))
        if o == OBJ_SEED_BASKET:
            baskets.append((i % width, i // width))

    if not baskets:
        return 0.0
    if not plots:
        return float("inf")    # baskets remain but no plots — dead state

    return info.htable.min_cost_assignment(baskets, plots)


def can_prune(state: bytes, info: FastInfo, depth: int, max_depth: int) -> bool:
    """Prune if any remaining basket has no path to any remaining plot."""
    cells_len = info.cells_len
    width     = info.width
    htable    = info.htable
    inf       = float("inf")

    plots: List[Tuple[int, int]] = []
    for i in range(cells_len):
        if (state[i] & 7) == GROUND_GARDEN_PLOT:
            plots.append((i % width, i // width))

    if not plots:
        return False  # no plots → either won or dead state caught by heuristic

    for i in range(cells_len):
        if ((state[i] >> 3) & 7) != OBJ_SEED_BASKET:
            continue
        bx, by = i % width, i // width
        reachable = any(
            htable.push_dist.get(plot, {}).get((bx, by), inf) < inf
            for plot in plots
        )
        if not reachable:
            return True  # this basket can never reach any plot

    return False
