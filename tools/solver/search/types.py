"""Shared result types for all GridPonder search algorithms."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Solution:
    """
    The result of a search.

    path           — ordered list of action strings (e.g. ["left", "right"])
    events         — per-step list of DSL event dicts (same vocabulary as the
                     Dart engine's event.dart); empty list per step for games
                     that do not yet emit events
    cost           — number of moves (== len(path))
    states_explored — how many states were expanded during the search
    is_optimal     — True if the algorithm guarantees this is the shortest path
                     (BFS always; A* when search completes without timeout)
    timed_out      — True if the search was cut short by the timeout budget;
                     path/events are empty in this case
    """
    path: List[str]
    events: List[List[Dict[str, Any]]]
    cost: int
    states_explored: int
    is_optimal: bool
    timed_out: bool = False
