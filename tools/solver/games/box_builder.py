"""
Box Builder game simulator for the GridPonder puzzle solver.

Faithfully implements the sided_box DSL system from the Dart engine.

State is immutable (frozen dataclass) so BFS can hash/deduplicate it.

Side bit encoding:  U=1, R=2, D=4, L=8
A complete box has sides == 15 (all four sides present).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Direction helpers
# ---------------------------------------------------------------------------

ACTIONS: List[str] = ["up", "down", "left", "right"]

_DELTA: Dict[str, Tuple[int, int]] = {
    "up":    (0, -1),
    "down":  (0,  1),
    "left":  (-1, 0),
    "right": ( 1, 0),
}

_OPPOSITE: Dict[str, str] = {
    "up": "down", "down": "up", "left": "right", "right": "left",
}

# Side bit for each direction (the wall on that side of a cell)
_SIDE_BIT: Dict[str, int] = {
    "up": 1, "right": 2, "down": 4, "left": 8,
}


# ---------------------------------------------------------------------------
# State / LevelInfo
# ---------------------------------------------------------------------------

# boxes: frozenset of ((x, y), sides_int)
Boxes = FrozenSet[Tuple[Tuple[int, int], int]]


@dataclass(frozen=True)
class BBState:
    """Immutable snapshot of one Box Builder turn."""
    boxes: Boxes                          # ((x, y), sides) for each box fragment
    rocks: FrozenSet[Tuple[int, int]]     # remaining rock positions
    pickaxes: FrozenSet[Tuple[int, int]]  # remaining pickaxe positions on ground
    ax: int                               # avatar x
    ay: int                               # avatar y
    inv: Optional[str]                    # held item ("pickaxe" or None)


@dataclass
class LevelInfo:
    """Static level data that does not change during play."""
    width: int
    height: int
    walls: FrozenSet[Tuple[int, int]]    # wall (non-walkable) ground cells
    targets: FrozenSet[Tuple[int, int]]  # box_target marker positions
    target_value: int                     # required sides value (typically 15)
    level_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Loading from level JSON
# ---------------------------------------------------------------------------

def load(level_json: Dict[str, Any]) -> Tuple[BBState, LevelInfo]:
    """Parse a box_builder level JSON into (initial_state, level_info)."""
    cols, rows = level_json["board"]["size"]
    layers = level_json["board"]["layers"]

    # ── Ground layer → walls ────────────────────────────────────────────────
    walls: list = []
    ground = layers.get("ground", [])
    if isinstance(ground, list):
        # Dense format: list of rows, each row is a list of kind strings
        for row_idx, row in enumerate(ground):
            for col_idx, kind in enumerate(row):
                if kind != "empty":
                    walls.append((col_idx, row_idx))
    elif isinstance(ground, dict):
        # Sparse format (unusual for ground but handle it)
        for entry in ground.get("entries", []):
            x, y = entry["position"]
            if entry.get("kind", "empty") not in ("empty",):
                walls.append((x, y))

    # ── Objects layer → boxes, rocks, pickaxes ──────────────────────────────
    boxes_list: list = []
    rocks_list: list = []
    pickaxes_list: list = []

    obj_layer = layers.get("objects", {})
    obj_entries = obj_layer.get("entries", []) if isinstance(obj_layer, dict) else []
    for entry in obj_entries:
        x, y = entry["position"]
        kind = entry.get("kind", "")
        if kind == "box_fragment":
            sides = int(entry.get("sides", 0))
            boxes_list.append(((x, y), sides))
        elif kind == "rock":
            rocks_list.append((x, y))
        elif kind == "pickaxe":
            pickaxes_list.append((x, y))
        # portals: not handled in solver v1

    # ── Markers layer → targets ─────────────────────────────────────────────
    targets_list: list = []
    markers = layers.get("markers", {})
    marker_entries = markers.get("entries", []) if isinstance(markers, dict) else []
    for entry in marker_entries:
        if entry.get("kind") == "box_target":
            x, y = entry["position"]
            targets_list.append((x, y))

    # ── Goals → target_value ────────────────────────────────────────────────
    target_value = 15  # default: full box
    for goal in level_json.get("goals", []):
        if goal.get("type") == "param_match":
            target_value = int(goal["config"].get("checkValue", 15))
            break

    # ── Avatar ──────────────────────────────────────────────────────────────
    avatar = level_json["state"]["avatar"]
    ax, ay = avatar["position"]

    info = LevelInfo(
        width=cols,
        height=rows,
        walls=frozenset(walls),
        targets=frozenset(targets_list),
        target_value=target_value,
        level_id=level_json.get("id"),
    )
    initial = BBState(
        boxes=frozenset(boxes_list),
        rocks=frozenset(rocks_list),
        pickaxes=frozenset(pickaxes_list),
        ax=ax,
        ay=ay,
        inv=None,
    )
    return initial, info


# ---------------------------------------------------------------------------
# Mechanics helpers
# ---------------------------------------------------------------------------

def _is_in_bounds(x: int, y: int, info: LevelInfo) -> bool:
    return 0 <= x < info.width and 0 <= y < info.height


def _is_walkable_ground(x: int, y: int, info: LevelInfo) -> bool:
    """Returns True if the ground tile at (x,y) is walkable (not a wall)."""
    return _is_in_bounds(x, y, info) and (x, y) not in info.walls


def _boxes_dict(boxes: Boxes) -> Dict[Tuple[int, int], int]:
    return dict(boxes)


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply(
    state: BBState, direction: str, info: LevelInfo
) -> Tuple[BBState, bool]:
    """
    Apply one move action (direction) to state.

    Returns (new_state, won). If the move is blocked, returns (state, False)
    (no state change, no win).
    """
    dx, dy = _DELTA[direction]
    ax, ay = state.ax, state.ay
    tx, ty = ax + dx, ay + dy

    # Basic bounds + walkable ground check for target
    if not _is_in_bounds(tx, ty, info):
        return state, False
    if (tx, ty) in info.walls:
        return state, False

    out_bit = _SIDE_BIT[direction]
    in_bit = _SIDE_BIT[_OPPOSITE[direction]]

    bd = _boxes_dict(state.boxes)
    box_at_pos = bd.get((ax, ay))  # sides int or None
    box_at_target = bd.get((tx, ty))

    # -----------------------------------------------------------------------
    # CASE 1: Carry — avatar on a cell with a sided box, exits through that side
    # -----------------------------------------------------------------------
    if box_at_pos is not None and (box_at_pos & out_bit) != 0:
        # Target must be in bounds + walkable (checked above already)

        # Blocked by rock (non-sided solid) at target
        if (tx, ty) in state.rocks:
            return state, False

        # Target has a pickup or portal (non-sided, non-solid) → blocked
        if (tx, ty) in state.pickaxes:
            return state, False  # Can't place box on a pickaxe cell

        # Target has a sided box → check inward side, then carry+merge
        if box_at_target is not None:
            if (box_at_target & in_bit) != 0:
                return state, False  # Inward side blocks carry
            merged = box_at_pos | box_at_target
            new_bd = {k: v for k, v in bd.items() if k != (ax, ay) and k != (tx, ty)}
            new_bd[(tx, ty)] = merged
            ns = BBState(
                boxes=frozenset(new_bd.items()),
                rocks=state.rocks,
                pickaxes=state.pickaxes,
                ax=tx, ay=ty,
                inv=state.inv,
            )
            return ns, _check_win(ns, info)

        # Target is clear → carry box there
        new_bd = {k: v for k, v in bd.items() if k != (ax, ay)}
        new_bd[(tx, ty)] = box_at_pos
        ns = BBState(
            boxes=frozenset(new_bd.items()),
            rocks=state.rocks,
            pickaxes=state.pickaxes,
            ax=tx, ay=ty,
            inv=state.inv,
        )
        return _apply_pickup(ns, info), _check_win(ns, info)

    # -----------------------------------------------------------------------
    # CASE 2: Target has a sided box
    # -----------------------------------------------------------------------
    if box_at_target is not None:
        if (box_at_target & in_bit) != 0:
            # 2a: PUSH — inward side blocks entry
            pdx, pdy = tx + dx, ty + dy

            if not _is_in_bounds(pdx, pdy, info):
                return state, False
            if (pdx, pdy) in info.walls:
                return state, False
            if not _is_walkable_ground(pdx, pdy, info):
                return state, False
            if (pdx, pdy) in state.rocks:
                return state, False

            box_at_push_dest = bd.get((pdx, pdy))

            if box_at_push_dest is not None:
                # Push + merge
                merged = box_at_target | box_at_push_dest
                new_bd = {k: v for k, v in bd.items()
                          if k != (tx, ty) and k != (pdx, pdy)}
                new_bd[(pdx, pdy)] = merged
                ns = BBState(
                    boxes=frozenset(new_bd.items()),
                    rocks=state.rocks,
                    pickaxes=state.pickaxes,
                    ax=tx, ay=ty,
                    inv=state.inv,
                )
                return ns, _check_win(ns, info)

            # Push dest has any other object → blocked
            if (pdx, pdy) in state.pickaxes:
                return state, False

            # Push to empty cell
            new_bd = {k: v for k, v in bd.items() if k != (tx, ty)}
            new_bd[(pdx, pdy)] = box_at_target
            ns = BBState(
                boxes=frozenset(new_bd.items()),
                rocks=state.rocks,
                pickaxes=state.pickaxes,
                ax=tx, ay=ty,
                inv=state.inv,
            )
            return ns, _check_win(ns, info)
        else:
            # 2b: ENTER — avatar walks into cell (co-occupies with box)
            ns = BBState(
                boxes=state.boxes,
                rocks=state.rocks,
                pickaxes=state.pickaxes,
                ax=tx, ay=ty,
                inv=state.inv,
            )
            ns = _apply_pickup(ns, info)
            return ns, _check_win(ns, info)

    # -----------------------------------------------------------------------
    # CASE 3: Target has a rock (non-sided solid)
    # -----------------------------------------------------------------------
    if (tx, ty) in state.rocks:
        if state.inv == "pickaxe":
            # Break rock, consume pickaxe, move
            new_rocks = state.rocks - {(tx, ty)}
            ns = BBState(
                boxes=state.boxes,
                rocks=new_rocks,
                pickaxes=state.pickaxes,
                ax=tx, ay=ty,
                inv=None,
            )
            return ns, _check_win(ns, info)
        return state, False

    # -----------------------------------------------------------------------
    # CASE 4: Clear — normal move
    # -----------------------------------------------------------------------
    ns = BBState(
        boxes=state.boxes,
        rocks=state.rocks,
        pickaxes=state.pickaxes,
        ax=tx, ay=ty,
        inv=state.inv,
    )
    ns = _apply_pickup(ns, info)
    return ns, _check_win(ns, info)


def _apply_pickup(state: BBState, info: LevelInfo) -> BBState:
    """If avatar is standing on a pickaxe and not already holding something, pick it up."""
    pos = (state.ax, state.ay)
    if state.inv is None and pos in state.pickaxes:
        return BBState(
            boxes=state.boxes,
            rocks=state.rocks,
            pickaxes=state.pickaxes - {pos},
            ax=state.ax, ay=state.ay,
            inv="pickaxe",
        )
    return state


def _check_win(state: BBState, info: LevelInfo) -> bool:
    """Win if every target has a box with the required sides value."""
    bd = _boxes_dict(state.boxes)
    return all(
        bd.get(t) == info.target_value
        for t in info.targets
    )


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------

def can_prune(
    state: BBState, info: LevelInfo, depth: int, max_depth: int
) -> bool:
    """Return True if this state cannot possibly lead to a solution."""
    bd = _boxes_dict(state.boxes)

    # ── Heuristic 1: Too few moves remain to satisfy all targets ─────────────
    # Each unsatisfied target needs at least 1 more move (to push/merge a box
    # onto it or to do the final merge on it). This is a sound lower bound.
    remaining = sum(
        1 for t in info.targets
        if bd.get(t) != info.target_value
    )
    if depth + remaining > max_depth:
        return True

    # ── Heuristic 2: Box permanently stuck (no reachable push direction) ─────
    # A box is stuck if, in every direction, the push destination is blocked
    # (OOB, wall, or rock) AND the avatar cannot enter the box from that side
    # (i.e., the inward side is set).  Such a box can never move.
    # Note: complete boxes (sides=15) CAN be pushed — the inward side being set
    # triggers a push. So we check pushability, not entryability.
    for pos, sides in bd.items():
        if pos in info.targets and sides == info.target_value:
            continue  # already satisfied, doesn't need to move
        px, py = pos
        can_move = False
        for d in ACTIONS:
            ddx, ddy = _DELTA[d]
            # To push box in direction d, avatar must be at (px-ddx, py-ddy)
            # and box can land at (px+ddx, py+ddy).
            land_x, land_y = px + ddx, py + ddy
            if not _is_in_bounds(land_x, land_y, info):
                continue
            if (land_x, land_y) in info.walls:
                continue
            if (land_x, land_y) in state.rocks:
                continue
            # Land cell must not be occupied by a non-box entity
            # (a box there means push+merge, which is fine)
            if (land_x, land_y) in state.pickaxes:
                continue
            can_move = True
            break
        if not can_move:
            return True

    return False
