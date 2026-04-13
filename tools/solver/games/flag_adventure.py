"""
Flag Adventure (Carrot Quest) game simulator for the GridPonder puzzle solver.

Faithfully implements the avatar_navigation + push_objects + portals + ice_slide
DSL systems from the Dart engine, plus the pickup_item, water_clears_items,
crate_creates_bridge, torch_melts_ice, and pickaxe_breaks_ice rules.

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
    ice_cells: FrozenSet[Tuple[int, int]]      # remaining ice (mutable — can be melted/broken)
    extra_water: FrozenSet[Tuple[int, int]]    # water cells created by torch-melts-ice


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

    # ── Ground layer → water + ice cells ────────────────────────────────────
    water_list: list = []
    ice_list: list = []
    ground = layers.get("ground", {})
    if isinstance(ground, dict):
        for entry in ground.get("entries", []):
            kind = entry.get("kind", "")
            x, y = entry["position"]
            if kind == "water":
                water_list.append((x, y))
            elif kind == "ice":
                ice_list.append((x, y))
    elif isinstance(ground, list):
        for row_idx, row in enumerate(ground):
            for col_idx, kind in enumerate(row):
                if kind == "water":
                    water_list.append((col_idx, row_idx))
                elif kind == "ice":
                    ice_list.append((col_idx, row_idx))

    # ── Portal channel collector (used by both layers below) ────────────────
    portal_by_channel: Dict[str, List[Tuple[int, int]]] = {}

    # ── Portals layer (new format — dedicated layer) ─────────────────────────
    portals_layer = layers.get("portals", {})
    portals_entries = (
        portals_layer.get("entries", []) if isinstance(portals_layer, dict) else []
    )
    for entry in portals_entries:
        x, y = entry["position"]
        # channel stored directly on entry OR in params sub-dict
        channel = entry.get("channel") or (entry.get("params") or {}).get("channel", "")
        if channel:
            portal_by_channel.setdefault(str(channel), []).append((x, y))

    # ── Objects layer → rocks, wood, crates, pickups, legacy portals ─────────
    rocks_list: list = []
    wood_list: list = []
    crates_list: list = []
    pickups_list: list = []

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
            # Legacy: portals stored in objects layer
            channel = entry.get("channel", "")
            if channel:
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

    # ── Avatar ───────────────────────────────────────────────────────────────
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
        ice_cells=frozenset(ice_list),
        extra_water=frozenset(),
    )
    return initial, info


# ---------------------------------------------------------------------------
# Mechanics helpers
# ---------------------------------------------------------------------------

def _in_bounds(x: int, y: int, info: LevelInfo) -> bool:
    return 0 <= x < info.width and 0 <= y < info.height


def _is_water(x: int, y: int, state: FAState, info: LevelInfo) -> bool:
    """True if (x, y) is currently water (not yet bridged, includes melted ice)."""
    if (x, y) in state.bridges:
        return False
    return (x, y) in info.water_cells or (x, y) in state.extra_water


def _has_solid(x: int, y: int, state: FAState) -> bool:
    """True if a solid non-pickup object occupies (x, y)."""
    return (x, y) in state.rocks or (x, y) in state.wood or (x, y) in state.crates


def _pickup_at(x: int, y: int, state: FAState) -> Optional[str]:
    """Return the kind of pickup at (x, y), or None."""
    for px, py, kind in state.pickups:
        if px == x and py == y:
            return kind
    return None


def _blocks_move(x: int, y: int, state: FAState, info: LevelInfo) -> bool:
    """True if (x, y) cannot be entered by avatar (out-of-bounds or solid)."""
    if not _in_bounds(x, y, info):
        return True
    return _has_solid(x, y, state)


def _blocks_push(x: int, y: int, state: FAState, info: LevelInfo) -> bool:
    """
    True if position (x, y) cannot receive a pushed object.
    A pushed object can land on any in-bounds cell not occupied by another
    solid object or a pickup.  Water cells are fine for wood; crate-into-water
    triggers the bridge rule.  Ice cells are walkable, not blocking.
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
        ice_cells=state.ice_cells,
        extra_water=state.extra_water,
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
        ice_cells=state.ice_cells,
        extra_water=state.extra_water,
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
# Object slide / teleport helpers
# ---------------------------------------------------------------------------

def _teleport_object(
    state: FAState,
    obj_kind: str,
    from_pos: Tuple[int, int],
    info: LevelInfo,
) -> Tuple[FAState, List[Event], Optional[Tuple[int, int]]]:
    """
    If from_pos is a portal and exit is clear, teleport the object.
    Returns (new_state, events, final_pos).  final_pos is None if not teleported.
    """
    partner = info.portals.get(from_pos)
    if partner is None:
        return state, [], None
    px, py = partner
    if _has_solid(px, py, state):
        return state, [], None  # exit blocked — object stays

    # Move object from from_pos to partner
    if obj_kind == "wood":
        new_wood = (state.wood - {from_pos}) | {partner}
        ns = FAState(
            ax=state.ax, ay=state.ay,
            rocks=state.rocks, wood=new_wood, crates=state.crates,
            pickups=state.pickups, bridges=state.bridges,
            inventory=state.inventory,
            ice_cells=state.ice_cells, extra_water=state.extra_water,
        )
    elif obj_kind == "metal_crate":
        new_crates = (state.crates - {from_pos}) | {partner}
        ns = FAState(
            ax=state.ax, ay=state.ay,
            rocks=state.rocks, wood=state.wood, crates=new_crates,
            pickups=state.pickups, bridges=state.bridges,
            inventory=state.inventory,
            ice_cells=state.ice_cells, extra_water=state.extra_water,
        )
    else:
        return state, [], None

    events = [{"type": "object_placed", "position": list(partner),
               "kind": obj_kind, "wasTeleported": True}]
    return ns, events, partner


def _apply_object_slide(
    state: FAState,
    obj_kind: str,
    start_pos: Tuple[int, int],
    direction: str,
    info: LevelInfo,
) -> Tuple[FAState, List[Event]]:
    """
    Slide a pushed object on ice until it stops.
    Handles portal teleport and crate-creates-bridge.
    Returns (new_state, events).
    """
    dx, dy = _DELTA[direction]
    events: List[Event] = []
    current_pos = start_pos

    for _ in range(12):
        # Object must be on ice to slide
        if current_pos not in state.ice_cells:
            break

        cx, cy = current_pos
        nx, ny = cx + dx, cy + dy

        if not _in_bounds(nx, ny, info):
            break  # wall
        if _blocks_push(nx, ny, state, info):
            break  # solid or pickup blocks

        # Crate into water → bridge (consume crate)
        if obj_kind == "metal_crate" and _is_water(nx, ny, state, info):
            new_crates = state.crates - {current_pos}
            new_bridges = state.bridges | {(nx, ny)}
            state = FAState(
                ax=state.ax, ay=state.ay,
                rocks=state.rocks, wood=state.wood, crates=new_crates,
                pickups=state.pickups, bridges=new_bridges,
                inventory=state.inventory,
                ice_cells=state.ice_cells, extra_water=state.extra_water,
            )
            events.append({"type": "object_pushed", "kind": "metal_crate",
                           "from": [cx, cy], "to": [nx, ny], "direction": direction})
            events.append({"type": "bridge_created", "position": [nx, ny]})
            return state, events

        # Move object to next cell
        if obj_kind == "wood":
            new_wood = (state.wood - {current_pos}) | {(nx, ny)}
            state = FAState(
                ax=state.ax, ay=state.ay,
                rocks=state.rocks, wood=new_wood, crates=state.crates,
                pickups=state.pickups, bridges=state.bridges,
                inventory=state.inventory,
                ice_cells=state.ice_cells, extra_water=state.extra_water,
            )
        elif obj_kind == "metal_crate":
            new_crates = (state.crates - {current_pos}) | {(nx, ny)}
            state = FAState(
                ax=state.ax, ay=state.ay,
                rocks=state.rocks, wood=state.wood, crates=new_crates,
                pickups=state.pickups, bridges=state.bridges,
                inventory=state.inventory,
                ice_cells=state.ice_cells, extra_water=state.extra_water,
            )
        else:
            break

        events.append({"type": "object_pushed", "kind": obj_kind,
                       "from": [cx, cy], "to": [nx, ny], "direction": direction})
        current_pos = (nx, ny)

        # Check if new position is a portal → teleport object
        partner = info.portals.get(current_pos)
        if partner is not None:
            state, tp_events, tp_dest = _teleport_object(state, obj_kind, current_pos, info)
            events.extend(tp_events)
            if tp_dest is not None:
                # Object teleported — continue sliding from partner position
                current_pos = tp_dest
            # Whether teleported or blocked, portal ends object slide
            break

    return state, events


# ---------------------------------------------------------------------------
# Ice slide (avatar)
# ---------------------------------------------------------------------------

def _apply_portal_then_slide(
    state: FAState,
    direction: str,
    info: LevelInfo,
) -> Tuple[FAState, List[Event]]:
    """
    Called after the avatar arrives at their current position via any non-portal
    move (push, rock-break, clear cell).  Mirrors the Dart engine's Phase 3 →
    Phase 5 ordering:

      Phase 3: portals_system.executeMovementResolution — teleport if on portal
      Phase 5: ice_slide_system.executeCascadeResolution — slide if on ice

    If the avatar is on a portal, teleport (exit blocked → stay; either way
    no further ice slide — portals end movement).  Otherwise run ice slide.
    """
    pos = (state.ax, state.ay)
    partner = info.portals.get(pos)
    if partner is not None:
        dest_x, dest_y = partner
        if not _has_solid(dest_x, dest_y, state):
            ns = FAState(
                ax=dest_x, ay=dest_y,
                rocks=state.rocks, wood=state.wood, crates=state.crates,
                pickups=state.pickups, bridges=state.bridges,
                inventory=state.inventory,
                ice_cells=state.ice_cells, extra_water=state.extra_water,
            )
            ev = [{"type": "avatar_entered", "position": [dest_x, dest_y],
                   "from": [state.ax, state.ay], "direction": direction,
                   "fromPosition": list(pos)}]
            return ns, ev
        # Blocked exit — stay at portal cell, no slide
        return state, []
    return _apply_ice_slide(state, direction, info)


def _apply_ice_slide(
    state: FAState,
    direction: str,
    info: LevelInfo,
) -> Tuple[FAState, List[Event]]:
    """
    Slide avatar on ice.  Called after avatar arrives at any cell.

    Each iteration:
      1. If not on ice → stop.
      2. Torch melts ice under avatar → water, stop.
      3. Pickaxe breaks ice under avatar → empty, stop.
      4. Check next cell in direction; push/slide/portal/clear.

    Portals end movement (endMovement=true).
    Returns (new_state, slide_events).
    """
    dx, dy = _DELTA[direction]
    events: List[Event] = []

    for _ in range(12):
        ax, ay = state.ax, state.ay

        # Not on ice → stop
        if (ax, ay) not in state.ice_cells:
            break

        # ── Torch melts ice → avatar stays, ice becomes water ────────────────
        if state.inventory == "torch":
            new_ice = state.ice_cells - {(ax, ay)}
            new_extra_water = state.extra_water | {(ax, ay)}
            state = FAState(
                ax=ax, ay=ay,
                rocks=state.rocks, wood=state.wood, crates=state.crates,
                pickups=state.pickups, bridges=state.bridges,
                inventory=state.inventory,
                ice_cells=new_ice, extra_water=new_extra_water,
            )
            events.append({"type": "ground_transformed", "position": [ax, ay],
                           "from": "ice", "to": "water", "animation": "melting"})
            break

        # ── Pickaxe breaks ice → avatar stays, ice removed, pickaxe consumed ─
        if state.inventory == "pickaxe":
            new_ice = state.ice_cells - {(ax, ay)}
            state = FAState(
                ax=ax, ay=ay,
                rocks=state.rocks, wood=state.wood, crates=state.crates,
                pickups=state.pickups, bridges=state.bridges,
                inventory=None,
                ice_cells=new_ice, extra_water=state.extra_water,
            )
            events.append({"type": "ground_transformed", "position": [ax, ay],
                           "from": "ice", "to": "empty", "animation": "breaking"})
            events.append({"type": "inventory_changed",
                           "oldItem": "pickaxe", "newItem": None})
            break

        # ── Next cell ─────────────────────────────────────────────────────────
        nx, ny = ax + dx, ay + dy

        if not _in_bounds(nx, ny, info):
            break  # board edge → stop

        # Rock → non-pushable, stop
        if (nx, ny) in state.rocks:
            break

        # Wood → try push then move avatar
        if (nx, ny) in state.wood:
            px, py = nx + dx, ny + dy
            if _blocks_push(px, py, state, info):
                break  # can't push → stop
            new_wood = (state.wood - {(nx, ny)}) | {(px, py)}
            state = FAState(
                ax=nx, ay=ny,
                rocks=state.rocks, wood=new_wood, crates=state.crates,
                pickups=state.pickups, bridges=state.bridges,
                inventory=state.inventory,
                ice_cells=state.ice_cells, extra_water=state.extra_water,
            )
            events.append({"type": "object_pushed", "kind": "wood",
                           "from": [nx, ny], "to": [px, py], "direction": direction})
            events.append({"type": "avatar_entered", "position": [nx, ny],
                           "from": [ax, ay], "direction": direction})
            # Slide the pushed wood object
            state, obj_ev = _apply_object_slide(state, "wood", (px, py), direction, info)
            events.extend(obj_ev)
            # Collect pickup at new avatar position, then continue slide check
            state, pu_ev = _apply_pickup(state, info)
            events.extend(pu_ev)
            continue

        # Crate → try push then move avatar
        if (nx, ny) in state.crates:
            px, py = nx + dx, ny + dy
            if _blocks_push(px, py, state, info):
                break  # can't push → stop
            new_crates = state.crates - {(nx, ny)}
            new_bridges = state.bridges
            push_events: List[Event] = [
                {"type": "object_pushed", "kind": "metal_crate",
                 "from": [nx, ny], "to": [px, py], "direction": direction},
            ]
            if _is_water(px, py, state, info):
                new_bridges = state.bridges | {(px, py)}
                push_events.append({"type": "bridge_created", "position": [px, py]})
            else:
                new_crates = new_crates | {(px, py)}
            state = FAState(
                ax=nx, ay=ny,
                rocks=state.rocks, wood=state.wood, crates=new_crates,
                pickups=state.pickups, bridges=new_bridges,
                inventory=state.inventory,
                ice_cells=state.ice_cells, extra_water=state.extra_water,
            )
            events.extend(push_events)
            events.append({"type": "avatar_entered", "position": [nx, ny],
                           "from": [ax, ay], "direction": direction})
            # Slide the pushed crate (if not into water)
            if not _is_water(px, py, state, info) and (px, py) in new_crates:
                state, obj_ev = _apply_object_slide(
                    state, "metal_crate", (px, py), direction, info)
                events.extend(obj_ev)
            state, pu_ev = _apply_pickup(state, info)
            events.extend(pu_ev)
            continue

        # Portal → teleport (if exit clear) or pass through, then stop
        partner = info.portals.get((nx, ny))
        if partner is not None:
            dest_x, dest_y = partner
            if not _has_solid(dest_x, dest_y, state):
                # Teleport
                state = FAState(
                    ax=dest_x, ay=dest_y,
                    rocks=state.rocks, wood=state.wood, crates=state.crates,
                    pickups=state.pickups, bridges=state.bridges,
                    inventory=state.inventory,
                    ice_cells=state.ice_cells, extra_water=state.extra_water,
                )
                events.append({"type": "avatar_entered",
                               "position": [dest_x, dest_y],
                               "from": [ax, ay], "direction": direction,
                               "fromPosition": [nx, ny]})
            else:
                # Blocked exit: move to portal cell, don't teleport
                state = FAState(
                    ax=nx, ay=ny,
                    rocks=state.rocks, wood=state.wood, crates=state.crates,
                    pickups=state.pickups, bridges=state.bridges,
                    inventory=state.inventory,
                    ice_cells=state.ice_cells, extra_water=state.extra_water,
                )
                events.append({"type": "avatar_entered", "position": [nx, ny],
                               "from": [ax, ay], "direction": direction})
            break  # portals always end movement

        # Clear slide move
        state = FAState(
            ax=nx, ay=ny,
            rocks=state.rocks, wood=state.wood, crates=state.crates,
            pickups=state.pickups, bridges=state.bridges,
            inventory=state.inventory,
            ice_cells=state.ice_cells, extra_water=state.extra_water,
        )
        events.append({"type": "avatar_entered", "position": [nx, ny],
                       "from": [ax, ay], "direction": direction})
        # Collect pickup at new position, then loop to check if still on ice
        state, pu_ev = _apply_pickup(state, info)
        events.extend(pu_ev)

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

    After every successful move, _apply_ice_slide runs the cascade slide,
    then _apply_post_move_rules handles pickup and water_clear at the final
    resting position.
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
                ice_cells=state.ice_cells,
                extra_water=state.extra_water,
            )
            events = [
                {"type": "object_removed", "kind": "rock",
                 "position": [tx, ty], "animation": "breaking"},
                {"type": "inventory_changed", "oldItem": "pickaxe", "newItem": None},
                {"type": "avatar_entered", "position": [tx, ty],
                 "from": [ax, ay], "direction": direction},
            ]
            ns, slide_ev = _apply_portal_then_slide(ns, direction, info)
            events.extend(slide_ev)
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
                ice_cells=state.ice_cells,
                extra_water=state.extra_water,
            )
            events = [
                {"type": "object_removed", "kind": "wood",
                 "position": [tx, ty], "animation": "burning"},
                {"type": "avatar_entered", "position": [tx, ty],
                 "from": [ax, ay], "direction": direction},
            ]
            ns, slide_ev = _apply_portal_then_slide(ns, direction, info)
            events.extend(slide_ev)
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
                ice_cells=state.ice_cells,
                extra_water=state.extra_water,
            )
            events = [
                {"type": "object_pushed", "kind": "wood",
                 "from": [tx, ty], "to": [px, py], "direction": direction},
                {"type": "avatar_entered", "position": [tx, ty],
                 "from": [ax, ay], "direction": direction},
            ]
            # Slide pushed wood and then check portal teleport for it
            ns, obj_ev = _apply_object_slide(ns, "wood", (px, py), direction, info)
            events.extend(obj_ev)
            # Avatar: check portal (Phase 3) then ice slide (Phase 5)
            ns, slide_ev = _apply_portal_then_slide(ns, direction, info)
            events.extend(slide_ev)
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
            new_bridges = state.bridges | {(px, py)}
            crate_events.append({"type": "bridge_created", "position": [px, py]})
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
            ice_cells=state.ice_cells,
            extra_water=state.extra_water,
        )
        events = crate_events + [
            {"type": "avatar_entered", "position": [tx, ty],
             "from": [ax, ay], "direction": direction},
        ]
        # Slide pushed crate (only if it landed on a non-water cell)
        if not _is_water(px, py, state, info) and (px, py) in new_crates:
            ns, obj_ev = _apply_object_slide(ns, "metal_crate", (px, py), direction, info)
            events.extend(obj_ev)
        # Avatar: check portal (Phase 3) then ice slide (Phase 5)
        ns, slide_ev = _apply_portal_then_slide(ns, direction, info)
        events.extend(slide_ev)
        ns, post_ev = _apply_post_move_rules(ns, info)
        return ns, _check_win(ns, info), events + post_ev

    # ── Portal at target ──────────────────────────────────────────────────────
    partner = info.portals.get((tx, ty))
    if partner is not None:
        dest_x, dest_y = partner
        if _has_solid(dest_x, dest_y, state):
            # Exit blocked: avatar moves to portal cell but is NOT teleported
            ns = FAState(
                ax=tx, ay=ty,
                rocks=state.rocks,
                wood=state.wood,
                crates=state.crates,
                pickups=state.pickups,
                bridges=state.bridges,
                inventory=state.inventory,
                ice_cells=state.ice_cells,
                extra_water=state.extra_water,
            )
            events = [
                {"type": "avatar_entered", "position": [tx, ty],
                 "from": [ax, ay], "direction": direction},
            ]
            # No ice slide — portal cell ends movement even when blocked
            ns, post_ev = _apply_post_move_rules(ns, info)
            return ns, _check_win(ns, info), events + post_ev

        # Teleport to partner
        ns = FAState(
            ax=dest_x, ay=dest_y,
            rocks=state.rocks,
            wood=state.wood,
            crates=state.crates,
            pickups=state.pickups,
            bridges=state.bridges,
            inventory=state.inventory,
            ice_cells=state.ice_cells,
            extra_water=state.extra_water,
        )
        events = [
            {"type": "avatar_entered", "position": [dest_x, dest_y],
             "from": [ax, ay], "direction": direction,
             "fromPosition": [tx, ty]},
        ]
        # No ice slide after portal teleport (portals end movement)
        ns, post_ev = _apply_post_move_rules(ns, info)
        return ns, _check_win(ns, info), events + post_ev

    # ── Clear move (empty / bridge / water / ice / pickup) ───────────────────
    ns = FAState(
        ax=tx, ay=ty,
        rocks=state.rocks,
        wood=state.wood,
        crates=state.crates,
        pickups=state.pickups,
        bridges=state.bridges,
        inventory=state.inventory,
        ice_cells=state.ice_cells,
        extra_water=state.extra_water,
    )
    events = [
        {"type": "avatar_entered", "position": [tx, ty],
         "from": [ax, ay], "direction": direction},
    ]
    ns, slide_ev = _apply_portal_then_slide(ns, direction, info)
    events.extend(slide_ev)
    ns, post_ev = _apply_post_move_rules(ns, info)
    return ns, _check_win(ns, info), events + post_ev


# ---------------------------------------------------------------------------
# Heuristic (for A*)
# ---------------------------------------------------------------------------

def heuristic(state: FAState, info: LevelInfo) -> float:
    """
    Admissible heuristic: BFS shortest path from avatar to flag on current
    walkable cells, treating rocks, wood, and crates as walls.

    Ice cells are walkable (slippery but passable).
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
