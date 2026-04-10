"""
Flag Adventure (Carrot Quest) game simulator for the GridPonder puzzle solver.

Faithfully implements the avatar_navigation + push_objects + portals DSL systems
from the Dart engine, plus the pickup_item, water_clears_items, and
crate_creates_bridge rules.

State is immutable (frozen dataclass) so BFS/A* can hash/deduplicate it.

apply() returns (new_state, won, events) where *events* is a list of DSL event
dicts using the same vocabulary as the Dart engine's event.dart.
"""

from __future__ import annotations

from collections import deque
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


# ---------------------------------------------------------------------------
# State / LevelInfo
# ---------------------------------------------------------------------------

Event = Dict[str, Any]


@dataclass(frozen=True)
class FAState:
    """Immutable snapshot of one Flag Adventure turn."""
    ax: int
    ay: int
    rocks: FrozenSet[Tuple[int, int]]
    wood: FrozenSet[Tuple[int, int]]
    crates: FrozenSet[Tuple[int, int]]
    pickups: FrozenSet[Tuple[int, int, str]]   # (x, y, kind)
    bridges: FrozenSet[Tuple[int, int]]        # water cells converted to bridge
    inventory: Optional[str]                   # None, "torch", or "pickaxe"


@dataclass
class LevelInfo:
    """Static level data that does not change during play."""
    width: int
    height: int
    water_cells: FrozenSet[Tuple[int, int]]               # initial water positions
    portals: Dict[Tuple[int, int], Tuple[int, int]]       # pos → partner (bidirectional)
    flag: Tuple[int, int]
    level_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Loading from level JSON
# ---------------------------------------------------------------------------

def load(level_json: Dict[str, Any]) -> Tuple[FAState, LevelInfo]:
    """Parse a flag_adventure level JSON into (initial_state, level_info)."""
    cols, rows = level_json["board"]["size"]
    layers = level_json["board"]["layers"]

    # ── Ground layer → water cells ───────────────────────────────────────────
    water_list: list = []
    ground = layers.get("ground", {})
    if isinstance(ground, dict):
        for entry in ground.get("entries", []):
            if entry.get("kind") == "water":
                x, y = entry["position"]
                water_list.append((x, y))
    elif isinstance(ground, list):
        for row_idx, row in enumerate(ground):
            for col_idx, kind in enumerate(row):
                if kind == "water":
                    water_list.append((col_idx, row_idx))

    # ── Objects layer → rocks, wood, crates, pickups, portals ───────────────
    rocks_list: list = []
    wood_list: list = []
    crates_list: list = []
    pickups_list: list = []
    portal_by_channel: Dict[str, List[Tuple[int, int]]] = {}

    obj_layer = layers.get("objects", {})
    obj_entries = obj_layer.get("entries", []) if isinstance(obj_layer, dict) else []
    for entry in obj_entries:
        x, y = entry["position"]
        kind = entry.get("kind", "")
        if kind == "rock":
            rocks_list.append((x, y))
        elif kind == "wood":
            wood_list.append((x, y))
        elif kind == "metal_crate":
            crates_list.append((x, y))
        elif kind in ("torch", "pickaxe"):
            pickups_list.append((x, y, kind))
        elif kind == "portal":
            channel = entry.get("channel", "")
            portal_by_channel.setdefault(channel, []).append((x, y))

    # Build bidirectional portal map
    portals: Dict[Tuple[int, int], Tuple[int, int]] = {}
    for channel, positions in portal_by_channel.items():
        if len(positions) == 2:
            a, b = positions[0], positions[1]
            portals[a] = b
            portals[b] = a

    # ── Markers layer → flag ─────────────────────────────────────────────────
    flag_pos: Tuple[int, int] = (0, 0)
    markers = layers.get("markers", {})
    marker_entries = markers.get("entries", []) if isinstance(markers, dict) else []
    for entry in marker_entries:
        if entry.get("kind") == "flag":
            flag_pos = (entry["position"][0], entry["position"][1])
            break

    # ── Avatar ──────────────────────────────────────────────────────────────
    avatar = level_json["state"]["avatar"]
    ax, ay = avatar["position"]

    info = LevelInfo(
        width=cols,
        height=rows,
        water_cells=frozenset(water_list),
        portals=portals,
        flag=flag_pos,
        level_id=level_json.get("id"),
    )
    initial = FAState(
        ax=ax,
        ay=ay,
        rocks=frozenset(rocks_list),
        wood=frozenset(wood_list),
        crates=frozenset(crates_list),
        pickups=frozenset(pickups_list),
        bridges=frozenset(),
        inventory=None,
    )
    return initial, info


# ---------------------------------------------------------------------------
# Mechanics helpers
# ---------------------------------------------------------------------------

def _in_bounds(x: int, y: int, info: LevelInfo) -> bool:
    return 0 <= x < info.width and 0 <= y < info.height


def _is_water(x: int, y: int, state: FAState, info: LevelInfo) -> bool:
    """True if (x, y) is water and not yet bridged."""
    return (x, y) in info.water_cells and (x, y) not in state.bridges


def _has_solid(x: int, y: int, state: FAState) -> bool:
    """True if a solid non-pickup object occupies (x, y)."""
    return (x, y) in state.rocks or (x, y) in state.wood or (x, y) in state.crates


def _pickup_at(x: int, y: int, state: FAState) -> Optional[str]:
    """Return the kind of pickup at (x, y), or None."""
    for px, py, kind in state.pickups:
        if px == x and py == y:
            return kind
    return None


def _blocks_push(x: int, y: int, state: FAState, info: LevelInfo) -> bool:
    """
    True if position (x, y) cannot receive a pushed object.
    A pushed object can land on any in-bounds cell not occupied by another
    solid object or a pickup.  Water cells are fine for wood; crate-into-water
    triggers the bridge rule.
    """
    if not _in_bounds(x, y, info):
        return True
    if _has_solid(x, y, state):
        return True
    if _pickup_at(x, y, state) is not None:
        return True
    return False


# ---------------------------------------------------------------------------
# Post-move rule helpers
# ---------------------------------------------------------------------------

def _apply_pickup(state: FAState, info: LevelInfo) -> Tuple[FAState, List[Event]]:
    """
    pickup_item rule: if avatar stands on a pickup, collect it (silently
    replacing any existing item).
    """
    pos = (state.ax, state.ay)
    found: Optional[Tuple[int, int, str]] = None
    for entry in state.pickups:
        if (entry[0], entry[1]) == pos:
            found = entry
            break
    if found is None:
        return state, []

    old_inv = state.inventory
    new_inv = found[2]
    ns = FAState(
        ax=state.ax, ay=state.ay,
        rocks=state.rocks,
        wood=state.wood,
        crates=state.crates,
        pickups=state.pickups - {found},
        bridges=state.bridges,
        inventory=new_inv,
    )
    return ns, [{"type": "inventory_changed", "oldItem": old_inv, "newItem": new_inv}]


def _apply_water_clear(state: FAState, info: LevelInfo) -> Tuple[FAState, List[Event]]:
    """
    water_clears_items rule: if avatar is on a water cell while holding an
    item, clear inventory.
    """
    if state.inventory is None:
        return state, []
    if not _is_water(state.ax, state.ay, state, info):
        return state, []
    old_inv = state.inventory
    ns = FAState(
        ax=state.ax, ay=state.ay,
        rocks=state.rocks,
        wood=state.wood,
        crates=state.crates,
        pickups=state.pickups,
        bridges=state.bridges,
        inventory=None,
    )
    return ns, [{"type": "inventory_changed", "oldItem": old_inv, "newItem": None}]


def _apply_post_move_rules(
    state: FAState, info: LevelInfo
) -> Tuple[FAState, List[Event]]:
    """Apply all post-move rules (pickup, water) in sequence."""
    events: List[Event] = []
    state, ev = _apply_pickup(state, info)
    events += ev
    state, ev = _apply_water_clear(state, info)
    events += ev
    return state, events


# ---------------------------------------------------------------------------
# Win check
# ---------------------------------------------------------------------------

def _check_win(state: FAState, info: LevelInfo) -> bool:
    return (state.ax, state.ay) == info.flag


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply(
    state: FAState, direction: str, info: LevelInfo
) -> Tuple[FAState, bool, List[Event]]:
    """
    Apply one move action to state.  Returns (new_state, won, events).
    If the move is blocked, returns (state, False, []).
    """
    dx, dy = _DELTA[direction]
    ax, ay = state.ax, state.ay
    tx, ty = ax + dx, ay + dy

    if not _in_bounds(tx, ty, info):
        return state, False, []

    events: List[Event] = []

    # ── Rock at target ────────────────────────────────────────────────────────
    if (tx, ty) in state.rocks:
        if state.inventory == "pickaxe":
            # Break rock, consume pickaxe, move in
            ns = FAState(
                ax=tx, ay=ty,
                rocks=state.rocks - {(tx, ty)},
                wood=state.wood,
                crates=state.crates,
                pickups=state.pickups,
                bridges=state.bridges,
                inventory=None,
            )
            events = [
                {"type": "object_removed", "kind": "rock",
                 "position": [tx, ty], "animation": "breaking"},
                {"type": "inventory_changed", "oldItem": "pickaxe", "newItem": None},
                {"type": "avatar_entered", "position": [tx, ty],
                 "from": [ax, ay], "direction": direction},
            ]
            ns, post_ev = _apply_post_move_rules(ns, info)
            return ns, _check_win(ns, info), events + post_ev
        return state, False, []

    # ── Wood at target ────────────────────────────────────────────────────────
    if (tx, ty) in state.wood:
        if state.inventory == "torch":
            # Burn wood in place (torch NOT consumed), move in
            ns = FAState(
                ax=tx, ay=ty,
                rocks=state.rocks,
                wood=state.wood - {(tx, ty)},
                crates=state.crates,
                pickups=state.pickups,
                bridges=state.bridges,
                inventory=state.inventory,
            )
            events = [
                {"type": "object_removed", "kind": "wood",
                 "position": [tx, ty], "animation": "burning"},
                {"type": "avatar_entered", "position": [tx, ty],
                 "from": [ax, ay], "direction": direction},
            ]
            ns, post_ev = _apply_post_move_rules(ns, info)
            return ns, _check_win(ns, info), events + post_ev
        else:
            # Push wood to T+d
            px, py = tx + dx, ty + dy
            if _blocks_push(px, py, state, info):
                return state, False, []
            new_wood = (state.wood - {(tx, ty)}) | {(px, py)}
            ns = FAState(
                ax=tx, ay=ty,
                rocks=state.rocks,
                wood=new_wood,
                crates=state.crates,
                pickups=state.pickups,
                bridges=state.bridges,
                inventory=state.inventory,
            )
            events = [
                {"type": "object_pushed", "kind": "wood",
                 "from": [tx, ty], "to": [px, py], "direction": direction},
                {"type": "avatar_entered", "position": [tx, ty],
                 "from": [ax, ay], "direction": direction},
            ]
            ns, post_ev = _apply_post_move_rules(ns, info)
            return ns, _check_win(ns, info), events + post_ev

    # ── Metal crate at target ─────────────────────────────────────────────────
    if (tx, ty) in state.crates:
        px, py = tx + dx, ty + dy
        if _blocks_push(px, py, state, info):
            return state, False, []

        new_crates = state.crates - {(tx, ty)}
        new_bridges = state.bridges
        crate_events: List[Event] = [
            {"type": "object_pushed", "kind": "metal_crate",
             "from": [tx, ty], "to": [px, py], "direction": direction},
        ]

        if _is_water(px, py, state, info):
            # crate_creates_bridge: crate sinks, water becomes bridge
            new_bridges = state.bridges | {(px, py)}
            crate_events.append({"type": "bridge_created", "position": [px, py]})
            # crate is NOT added back — it's consumed
        else:
            new_crates = new_crates | {(px, py)}

        ns = FAState(
            ax=tx, ay=ty,
            rocks=state.rocks,
            wood=state.wood,
            crates=new_crates,
            pickups=state.pickups,
            bridges=new_bridges,
            inventory=state.inventory,
        )
        events = crate_events + [
            {"type": "avatar_entered", "position": [tx, ty],
             "from": [ax, ay], "direction": direction},
        ]
        ns, post_ev = _apply_post_move_rules(ns, info)
        return ns, _check_win(ns, info), events + post_ev

    # ── Portal at target ──────────────────────────────────────────────────────
    partner = info.portals.get((tx, ty))
    if partner is not None:
        dest_x, dest_y = partner
        ns = FAState(
            ax=dest_x, ay=dest_y,
            rocks=state.rocks,
            wood=state.wood,
            crates=state.crates,
            pickups=state.pickups,
            bridges=state.bridges,
            inventory=state.inventory,
        )
        events = [
            {"type": "avatar_entered", "position": [dest_x, dest_y],
             "from": [ax, ay], "direction": direction},
        ]
        ns, post_ev = _apply_post_move_rules(ns, info)
        return ns, _check_win(ns, info), events + post_ev

    # ── Clear move (empty / bridge / water / pickup) ──────────────────────────
    ns = FAState(
        ax=tx, ay=ty,
        rocks=state.rocks,
        wood=state.wood,
        crates=state.crates,
        pickups=state.pickups,
        bridges=state.bridges,
        inventory=state.inventory,
    )
    events = [
        {"type": "avatar_entered", "position": [tx, ty],
         "from": [ax, ay], "direction": direction},
    ]
    ns, post_ev = _apply_post_move_rules(ns, info)
    return ns, _check_win(ns, info), events + post_ev


# ---------------------------------------------------------------------------
# Heuristic (for A*)
# ---------------------------------------------------------------------------

def heuristic(state: FAState, info: LevelInfo) -> float:
    """
    Admissible heuristic: BFS shortest path from avatar to flag on current
    walkable cells, treating rocks, wood, and crates as walls.

    Portals are traversable at cost 1 (entering portal = one move).
    Bridges are traversable (already converted from water).

    Returns float('inf') only when the flag is provably unreachable AND no
    tools remain to clear any obstacle.  When tools are available, falls back
    to Manhattan distance (still admissible; never overestimates).
    """
    blocked = state.rocks | state.wood | state.crates
    start = (state.ax, state.ay)
    goal = info.flag

    if start == goal:
        return 0.0

    queue: deque = deque([(start, 0)])
    visited: set = {start}

    while queue:
        (cx, cy), cost = queue.popleft()

        for ddx, ddy in _DELTA.values():
            nx, ny = cx + ddx, cy + ddy
            if not _in_bounds(nx, ny, info):
                continue
            if (nx, ny) in blocked:
                continue
            if (nx, ny) in visited:
                continue

            new_cost = cost + 1
            if (nx, ny) == goal:
                return float(new_cost)

            visited.add((nx, ny))
            queue.append(((nx, ny), new_cost))

            # Portals are traversable: enqueue partner at same cost step
            partner = info.portals.get((nx, ny))
            if partner is not None and partner not in visited:
                if partner == goal:
                    return float(new_cost)
                visited.add(partner)
                queue.append((partner, new_cost))

    # No path found.  If tools remain (inventory, pickups on board, or
    # clearable obstacles), a future action may open a path — use Manhattan
    # distance as the admissible fallback rather than pruning the branch.
    has_potential = (
        state.inventory is not None
        or any(True for _ in state.pickups)
        or bool(state.rocks)
        or bool(state.wood)
    )
    if not has_potential:
        return float("inf")

    # Manhattan distance — always admissible
    return float(abs(state.ax - info.flag[0]) + abs(state.ay - info.flag[1]))


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------

def can_prune(
    state: FAState, info: LevelInfo, depth: int, max_depth: int
) -> bool:
    """Dead-end detection is delegated to heuristic() returning inf."""
    return False
