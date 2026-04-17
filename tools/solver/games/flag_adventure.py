"""
Flag Adventure (Carrot Quest) solver adapter.

Delegates game simulation to the Python engine via engine_adapter, providing
only a precomputed admissible A* heuristic specific to Flag Adventure.

The heuristic is a BFS on the obstacle-free ice-slide graph, computed once at
load time from the *initial* ice configuration.  This is admissible because ice
only gets removed during play (melted/broken), and removing ice can only make
paths equal or longer (fewer cells reachable per action).
"""

from __future__ import annotations

import sys
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Make engine_adapter importable
_SOLVER = Path(__file__).parent.parent
if str(_SOLVER) not in sys.path:
    sys.path.insert(0, str(_SOLVER))

import engine_adapter as ea

# ---------------------------------------------------------------------------
# Action strings — engine adapter uses "move_up" etc.
# ---------------------------------------------------------------------------

ACTIONS: List[str] = ["move_up", "move_down", "move_left", "move_right"]

_DELTA: Dict[str, Tuple[int, int]] = {
    "move_up":    (0, -1),
    "move_down":  (0,  1),
    "move_left":  (-1, 0),
    "move_right": ( 1, 0),
}

# Pack directory for engine_adapter
_PACK_DIR = Path(__file__).parent.parent.parent.parent / "packs" / "flag_adventure"


# ---------------------------------------------------------------------------
# Info wrapper — extends EngineInfo with precomputed heuristic table
# ---------------------------------------------------------------------------

class FAInfo:
    """EngineInfo + precomputed heuristic table for A*."""

    __slots__ = ("engine_info", "h_table", "flag", "width", "height",
                 "water_cells", "portals", "level_id")

    def __init__(
        self,
        engine_info: ea.EngineInfo,
        h_table: Dict[Tuple[int, int], float],
        flag: Tuple[int, int],
        water_cells: frozenset,
        portals: Dict[Tuple[int, int], Tuple[int, int]],
    ):
        self.engine_info = engine_info
        self.h_table = h_table
        self.flag = flag
        self.width = engine_info.width
        self.height = engine_info.height
        self.water_cells = water_cells
        self.portals = portals
        self.level_id = engine_info.level_id


# ---------------------------------------------------------------------------
# Heuristic precomputation
# ---------------------------------------------------------------------------

def _precompute_heuristic(
    width: int,
    height: int,
    ice_cells: frozenset,
    void_cells: frozenset,
    portals: Dict[Tuple[int, int], Tuple[int, int]],
    flag: Tuple[int, int],
) -> Dict[Tuple[int, int], float]:
    """
    Backwards BFS from the flag on the obstacle-free ice-slide graph.

    Returns h_table: (x, y) -> minimum actions to reach the flag.
    Cells not in h_table are unreachable (h = inf).

    Admissibility argument: objects are ignored (removing them only shortens
    paths), and every intermediate cell along a slide is costed at the same
    level as the slide landing (objects could create earlier stopping points,
    so the BFS accounts for them by marking intermediates reachable at the
    same cost).

    The initial ice configuration is used.  Since ice only gets removed during
    play, the actual cost with less ice is always >= the precomputed cost:
    more ice = longer slides = more cells reachable per action.
    """
    h_table: Dict[Tuple[int, int], float] = {flag: 0.0}
    queue: deque = deque([(flag, 0)])

    def in_bounds(x: int, y: int) -> bool:
        return 0 <= x < width and 0 <= y < height

    while queue:
        (cx, cy), cost = queue.popleft()
        new_cost = cost + 1

        for ddx, ddy in _DELTA.values():
            # Simulate a slide action in this direction.
            # We explore BACKWARDS (from flag outward), but the slide physics
            # is the same: one action = slide until hitting wall/void/non-ice.
            # Enqueue every intermediate as a potential origin.
            px, py = cx, cy
            while True:
                nx, ny = px + ddx, py + ddy
                if not in_bounds(nx, ny):
                    break
                if (nx, ny) in void_cells:
                    break
                px, py = nx, ny

                if (px, py) not in h_table:
                    h_table[(px, py)] = float(new_cost)
                    queue.append(((px, py), new_cost))

                # Portal: check partner
                partner = portals.get((px, py))
                if partner is not None and partner not in h_table:
                    h_table[partner] = float(new_cost)
                    queue.append((partner, new_cost))

                if (px, py) not in ice_cells:
                    break  # slide stops (no object to block earlier)

    return h_table


def _extract_level_geometry(level_json: dict) -> tuple:
    """Extract ice cells, void cells, portals, flag from level JSON."""
    cols, rows = level_json["board"]["size"]
    layers = level_json["board"]["layers"]

    ice_cells = set()
    void_cells = set()
    water_cells = set()

    ground = layers.get("ground", {})
    if isinstance(ground, dict):
        for entry in ground.get("entries", []):
            kind = entry.get("kind", "")
            x, y = entry["position"]
            if kind == "ice":
                ice_cells.add((x, y))
            elif kind == "void":
                void_cells.add((x, y))
            elif kind == "water":
                water_cells.add((x, y))
    elif isinstance(ground, list):
        for row_idx, row in enumerate(ground):
            for col_idx, kind in enumerate(row):
                if kind == "ice":
                    ice_cells.add((col_idx, row_idx))
                elif kind == "void":
                    void_cells.add((col_idx, row_idx))
                elif kind == "water":
                    water_cells.add((col_idx, row_idx))

    # Portals — dedicated layer or legacy objects layer
    portal_by_channel: Dict[str, List[Tuple[int, int]]] = {}
    portals_layer = layers.get("portals", {})
    for entry in (portals_layer.get("entries", []) if isinstance(portals_layer, dict) else []):
        x, y = entry["position"]
        channel = entry.get("channel") or (entry.get("params") or {}).get("channel", "")
        if channel:
            portal_by_channel.setdefault(str(channel), []).append((x, y))

    obj_layer = layers.get("objects", {})
    for entry in (obj_layer.get("entries", []) if isinstance(obj_layer, dict) else []):
        if entry.get("kind") == "portal":
            x, y = entry["position"]
            channel = entry.get("channel", "")
            if channel:
                portal_by_channel.setdefault(channel, []).append((x, y))

    portals: Dict[Tuple[int, int], Tuple[int, int]] = {}
    for positions in portal_by_channel.values():
        if len(positions) == 2:
            a, b = positions
            portals[a] = b
            portals[b] = a

    # Flag
    flag_pos = (0, 0)
    markers = layers.get("markers", {})
    for entry in (markers.get("entries", []) if isinstance(markers, dict) else []):
        if entry.get("kind") == "flag":
            flag_pos = (entry["position"][0], entry["position"][1])
            break

    return (cols, rows, frozenset(ice_cells), frozenset(void_cells),
            frozenset(water_cells), portals, flag_pos)


# ---------------------------------------------------------------------------
# Solver interface
# ---------------------------------------------------------------------------

def load(level_json: Dict[str, Any]) -> Tuple[ea.EngineState, FAInfo]:
    """Load a flag_adventure level for solving."""
    initial, engine_info = ea.load(level_json, _PACK_DIR)

    cols, rows, ice_cells, void_cells, water_cells, portals, flag = \
        _extract_level_geometry(level_json)

    h_table = _precompute_heuristic(cols, rows, ice_cells, void_cells, portals, flag)

    info = FAInfo(engine_info, h_table, flag, water_cells, portals)
    return initial, info


def apply(
    state: ea.EngineState, action: str, info: FAInfo
) -> Tuple[ea.EngineState, bool, List[dict]]:
    """Apply one action via the Python engine."""
    return ea.apply(state, action, info.engine_info)


def heuristic(state: ea.EngineState, info: FAInfo) -> float:
    """
    O(1) precomputed admissible heuristic.

    Looks up the avatar's current position in the h-table precomputed at load
    time.  Returns inf for provably unreachable cells (dead-end pruning).
    """
    gs = state.game_state
    pos = gs.avatar.position
    if pos is None:
        return float("inf")
    return info.h_table.get((pos.x, pos.y), float("inf"))


def can_prune(
    state: ea.EngineState, info: FAInfo, depth: int, max_depth: int
) -> bool:
    return False
