"""
Twinseed solver adapter.

Delegates game simulation to the Python engine via engine_adapter,
adding a precomputed admissible heuristic for A* search.

Heuristic (precomputed at load time):
  For each garden plot, run Dijkstra over (basket_pos, last_push_dir) to find the
  minimum cost to push a basket to that plot, where cost = push_count + 2 * direction_changes.

  The direction_change penalty (2 per change) is a tight lower bound: after pushing in
  direction D, repositioning to push in a perpendicular direction requires navigating around
  the basket — at least 2 extra moves even in open space. Clone does not reduce this below 2.

  Ice-aware (admissible): a single push can slide a basket across multiple ice cells.
  We use expanded-reachability — the basket CAN stop at any intermediate ice cell (a real
  object in the actual game could stop it there). This strictly underestimates push cost
  when ice is present, preserving admissibility.

  Assignment lower bound: with N baskets and N plots, we enumerate all N! assignments and
  use the minimum total cost (optimal bipartite matching). For N ≤ 4 this is cheap; for
  larger N we fall back to the sum-of-minima, which is still admissible.

Dead-end pruning:
  If any remaining basket has push_dist = ∞ to every remaining plot, prune immediately.
  This subsumes the old corner check and also catches ice-specific dead ends.
"""

from __future__ import annotations

import heapq
import sys
from dataclasses import dataclass, field
from itertools import permutations
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_SOLVER = Path(__file__).parent.parent
if str(_SOLVER) not in sys.path:
    sys.path.insert(0, str(_SOLVER))

import engine_adapter as ea

_PACK_DIR = Path(__file__).parent.parent.parent.parent / "packs" / "twinseed"

ACTIONS: List[str] = ["move_up", "move_down", "move_left", "move_right", "clone"]

# (dx, dy, direction_name) — direction the basket MOVES when pushed
_PUSH_DIRS: List[Tuple[int, int, str]] = [
    (1,  0, "right"),
    (-1, 0, "left"),
    (0,  1, "down"),
    (0, -1, "up"),
]


# ---------------------------------------------------------------------------
# Precomputed heuristic table
# ---------------------------------------------------------------------------

@dataclass
class _HeuristicTable:
    """
    push_dist[plot_xy][basket_xy] = Dijkstra cost (push_count + 2*direction_changes)
    to move a basket from basket_xy to plot_xy on the static board.

    plot_positions: the set of initial garden plot positions (never changes after load).
    """
    plot_positions: List[Tuple[int, int]]
    push_dist: Dict[Tuple[int, int], Dict[Tuple[int, int], float]] = field(
        default_factory=dict
    )

    def min_cost_assignment(
        self,
        basket_positions: List[Tuple[int, int]],
        remaining_plots: List[Tuple[int, int]],
    ) -> float:
        """
        Minimum-cost assignment of baskets to plots (admissible lower bound).

        For N ≤ 4 baskets we enumerate all N-permutations of remaining_plots and
        take the minimum total cost — exact optimal matching in O(N! × N).
        For larger N we sum each basket's individual minimum (still admissible).
        """
        n = len(basket_positions)
        if n == 0:
            return 0.0
        if not remaining_plots:
            return float("inf")

        inf = float("inf")

        if n <= 4:
            best = inf
            for perm in permutations(remaining_plots, n):
                cost = 0.0
                for (bx, by), plot in zip(basket_positions, perm):
                    c = self.push_dist.get(plot, {}).get((bx, by), inf)
                    if c >= inf:
                        cost = inf
                        break
                    cost += c
                if cost < best:
                    best = cost
            return best

        # Fallback: sum of individual minima (still admissible)
        total = 0.0
        for bx, by in basket_positions:
            best_c = min(
                self.push_dist.get(plot, {}).get((bx, by), inf)
                for plot in remaining_plots
            )
            if best_c >= inf:
                return inf
            total += best_c
        return total


def _precompute_heuristic(board: Any, width: int, height: int) -> _HeuristicTable:
    """
    Precompute push_dist tables using Dijkstra from each garden plot.

    State:  (basket_x, basket_y, last_push_dir_or_None)
    Cost:   push_count + 2 * direction_changes

    Transitions (reverse pushes):
      Basket arrived at (cx, cy) by a push in direction (dx, dy).
      Origin O = (cx - dx*j, cy - dy*j) for j ≥ 1.
      For j > 1, all cells between O and (cx, cy) exclusive must be ice
      (the basket slid through them). But we allow stopping at ANY intermediate
      ice cell — meaning a real blocking object could stop the slide there.
      This gives a strict underestimate → admissible.

    Repositioning penalty:
      If the next push (further back in the sequence) is in a different direction
      than the current push, we pay +2 for avatar repositioning.
    """
    from engines.python._models import Pos

    ground_layer = board.layers.get("ground")
    if ground_layer is None:
        return _HeuristicTable(plot_positions=[])

    def cell_kind(x: int, y: int) -> str:
        if x < 0 or y < 0 or x >= width or y >= height:
            return "oob"
        cell = ground_layer.get(Pos(x, y))
        return cell.kind if cell is not None else "empty"

    plot_positions = [
        (pos.x, pos.y)
        for pos, ent in ground_layer.entries()
        if ent.kind == "garden_plot"
    ]

    push_dist: Dict[Tuple[int, int], Dict[Tuple[int, int], float]] = {}
    inf = float("inf")

    for (gx, gy) in plot_positions:
        # Dijkstra over (basket_pos, last_push_dir_or_None)
        dist: Dict[Tuple[Tuple[int, int], Optional[str]], float] = {}
        counter = 0

        start: Tuple[Tuple[int, int], Optional[str]] = ((gx, gy), None)
        dist[start] = 0.0
        pq: List = [(0.0, counter, (gx, gy), None)]

        while pq:
            cost, _, (cx, cy), d_in = heapq.heappop(pq)
            key = ((cx, cy), d_in)
            if dist.get(key, inf) < cost:
                continue

            for dx, dy, d_new in _PUSH_DIRS:
                # Repositioning cost: paid when THIS push direction differs from
                # the direction of the NEXT push in the sequence (d_in).
                reposition = 2 if (d_in is not None and d_new != d_in) else 0
                new_cost = cost + 1.0 + reposition

                # Walk backwards from (cx, cy) in the anti-push direction.
                j = 1
                while True:
                    ox, oy = cx - dx * j, cy - dy * j
                    kind_o = cell_kind(ox, oy)
                    if kind_o in ("oob", "void"):
                        break

                    new_key = ((ox, oy), d_new)
                    if dist.get(new_key, inf) > new_cost:
                        dist[new_key] = new_cost
                        counter += 1
                        heapq.heappush(pq, (new_cost, counter, (ox, oy), d_new))

                    # Extend j only if the current cell is ice — meaning the basket
                    # could have slid THROUGH it from a farther-back origin.
                    if kind_o == "ice":
                        j += 1
                    else:
                        break

        # Aggregate over all last-directions: keep the minimum cost per position.
        pos_dist: Dict[Tuple[int, int], float] = {}
        for (pos, _d), c in dist.items():
            if c < pos_dist.get(pos, inf):
                pos_dist[pos] = c

        push_dist[(gx, gy)] = pos_dist

    return _HeuristicTable(plot_positions=plot_positions, push_dist=push_dist)


# ---------------------------------------------------------------------------
# Info wrapper
# ---------------------------------------------------------------------------

@dataclass
class TwinseedInfo:
    engine_info: ea.EngineInfo
    level_id: Optional[str]
    width: int
    height: int
    htable: _HeuristicTable

    @property
    def ACTIONS(self) -> List[str]:
        return self.engine_info.ACTIONS


# ---------------------------------------------------------------------------
# Solver interface
# ---------------------------------------------------------------------------

def load(level_json: Dict[str, Any]) -> Tuple[ea.EngineState, TwinseedInfo]:
    """Load a twinseed level and precompute the heuristic table."""
    initial, engine_info = ea.load(level_json, _PACK_DIR)
    board = level_json.get("board", {})
    cols, rows = board.get("size", [0, 0])

    # Precompute from the actual engine board (after parsing rules/defaults).
    game_board = initial.game_state.board
    htable = _precompute_heuristic(game_board, cols, rows)

    info = TwinseedInfo(
        engine_info=engine_info,
        level_id=level_json.get("id"),
        width=cols,
        height=rows,
        htable=htable,
    )
    return initial, info


def apply(
    state: ea.EngineState, action: str, info: TwinseedInfo
) -> Tuple[ea.EngineState, bool, List[dict]]:
    """Apply one action via the Python engine."""
    return ea.apply(state, action, info.engine_info)


def heuristic(state: ea.EngineState, info: TwinseedInfo) -> float:
    """
    Admissible A* heuristic using the precomputed push_dist tables.

    For each remaining basket, look up its cost to the nearest unplanted plot
    in the precomputed table. Use optimal bipartite matching across baskets and
    plots (exact for N ≤ 4). Returns inf if any basket has no path to any plot.
    """
    gs = state.game_state
    board = gs.board

    objects_layer = board.layers.get("objects")
    ground_layer = board.layers.get("ground")
    if objects_layer is None or ground_layer is None:
        return 0.0

    baskets = [
        (pos.x, pos.y)
        for pos, entity in objects_layer.entries()
        if entity.kind == "seed_basket"
    ]
    if not baskets:
        return 0.0

    # Only consider plots that still exist in the current game state.
    remaining_plots = [
        (pos.x, pos.y)
        for pos, entity in ground_layer.entries()
        if entity.kind == "garden_plot"
    ]
    if not remaining_plots:
        return float("inf")

    return info.htable.min_cost_assignment(baskets, remaining_plots)


def can_prune(
    state: ea.EngineState, info: TwinseedInfo, depth: int, max_depth: int
) -> bool:
    """
    Prune dead states.

    Primary check (from precomputed table): if any remaining basket has
    push_dist = ∞ to every remaining plot, the level is unsolvable from
    this state — prune immediately. This subsumes the old corner check
    and also catches ice-specific dead ends.

    Secondary check: heuristic returns inf (catches cases like no plots
    remaining with baskets still present).
    """
    gs = state.game_state
    board = gs.board

    objects_layer = board.layers.get("objects")
    ground_layer = board.layers.get("ground")
    if objects_layer is None or ground_layer is None:
        return False

    remaining_plots = [
        (pos.x, pos.y)
        for pos, entity in ground_layer.entries()
        if entity.kind == "garden_plot"
    ]

    inf = float("inf")

    for pos, entity in objects_layer.entries():
        if entity.kind != "seed_basket":
            continue

        bx, by = pos.x, pos.y

        # A basket sitting on a garden_plot: it hasn't been planted yet (that
        # requires a push event), but it can still be pushed to any other plot.
        # Push_dist for (bx,by) → same plot = 0, so it won't be pruned.

        reachable = any(
            info.htable.push_dist.get(plot, {}).get((bx, by), inf) < inf
            for plot in remaining_plots
        )
        if not reachable:
            return True

    return False


def _wall_or_solid(board: Any, x: int, y: int) -> bool:
    """True if the cell is out of bounds, void, or holds a non-basket solid."""
    from engines.python._models import Pos
    if x < 0 or y < 0 or x >= board.width or y >= board.height:
        return True
    p = Pos(x, y)
    ground = board.layers.get("ground")
    if ground is not None:
        g = ground.get(p)
        if g is not None and g.kind == "void":
            return True
    objects = board.layers.get("objects")
    if objects is not None:
        obj = objects.get(p)
        if obj is not None and obj.kind != "seed_basket":
            return True
    return False
