"""
Twinseed Cython solver wrapper.

Provides the same (load, apply, heuristic, can_prune, ACTIONS) interface as
games.twinseed, but backed by the Cython fast engine (games.twinseed_cython).

Used by mutate_and_test.py when --cython is set, and by any caller that needs
raw search throughput over the engine-adapter based version.

Semantics must match games.twinseed.apply step-by-step; see benchmark_tw.py for
the gold-path verification.  apply() returns [] for events — callers that need
events should replay the final solution through games.twinseed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

_SOLVER = Path(__file__).parent.parent
if str(_SOLVER) not in sys.path:
    sys.path.insert(0, str(_SOLVER))

import games.twinseed_fast as _tw_fast
from games.twinseed_cython import apply_cy, heuristic_and_prune_cy, CYTHON_AVAILABLE


ACTIONS: List[str] = _tw_fast.ACTIONS

_DIR_OF = _tw_fast._DIR_OF


@dataclass
class TwinseedCyInfo:
    """Wraps FastInfo with a plain-list neighbors buffer for the C call."""
    fast: _tw_fast.FastInfo
    neighbors_list: List[int]  # flat python list of length cells_len*4 (Cython signature)
    cells_len: int
    width: int
    cost_table: object
    level_id: Any = None

    @property
    def ACTIONS(self) -> List[str]:
        return ACTIONS


def load(level_json: Dict[str, Any]) -> Tuple[bytes, TwinseedCyInfo]:
    if not CYTHON_AVAILABLE:
        raise RuntimeError(
            "twinseed_cython extension not built. Build it with:\n"
            "  cd tools/solver/games/twinseed_cython && python setup.py build_ext --inplace"
        )
    initial, fast_info = _tw_fast.load(level_json)
    info = TwinseedCyInfo(
        fast=fast_info,
        neighbors_list=list(fast_info.neighbors_flat),
        cells_len=fast_info.cells_len,
        width=fast_info.width,
        cost_table=fast_info.cost_table,
        level_id=fast_info.level_id,
    )
    return initial, info


def apply(state: bytes, action: str, info: TwinseedCyInfo) -> Tuple[bytes, bool, list]:
    action_idx = _DIR_OF.get(action, 4)
    ns, won = apply_cy(state, action_idx, info.neighbors_list, info.cells_len)
    return ns, won, []


def heuristic(state: bytes, info: TwinseedCyInfo) -> float:
    h, _ = heuristic_and_prune_cy(state, info.cost_table, info.cells_len, info.width)
    return h


def can_prune(state: bytes, info: TwinseedCyInfo, depth: int, max_depth: int) -> bool:
    # Pruning is signalled by heuristic() returning inf — astar handles that
    # path in its inner loop, so we don't need a second Cython call here.
    return False
