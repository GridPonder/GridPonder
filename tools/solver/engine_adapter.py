"""
Generic engine adapter for the GridPonder puzzle solver.

Wraps the Python TurnEngine (engines/python/) to provide the standard solver
interface (load / apply / ACTIONS / can_prune) for any game pack.  Any game
with a game.json + level JSON can be solved without a hand-written simulator.

State representation
--------------------
BFS/DFS/A* need hashable states.  ``EngineState`` wraps a ``GameState`` and
delegates ``__hash__`` / ``__eq__`` to ``GameState.to_key()``.  The underlying
``GameState`` is never mutated after construction; a fresh copy is made for
every ``apply`` call.

Action strings
--------------
Actions are flattened to strings:

  * Actions with a ``direction`` param → ``"{action_id}_{direction}"``
    (e.g. ``"move_up"``, ``"diagonal_swap_up_right"``)
  * Actions with no params → ``"{action_id}"``
    (e.g. ``"flood_red"``, ``"rotate"``)

Usage
-----
::

    from engine_adapter import load, apply, can_prune, gold_path_actions

    pack_dir = Path("../../packs/diagonal_swipes")
    level_json = json.loads((pack_dir / "levels/ds_001.json").read_text())
    initial, info = load(level_json, pack_dir)

    for action in info.ACTIONS:
        new_state, won, events = apply(initial, action, info)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# Make engines/ importable when running from tools/solver/
_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engines.python._game_def import GameDef
from engines.python._models import GameState
from engines.python._turn_engine import TurnEngine
from engines.python.loader import load_pack


# ---------------------------------------------------------------------------
# EngineState — hashable wrapper around GameState
# ---------------------------------------------------------------------------

class EngineState:
    """
    Hashable snapshot of a ``GameState``.

    Immutable from the caller's perspective: ``apply`` always returns a fresh
    ``EngineState`` and never mutates an existing one.
    """

    __slots__ = ("_state", "_key", "_hash")

    def __init__(self, state: GameState) -> None:
        self._state = state
        self._key: Optional[tuple] = None
        self._hash: Optional[int] = None

    def _get_key(self) -> tuple:
        if self._key is None:
            self._key = self._state.to_key()
        return self._key

    def __hash__(self) -> int:
        if self._hash is None:
            self._hash = hash(self._get_key())
        return self._hash

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EngineState):
            return NotImplemented
        return self._get_key() == other._get_key()

    @property
    def game_state(self) -> GameState:
        return self._state


# ---------------------------------------------------------------------------
# EngineInfo — static level data (does not change during search)
# ---------------------------------------------------------------------------

@dataclass
class EngineInfo:
    """Static context passed to every ``apply`` call."""
    game: GameDef
    level_def: dict
    pack_dir: Path
    ACTIONS: list[str]        # flat action strings valid for this game
    level_id: Optional[str] = None
    width: int = 0
    height: int = 0


# ---------------------------------------------------------------------------
# Action helpers
# ---------------------------------------------------------------------------

def _build_actions(game: GameDef) -> list[str]:
    """Build the flat ACTIONS list from the game definition."""
    result: list[str] = []
    for action_def in game.actions:
        aid = action_def["id"]
        params = action_def.get("params", {})
        if "direction" in params:
            dirs = params["direction"].get("values", ["up", "down", "left", "right"])
            for d in dirs:
                result.append(f"{aid}_{d}")
        else:
            result.append(aid)
    return result


def _parse_action(action_str: str, game: GameDef) -> tuple[str, dict]:
    """Convert a flat action string back to ``(action_id, params)``."""
    for action_def in game.actions:
        aid = action_def["id"]
        params = action_def.get("params", {})
        if "direction" in params:
            dirs = params["direction"].get("values", ["up", "down", "left", "right"])
            for d in dirs:
                if action_str == f"{aid}_{d}":
                    return aid, {"direction": d}
        elif action_str == aid:
            return aid, {}
    raise ValueError(f"Unknown action string: {action_str!r}")


# ---------------------------------------------------------------------------
# Solver interface
# ---------------------------------------------------------------------------

def load(level_json: dict, pack_dir: str | Path) -> tuple[EngineState, EngineInfo]:
    """
    Load a level for generic engine-backed solving.

    Returns
    -------
    initial : EngineState
        The starting state.
    info : EngineInfo
        Static context (game def, level def, ACTIONS list, …).
    """
    pack_dir = Path(pack_dir)
    game, levels = load_pack(pack_dir)

    level_id = level_json.get("id")
    board = level_json.get("board", {})
    cols, rows = board.get("size", [0, 0])

    actions = _build_actions(game)

    info = EngineInfo(
        game=game,
        level_def=level_json,
        pack_dir=pack_dir,
        ACTIONS=actions,
        level_id=level_id,
        width=cols,
        height=rows,
    )

    # Build the initial GameState via TurnEngine's board parser
    engine = TurnEngine(game, level_json)
    initial = EngineState(engine.state.copy())
    return initial, info


def apply(
    state: EngineState,
    action_str: str,
    info: EngineInfo,
) -> tuple[EngineState, bool, list[dict]]:
    """
    Apply one action to *state*.

    Returns ``(new_state, won, events)``.  If the action is vetoed (move
    blocked, etc.) the state is unchanged and ``won`` is False.
    """
    action_id, params = _parse_action(action_str, info.game)

    # Fast-path: bypass TurnEngine.__init__ (no board re-parsing)
    engine = object.__new__(TurnEngine)
    engine._game = info.game
    engine._level = info.level_def
    engine._initial_state = state._state   # for reset() — unused in apply
    engine._state = state._state.copy()
    engine._history = []

    result = engine.execute_turn(action_id, params, save_history=False)
    new_state = EngineState(engine._state)
    return new_state, result.is_won, result.events


def can_prune(
    state: EngineState,
    info: EngineInfo,
    depth: int,
    max_depth: int,
) -> bool:
    """Generic pruning — always False.  Override in game-specific code."""
    return False


# ---------------------------------------------------------------------------
# Gold path helpers
# ---------------------------------------------------------------------------

def gold_path_actions(level_json: dict) -> list[str]:
    """
    Extract the gold path from a level JSON as flat action strings.

    Works for any game: direction-based entries become ``"{action}_{dir}"``
    and param-less entries become just ``"{action}"``.
    """
    gold_raw = level_json.get("solution", {}).get("goldPath", [])
    actions: list[str] = []
    for entry in gold_raw:
        if isinstance(entry, str):
            actions.append(entry)
        elif isinstance(entry, dict):
            action_id = entry.get("action", "move")
            direction = entry.get("direction")
            if direction:
                actions.append(f"{action_id}_{direction}")
            else:
                actions.append(action_id)
    return actions
