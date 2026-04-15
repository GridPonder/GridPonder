"""
Box Builder game simulator for the GridPonder puzzle solver.

Faithfully implements the sided_box DSL system from the Dart engine.

State is immutable (frozen dataclass) so BFS/A* can hash/deduplicate it.

Side bit encoding:  U=1, R=2, D=4, L=8
A complete box has sides == 15 (all four sides present).

apply() returns (new_state, won, events) where *events* is a list of DSL event
dicts using the same vocabulary as the Dart engine's event.dart.  This enables
generic event formatting and constraint checking in the search layer.
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

Boxes = FrozenSet[Tuple[Tuple[int, int], int]]
Event = Dict[str, Any]


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
        for row_idx, row in enumerate(ground):
            for col_idx, kind in enumerate(row):
                if kind != "empty":
                    walls.append((col_idx, row_idx))
    elif isinstance(ground, dict):
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
        # portals: not yet handled in solver

    # ── Markers layer → targets ─────────────────────────────────────────────
    targets_list: list = []
    markers = layers.get("markers", {})
    marker_entries = markers.get("entries", []) if isinstance(markers, dict) else []
    for entry in marker_entries:
        if entry.get("kind") == "box_target":
            x, y = entry["position"]
            targets_list.append((x, y))

    # ── Goals → target_value ────────────────────────────────────────────────
    target_value = 15
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
    return _is_in_bounds(x, y, info) and (x, y) not in info.walls


def _boxes_dict(boxes: Boxes) -> Dict[Tuple[int, int], int]:
    return dict(boxes)


def _apply_pickup(
    state: BBState, info: LevelInfo
) -> Tuple[BBState, List[Event]]:
    """
    If the avatar is standing on a pickaxe and not already holding one,
    pick it up.  Returns (new_state, events).
    """
    pos = (state.ax, state.ay)
    if state.inv is None and pos in state.pickaxes:
        ns = BBState(
            boxes=state.boxes,
            rocks=state.rocks,
            pickaxes=state.pickaxes - {pos},
            ax=state.ax,
            ay=state.ay,
            inv="pickaxe",
        )
        return ns, [{"type": "inventory_changed", "oldItem": None, "newItem": "pickaxe"}]
    return state, []


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply(
    state: BBState, direction: str, info: LevelInfo
) -> Tuple[BBState, bool, List[Event]]:
    """
    Apply one move action to state.

    Returns (new_state, won, events).

    *events* is a list of DSL event dicts describing what happened this turn.
    If the move is blocked, returns (state, False, []) with no state change.
    """
    dx, dy = _DELTA[direction]
    ax, ay = state.ax, state.ay
    tx, ty = ax + dx, ay + dy

    # Basic bounds + walkable check
    if not _is_in_bounds(tx, ty, info):
        return state, False, []
    if (tx, ty) in info.walls:
        return state, False, []

    out_bit  = _SIDE_BIT[direction]
    in_bit   = _SIDE_BIT[_OPPOSITE[direction]]
    perp_mask = (
        (_SIDE_BIT["left"] | _SIDE_BIT["right"])
        if direction in ("up", "down")
        else (_SIDE_BIT["up"] | _SIDE_BIT["down"])
    )

    bd = _boxes_dict(state.boxes)
    box_at_pos    = bd.get((ax, ay))
    box_at_target = bd.get((tx, ty))

    events: List[Event] = []

    # -----------------------------------------------------------------------
    # CASE 1: Carry — avatar co-occupies a box with the outward side set
    # -----------------------------------------------------------------------
    if box_at_pos is not None and (box_at_pos & out_bit) != 0:

        if (tx, ty) in state.rocks:
            return state, False, []
        if (tx, ty) in state.pickaxes:
            return state, False, []

        if box_at_target is not None:
            if (box_at_target & in_bit) != 0:
                return state, False, []
            if (box_at_pos & box_at_target & perp_mask) != 0:
                return state, False, []
            merged = box_at_pos | box_at_target
            new_bd = {k: v for k, v in bd.items()
                      if k != (ax, ay) and k != (tx, ty)}
            new_bd[(tx, ty)] = merged
            ns = BBState(
                boxes=frozenset(new_bd.items()),
                rocks=state.rocks,
                pickaxes=state.pickaxes,
                ax=tx, ay=ty,
                inv=state.inv,
            )
            events = [
                {"type": "object_pushed", "kind": "box_fragment",
                 "from": [ax, ay], "to": [tx, ty], "direction": direction},
                {"type": "boxes_merged", "position": [tx, ty],
                 "resultSides": merged, "aSides": box_at_pos, "bSides": box_at_target},
                {"type": "avatar_entered", "position": [tx, ty],
                 "from": [ax, ay], "direction": direction},
            ]
            return ns, _check_win(ns, info), events

        # Clear carry
        new_bd = {k: v for k, v in bd.items() if k != (ax, ay)}
        new_bd[(tx, ty)] = box_at_pos
        ns = BBState(
            boxes=frozenset(new_bd.items()),
            rocks=state.rocks,
            pickaxes=state.pickaxes,
            ax=tx, ay=ty,
            inv=state.inv,
        )
        events = [
            {"type": "object_pushed", "kind": "box_fragment",
             "from": [ax, ay], "to": [tx, ty], "direction": direction},
            {"type": "avatar_entered", "position": [tx, ty],
             "from": [ax, ay], "direction": direction},
        ]
        ns, pickup_events = _apply_pickup(ns, info)
        return ns, _check_win(ns, info), events + pickup_events

    # -----------------------------------------------------------------------
    # CASE 2: Target cell has a box fragment
    # -----------------------------------------------------------------------
    if box_at_target is not None:
        if (box_at_target & in_bit) != 0:
            # ── 2a: PUSH — inward side blocks entry ──────────────────────────
            pdx, pdy = tx + dx, ty + dy

            if not _is_in_bounds(pdx, pdy, info):
                return state, False, []
            if (pdx, pdy) in info.walls:
                return state, False, []
            if not _is_walkable_ground(pdx, pdy, info):
                return state, False, []
            if (pdx, pdy) in state.rocks:
                return state, False, []

            box_at_push_dest = bd.get((pdx, pdy))

            if box_at_push_dest is not None:
                if (box_at_target & box_at_push_dest & perp_mask) != 0:
                    return state, False, []
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
                events = [
                    {"type": "object_pushed", "kind": "box_fragment",
                     "from": [tx, ty], "to": [pdx, pdy], "direction": direction},
                    {"type": "boxes_merged", "position": [pdx, pdy],
                     "resultSides": merged,
                     "aSides": box_at_target, "bSides": box_at_push_dest},
                    {"type": "avatar_entered", "position": [tx, ty],
                     "from": [ax, ay], "direction": direction},
                ]
                return ns, _check_win(ns, info), events

            if (pdx, pdy) in state.pickaxes:
                return state, False, []

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
            events = [
                {"type": "object_pushed", "kind": "box_fragment",
                 "from": [tx, ty], "to": [pdx, pdy], "direction": direction},
                {"type": "avatar_entered", "position": [tx, ty],
                 "from": [ax, ay], "direction": direction},
            ]
            return ns, _check_win(ns, info), events

        else:
            # ── 2b: ENTER — no inward side, avatar co-occupies ───────────────
            ns = BBState(
                boxes=state.boxes,
                rocks=state.rocks,
                pickaxes=state.pickaxes,
                ax=tx, ay=ty,
                inv=state.inv,
            )
            events = [
                {"type": "avatar_entered", "position": [tx, ty],
                 "from": [ax, ay], "direction": direction},
            ]
            ns, pickup_events = _apply_pickup(ns, info)
            return ns, _check_win(ns, info), events + pickup_events

    # -----------------------------------------------------------------------
    # CASE 3: Rock — break with pickaxe
    # -----------------------------------------------------------------------
    if (tx, ty) in state.rocks:
        if state.inv == "pickaxe":
            ns = BBState(
                boxes=state.boxes,
                rocks=state.rocks - {(tx, ty)},
                pickaxes=state.pickaxes,
                ax=tx, ay=ty,
                inv=None,
            )
            events = [
                {"type": "object_removed", "position": [tx, ty],
                 "kind": "rock", "animation": "breaking"},
                {"type": "inventory_changed",
                 "oldItem": "pickaxe", "newItem": None},
                {"type": "avatar_entered", "position": [tx, ty],
                 "from": [ax, ay], "direction": direction},
            ]
            return ns, _check_win(ns, info), events
        return state, False, []

    # -----------------------------------------------------------------------
    # CASE 4: Clear move
    # -----------------------------------------------------------------------
    ns = BBState(
        boxes=state.boxes,
        rocks=state.rocks,
        pickaxes=state.pickaxes,
        ax=tx, ay=ty,
        inv=state.inv,
    )
    events = [
        {"type": "avatar_entered", "position": [tx, ty],
         "from": [ax, ay], "direction": direction},
    ]
    ns, pickup_events = _apply_pickup(ns, info)
    return ns, _check_win(ns, info), events + pickup_events


# ---------------------------------------------------------------------------
# Heuristic (for A* search)
# ---------------------------------------------------------------------------

def heuristic(state: BBState, info: LevelInfo) -> float:
    """
    Admissible lower-bound heuristic for A*.

    For each unsatisfied target, finds the cheapest valid group assignment
    (set of fragments whose sides OR to the target value) and estimates:
        assembly_cost (bring fragments together) + delivery_cost (reach target)

    Returns float('inf') if no valid fragment pairing exists — this signals
    a dead end and causes A* to prune the subtree immediately.

    The estimate uses Manhattan distances and is therefore admissible: real
    paths cost at least as many moves.
    """
    bd = _boxes_dict(state.boxes)

    unsatisfied = [t for t in info.targets if bd.get(t) != info.target_value]
    if not unsatisfied:
        return 0.0

    # Exclude fragments already on satisfied targets (they are done)
    satisfied = {t for t in info.targets if bd.get(t) == info.target_value}
    fragments = [(pos, sides) for pos, sides in bd.items() if pos not in satisfied]

    if not fragments:
        return float("inf")

    valid_groups = _enumerate_valid_groups(fragments, info.target_value)
    if not valid_groups:
        return float("inf")  # No valid pairing → dead end

    # For each unsatisfied target, find cheapest valid group (ignoring
    # disjointness — gives admissible lower bound per target).
    total = 0.0
    for target in unsatisfied:
        best = min((_group_cost(g, target) for g in valid_groups), default=float("inf"))
        if best == float("inf"):
            return float("inf")
        total += best

    return total


def _enumerate_valid_groups(
    fragments: List[Tuple[Tuple[int, int], int]],
    target_value: int,
) -> List[List[Tuple[Tuple[int, int], int]]]:
    """
    Return all non-empty subsets of *fragments* whose sides bitwise-OR to
    *target_value*.  For n ≤ 12 fragments this is fast (at most 4096 subsets).
    """
    n = len(fragments)
    valid = []
    for mask in range(1, 1 << n):
        combined = 0
        group = []
        for i in range(n):
            if mask & (1 << i):
                combined |= fragments[i][1]
                group.append(fragments[i])
        if combined == target_value:
            valid.append(group)
    return valid


def _group_cost(
    group: List[Tuple[Tuple[int, int], int]],
    target: Tuple[int, int],
) -> float:
    """
    Admissible lower-bound cost to assemble the fragment group and deliver it
    to *target*.

    assembly_cost — Prim's MST (Manhattan) to bring all fragments together.
                    MST distance is a lower bound on assembly push-actions
                    because fragments must traverse at least MST-length to
                    reach a common point.  (We use exact Prim's, not the
                    previously used nearest-neighbour approximation which can
                    overestimate the MST and break admissibility.)

    delivery_cost — Manhattan distance from the nearest group member to the
                    target (lower bound on how far the final box must travel).

    We return max(assembly, delivery) rather than their sum because box carry
    allows assembly and delivery to overlap: the avatar can merge fragments
    while simultaneously moving toward the target, so the total cost is at
    least the larger of the two costs individually, but need not pay both in
    full.
    """
    positions = [pos for pos, _ in group]

    if len(positions) == 1:
        assembly = 0.0
    else:
        # Prim's MST — exact minimum spanning tree (Manhattan distances)
        in_mst: set = {positions[0]}
        not_in_mst = list(positions[1:])
        assembly = 0.0
        while not_in_mst:
            best_d = float("inf")
            best_p = None
            for p in not_in_mst:
                for q in in_mst:
                    d = abs(p[0] - q[0]) + abs(p[1] - q[1])
                    if d < best_d:
                        best_d = d
                        best_p = p
            assembly += best_d
            in_mst.add(best_p)
            not_in_mst.remove(best_p)

    delivery = float(min(
        abs(pos[0] - target[0]) + abs(pos[1] - target[1])
        for pos in positions
    ))

    # max is admissible: true cost ≥ assembly (fragments must meet)
    # and true cost ≥ delivery (box must reach target), so
    # true cost ≥ max(assembly, delivery).
    return max(assembly, delivery)


# ---------------------------------------------------------------------------
# Waypoint / override helpers
# ---------------------------------------------------------------------------

def override_initial_state(base: BBState, override: Dict[str, Any]) -> BBState:
    """
    Return a new BBState where fields listed in *override* replace those in
    *base*.  Fields absent from *override* are taken from *base*.

    Override JSON format::

        {
          "boxes":     [{"position": [x, y], "sides": N}, ...],
          "rocks":     [[x, y], ...],
          "pickaxes":  [[x, y], ...],
          "avatar":    [x, y],
          "inventory": null | "pickaxe"
        }
    """
    boxes = base.boxes
    if "boxes" in override:
        boxes = frozenset(
            (tuple(e["position"]), int(e["sides"]))
            for e in override["boxes"]
        )
    rocks = base.rocks
    if "rocks" in override:
        rocks = frozenset(tuple(r) for r in override["rocks"])
    pickaxes = base.pickaxes
    if "pickaxes" in override:
        pickaxes = frozenset(tuple(p) for p in override["pickaxes"])
    ax, ay = base.ax, base.ay
    if "avatar" in override:
        ax, ay = override["avatar"]
    inv = base.inv
    if "inventory" in override:
        inv = override["inventory"]
    return BBState(boxes=boxes, rocks=rocks, pickaxes=pickaxes,
                   ax=ax, ay=ay, inv=inv)


def matches_waypoint(state: BBState, waypoint: Dict[str, Any]) -> bool:
    """
    Return True if *state* satisfies all constraints listed in *waypoint*.

    Waypoint JSON format::

        {
          "boxes":     [{"position": [x, y], "sides": N}, ...],
          "avatar":    [x, y],
          "inventory": null | "pickaxe"
        }

    Only listed fields are checked; others are ignored.
    """
    bd = _boxes_dict(state.boxes)
    if "boxes" in waypoint:
        for entry in waypoint["boxes"]:
            pos = tuple(entry["position"])
            if bd.get(pos) != int(entry["sides"]):
                return False
    if "avatar" in waypoint:
        wx, wy = waypoint["avatar"]
        if state.ax != wx or state.ay != wy:
            return False
    if "inventory" in waypoint:
        if state.inv != waypoint["inventory"]:
            return False
    return True


# ---------------------------------------------------------------------------
# Win condition
# ---------------------------------------------------------------------------

def _check_win(state: BBState, info: LevelInfo) -> bool:
    bd = _boxes_dict(state.boxes)
    return all(bd.get(t) == info.target_value for t in info.targets)


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------

def can_prune(
    state: BBState, info: LevelInfo, depth: int, max_depth: int
) -> bool:
    """Return True if this state cannot possibly lead to a solution."""
    bd = _boxes_dict(state.boxes)

    # ── Heuristic 1: Too few moves remain for all unsatisfied targets ────────
    remaining = sum(1 for t in info.targets if bd.get(t) != info.target_value)
    if depth + remaining > max_depth:
        return True

    # ── Heuristic 2: Box permanently stuck (no reachable push direction) ─────
    for pos, sides in bd.items():
        if pos in info.targets and sides == info.target_value:
            continue  # already satisfied
        px, py = pos
        can_move = False
        for d in ACTIONS:
            ddx, ddy = _DELTA[d]
            land_x, land_y = px + ddx, py + ddy
            if not _is_in_bounds(land_x, land_y, info):
                continue
            if (land_x, land_y) in info.walls:
                continue
            if (land_x, land_y) in state.rocks:
                continue
            if (land_x, land_y) in state.pickaxes:
                continue
            can_move = True
            break
        if not can_move:
            return True

    return False
