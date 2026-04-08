"""Rotate-Flip game simulator for the GridPonder solver.

State representation
--------------------
  RFState(board, ox, oy)
    board : frozenset of ((col, row), kind) — non-empty cells only
    ox/oy : overlay top-left position

Actions
-------
  move_right | move_left | move_up | move_down   — move overlay (and avatar)
  rotate                                          — CW 90° within overlay
  flip                                            — horizontal mirror within overlay

Overlay mechanics (2×2 default)
---------------------------------
  Clockwise rotate:  local (lx, ly) → (H-1-ly, lx)
  Horizontal flip:   local (lx, ly) → (W-1-lx, ly)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Optional, Tuple

Board = FrozenSet[Tuple[Tuple[int, int], str]]

ACTIONS = [
    "move_right", "move_left", "move_up", "move_down",
    "rotate", "flip",
]


# ---------------------------------------------------------------------------
# State / LevelInfo
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RFState:
    board: Board
    ox: int
    oy: int


@dataclass
class LevelInfo:
    cols: int
    rows: int
    overlay_w: int
    overlay_h: int
    goal_board: Board
    void_cells: FrozenSet[Tuple[int, int]] = frozenset()
    level_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Loading from level JSON
# ---------------------------------------------------------------------------

def _board_from_entries(entries) -> Board:
    return frozenset(
        ((e["position"][0], e["position"][1]), e["kind"])
        for e in entries
    )


def _board_from_grid(grid) -> Board:
    """Parse the 2-D targetLayers grid (list-of-rows) into a Board."""
    cells = []
    for row_idx, row in enumerate(grid):
        for col_idx, kind in enumerate(row):
            if kind is not None:
                cells.append(((col_idx, row_idx), kind))
    return frozenset(cells)


def _void_cells_from_ground(ground_layer) -> FrozenSet[Tuple[int, int]]:
    """Extract void cell positions from a dense ground layer (list of rows)."""
    if not isinstance(ground_layer, list):
        return frozenset()
    voids = []
    for row_idx, row in enumerate(ground_layer):
        for col_idx, kind in enumerate(row):
            if kind == "void":
                voids.append((col_idx, row_idx))
    return frozenset(voids)


def load(level_json: Dict[str, Any]) -> Tuple[RFState, LevelInfo]:
    cols, rows = level_json["board"]["size"]
    entries = level_json["board"]["layers"]["objects"]["entries"]
    initial_board = _board_from_entries(entries)

    ov = level_json["state"]["overlay"]
    ox0, oy0 = ov["position"]
    ow, oh = ov.get("size", [2, 2])

    # Load void cells from ground layer if present
    ground_layer = level_json["board"]["layers"].get("ground")
    void_cells = _void_cells_from_ground(ground_layer)

    goal_cfg = next(
        g for g in level_json["goals"] if g["type"] == "board_match"
    )
    goal_board = _board_from_grid(
        goal_cfg["config"]["targetLayers"]["objects"]
    )

    info = LevelInfo(
        cols=cols, rows=rows,
        overlay_w=ow, overlay_h=oh,
        goal_board=goal_board,
        void_cells=void_cells,
        level_id=level_json.get("id"),
    )
    return RFState(board=initial_board, ox=ox0, oy=oy0), info


# ---------------------------------------------------------------------------
# Mechanics
# ---------------------------------------------------------------------------

def _rotate(board_dict: dict, ox: int, oy: int, ow: int, oh: int) -> dict:
    """CW 90°: local (lx, ly) → (oh-1-ly, lx)."""
    local = {
        (lx, ly): board_dict.get((ox + lx, oy + ly))
        for lx in range(ow)
        for ly in range(oh)
    }
    result = {
        k: v for k, v in board_dict.items()
        if not (ox <= k[0] < ox + ow and oy <= k[1] < oy + oh)
    }
    for lx in range(ow):
        for ly in range(oh):
            val = local[(lx, ly)]
            if val is not None:
                result[(ox + oh - 1 - ly, oy + lx)] = val
    return result


def _flip(board_dict: dict, ox: int, oy: int, ow: int, oh: int) -> dict:
    """Horizontal mirror: local (lx, ly) → (ow-1-lx, ly)."""
    local = {
        (lx, ly): board_dict.get((ox + lx, oy + ly))
        for lx in range(ow)
        for ly in range(oh)
    }
    result = {
        k: v for k, v in board_dict.items()
        if not (ox <= k[0] < ox + ow and oy <= k[1] < oy + oh)
    }
    for lx in range(ow):
        for ly in range(oh):
            val = local[(lx, ly)]
            if val is not None:
                result[(ox + ow - 1 - lx, oy + ly)] = val
    return result


def apply(
    state: RFState, action: str, info: LevelInfo
) -> Tuple[RFState, bool]:
    ox, oy = state.ox, state.oy
    max_ox = info.cols - info.overlay_w
    max_oy = info.rows - info.overlay_h

    if action == "move_right":
        if ox >= max_ox:
            return state, False
        if (ox + 1, oy) in info.void_cells:
            return state, False
        ns = RFState(board=state.board, ox=ox + 1, oy=oy)
    elif action == "move_left":
        if ox <= 0:
            return state, False
        if (ox - 1, oy) in info.void_cells:
            return state, False
        ns = RFState(board=state.board, ox=ox - 1, oy=oy)
    elif action == "move_down":
        if oy >= max_oy:
            return state, False
        if (ox, oy + 1) in info.void_cells:
            return state, False
        ns = RFState(board=state.board, ox=ox, oy=oy + 1)
    elif action == "move_up":
        if oy <= 0:
            return state, False
        if (ox, oy - 1) in info.void_cells:
            return state, False
        ns = RFState(board=state.board, ox=ox, oy=oy - 1)
    elif action == "rotate":
        # Blocked if any overlay cell is void
        if any((ox + dx, oy + dy) in info.void_cells
               for dx in range(info.overlay_w) for dy in range(info.overlay_h)):
            return state, False
        nb = _rotate(dict(state.board), ox, oy, info.overlay_w, info.overlay_h)
        ns = RFState(board=frozenset(nb.items()), ox=ox, oy=oy)
    elif action == "flip":
        # Blocked if any overlay cell is void
        if any((ox + dx, oy + dy) in info.void_cells
               for dx in range(info.overlay_w) for dy in range(info.overlay_h)):
            return state, False
        nb = _flip(dict(state.board), ox, oy, info.overlay_w, info.overlay_h)
        ns = RFState(board=frozenset(nb.items()), ox=ox, oy=oy)
    else:
        return state, False

    won = ns.board == info.goal_board
    return ns, won


def can_prune(
    state: RFState, info: LevelInfo, depth: int, max_depth: int
) -> bool:
    return False  # no domain-specific pruning needed for small boards


# ---------------------------------------------------------------------------
# Constraint checker (used by generator)
# ---------------------------------------------------------------------------

def board_satisfies_constraints(
    board: Board, cols: int, rows: int,
    min_per: int = 1, max_per: int = 2,
) -> bool:
    """Return True if every row and column has min_per..max_per cells."""
    bd = dict(board)
    for r in range(rows):
        cnt = sum(1 for c in range(cols) if (c, r) in bd)
        if not (min_per <= cnt <= max_per):
            return False
    for c in range(cols):
        cnt = sum(1 for r in range(rows) if (c, r) in bd)
        if not (min_per <= cnt <= max_per):
            return False
    return True
