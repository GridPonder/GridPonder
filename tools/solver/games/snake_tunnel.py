"""
Snake Tunnel solver adapter.

Delegates game simulation to the Python engine via engine_adapter.

Heuristic: manhattan distance from each snake head to its matching tunnel,
taking the maximum across all snakes.  This is admissible because every snake
must cover at least that many cells.

Dead-end pruning: a state is dead when any unfinished snake has budget <= 0,
or when any snake's budget + all remaining food < its manhattan distance to its
tunnel.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_SOLVER = Path(__file__).parent.parent
if str(_SOLVER) not in sys.path:
    sys.path.insert(0, str(_SOLVER))

import engine_adapter as ea
from engines.python._models import Pos

_PUBLIC_PACK_DIR = Path(__file__).parent.parent.parent.parent / "packs" / "snake_tunnel"
_PRIVATE_PACK_DIR = (
    Path(__file__).parent.parent.parent.parent.parent / "gridponder-private" / "snake_tunnel"
)
PACK_DIR = _PUBLIC_PACK_DIR if _PUBLIC_PACK_DIR.is_dir() else _PRIVATE_PACK_DIR

ACTIONS: List[str] = []  # built at load time from game definition

_FOOD_VALUES: Dict[str, int] = {
    "food_1": 1,
    "food_2": 2,
    "food_3": 3,
    "food_5": 5,
    "food_6": 6,
    "food_7": 7,
    "food_9": 9,
    "food_10": 10,
}

_TUNNEL_FOR_SNAKE: Dict[str, str] = {
    "snake_red":   "tunnel_red",
    "snake_blue":  "tunnel_blue",
    "snake_green": "tunnel_green",
}

_BUDGET_VAR_FOR_SNAKE: Dict[str, str] = {
    "snake_red":   "moveBudget_red",
    "snake_blue":  "moveBudget_blue",
    "snake_green": "moveBudget_green",
}


class STInfo:
    """EngineInfo + precomputed tunnel positions."""

    __slots__ = ("engine_info", "tunnels", "level_id")

    def __init__(self, engine_info: ea.EngineInfo, tunnels: Dict[str, Pos]):
        self.engine_info = engine_info
        self.tunnels = tunnels          # {tunnel_kind: Pos}
        self.level_id = engine_info.level_id


def _extract_tunnels(level_json: dict) -> Dict[str, Pos]:
    tunnels: Dict[str, Pos] = {}
    markers = level_json["board"]["layers"].get("markers", {})
    entries = markers.get("entries", []) if isinstance(markers, dict) else []
    for entry in entries:
        kind = entry.get("kind", "")
        if kind.startswith("tunnel_"):
            pos = Pos.from_json(entry["position"])
            tunnels[kind] = pos
    return tunnels


def _snake_positions(state: ea.EngineState) -> List[Tuple[str, Pos]]:
    """Return [(snake_kind, pos), ...] for all snakes on the board."""
    gs = state.game_state
    snakes_layer = gs.board.layers.get("snakes")
    if snakes_layer is None:
        return []
    return [(e.kind, pos) for pos, e in snakes_layer.entries()]


def _remaining_food_value(state: ea.EngineState) -> int:
    gs = state.game_state
    obj_layer = gs.board.layers.get("objects")
    if obj_layer is None:
        return 0
    total = 0
    for _, entity in obj_layer.entries():
        total += _FOOD_VALUES.get(entity.kind, 0)
    return total


def load(level_json: Dict[str, Any]) -> Tuple[ea.EngineState, STInfo]:
    initial, engine_info = ea.load(level_json, PACK_DIR)
    tunnels = _extract_tunnels(level_json)
    info = STInfo(engine_info, tunnels)

    # Build ACTIONS from game definition (done once per load)
    global ACTIONS
    cols, rows = level_json["board"]["size"]
    ACTIONS = ea._build_actions(engine_info.game, cols, rows)

    return initial, info


def apply(
    state: ea.EngineState,
    action: str,
    info: STInfo,
) -> Tuple[ea.EngineState, bool, List[dict]]:
    return ea.apply(state, action, info.engine_info)


def _snake_budget(snake_kind: str, gs) -> int:
    """Return the per-snake budget for the given snake kind, or 0 if not set."""
    var = _BUDGET_VAR_FOR_SNAKE.get(snake_kind, "moveBudget")
    val = gs.variables.get(var, 0)
    return int(val) if isinstance(val, (int, float)) else 0


def heuristic(state: ea.EngineState, info: STInfo) -> float:
    """Admissible lower bound: max manhattan distance across all unfinished snakes."""
    gs = state.game_state
    snakes = _snake_positions(state)
    if not snakes:
        return float("inf")

    total_h = 0.0
    for snake_kind, pos in snakes:
        tunnel_kind = _TUNNEL_FOR_SNAKE.get(snake_kind)
        if tunnel_kind is None:
            continue
        tunnel_pos = info.tunnels.get(tunnel_kind)
        if tunnel_pos is None:
            return float("inf")
        dist = abs(pos.x - tunnel_pos.x) + abs(pos.y - tunnel_pos.y)
        if dist == 0:
            continue  # already at tunnel
        budget = _snake_budget(snake_kind, gs)
        if budget <= 0:
            return float("inf")  # stuck away from tunnel
        total_h = max(total_h, dist)

    return total_h


def can_prune(
    state: ea.EngineState,
    info: STInfo,
    depth: int,
    max_depth: int,
) -> bool:
    gs = state.game_state
    snakes = _snake_positions(state)
    if not snakes:
        return True

    food_bonus = _remaining_food_value(state)

    for snake_kind, pos in snakes:
        tunnel_kind = _TUNNEL_FOR_SNAKE.get(snake_kind)
        if tunnel_kind is None:
            continue
        tunnel_pos = info.tunnels.get(tunnel_kind)
        if tunnel_pos is None:
            return True
        dist = abs(pos.x - tunnel_pos.x) + abs(pos.y - tunnel_pos.y)
        if dist == 0:
            continue  # already at tunnel
        budget = _snake_budget(snake_kind, gs)
        if budget <= 0:
            return True  # can't move, not at tunnel
        # Conservative upper bound: own budget + all remaining food
        if budget + food_bonus < dist:
            return True

    return False
