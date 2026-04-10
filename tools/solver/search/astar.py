"""
A* search for GridPonder puzzles.

Works with any game module that implements the extended interface:

    apply(state, action, info) -> (new_state, won, events)
    heuristic(state, info)     -> float           (optional; defaults to 0)
    can_prune(state, info, depth, max_depth) -> bool
    ACTIONS: List[str]

The heuristic must be *admissible* (never overestimates the true cost) for the
solution to be optimal.  If the module does not export heuristic(), A* degrades
to Dijkstra / BFS.

Constraints are checked eagerly: any transition whose events violate a
constraint is skipped.  See search/events.py for the constraint format.
"""

from __future__ import annotations

import heapq
import time
from typing import Any, Callable, Dict, List, Optional

from .events import violates_constraint
from .types import Solution


def astar(
    initial: Any,
    info: Any,
    module: Any,
    timeout_s: float,
    constraints: List[Dict[str, Any]],
    max_depth: int = 300,
    is_win_fn: Optional[Callable[[Any], bool]] = None,
) -> Solution:
    """
    A* search with timeout and constraint support.

    Parameters
    ----------
    initial     : initial game state (frozen/hashable)
    info        : static level info
    module      : game module (apply, heuristic, can_prune, ACTIONS)
    timeout_s   : wall-clock budget in seconds
    constraints : list of constraint dicts (see events.py)
    max_depth   : hard depth limit (safety valve)
    is_win_fn   : optional override for win detection — called as is_win_fn(state);
                  if None, win is determined by apply()'s second return value

    Returns
    -------
    Solution — timed_out=True if the budget was exhausted before a solution was
    found; path/events are empty in that case.  is_optimal=True when the full
    search space was exhausted without finding a solution (proven no solution).
    """
    heuristic_fn = getattr(module, "heuristic", None)

    def h(state: Any) -> float:
        if heuristic_fn is None:
            return 0.0
        return heuristic_fn(state, info)

    start_time = time.monotonic()
    states_explored = 0

    # visited: state → (best_g, parent_state, action, step_events)
    # parent_state is None for the initial state.
    visited: Dict[Any, Any] = {initial: (0, None, None, [])}

    h0 = h(initial)
    if h0 == float("inf"):
        return Solution(path=[], events=[], cost=0,
                        states_explored=0, is_optimal=True, timed_out=False)

    counter = 0
    # heap entries: (f, g, tie-breaker, state)
    heap: list = [(h0, 0, counter, initial)]

    while heap:
        if time.monotonic() - start_time > timeout_s:
            return Solution(path=[], events=[], cost=0,
                            states_explored=states_explored,
                            is_optimal=False, timed_out=True)

        f, g, _, state = heapq.heappop(heap)

        # Skip stale heap entries (state was already reached via a better path)
        current_g = visited[state][0]
        if current_g < g:
            continue

        states_explored += 1

        for action in module.ACTIONS:
            new_state, module_won, step_events = module.apply(state, action, info)

            # Constraint check: prune this transition if any event violates
            if constraints and any(
                violates_constraint(step_events, c) for c in constraints
            ):
                continue

            won = module_won or (is_win_fn is not None and is_win_fn(new_state))
            new_g = g + 1

            if won:
                # Reconstruct path by following parent pointers
                path = [action]
                events = [step_events]
                cur = state
                while True:
                    entry = visited[cur]
                    parent = entry[1]
                    if parent is None:
                        break
                    path.append(entry[2])
                    events.append(entry[3])
                    cur = parent
                path.reverse()
                events.reverse()
                return Solution(
                    path=path,
                    events=events,
                    cost=new_g,
                    states_explored=states_explored,
                    is_optimal=True,
                    timed_out=False,
                )

            if new_g >= max_depth:
                continue

            if module.can_prune(new_state, info, new_g, max_depth):
                continue

            # Dedup check before heuristic — avoids paying heuristic cost
            # for states already reached via a better or equal path.
            prev = visited.get(new_state)
            if prev is not None and prev[0] <= new_g:
                continue

            new_h = h(new_state)
            if new_h == float("inf"):
                continue  # heuristic signals dead end — prune

            visited[new_state] = (new_g, state, action, step_events)
            counter += 1
            heapq.heappush(heap, (new_g + new_h, new_g, counter, new_state))

    # Search exhausted with no solution found
    return Solution(path=[], events=[], cost=0,
                    states_explored=states_explored,
                    is_optimal=True, timed_out=False)
