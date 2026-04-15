"""
GridPonder Python Engine.

A faithful Python implementation of the GridPonder DSL engine, mirroring the
Dart engine in engines/dart/.  Reads game.json + level JSON and executes the
same 7-phase turn pipeline as the Dart engine.

Quick start::

    from engines.python import TurnEngine
    from engines.python.loader import load_pack

    game, levels = load_pack('packs/flag_adventure')
    engine = TurnEngine(game, levels['fw_001'])
    result = engine.execute_turn('move', {'direction': 'right'})
    print(engine.is_won)

For solver use, state snapshots are available via::

    key = engine.state_key()   # hashable tuple for BFS/A* visited tracking
    snap = engine.state.copy() # full mutable copy for branching
"""
__version__ = "0.5.0"

from ._game_def import GameDef
from ._models import GameState, Pos, Entity, Board, AvatarState
from ._turn_engine import TurnEngine, TurnResult
from .loader import load_pack, make_engine

__all__ = [
    "__version__",
    "GameDef",
    "GameState",
    "Pos",
    "Entity",
    "Board",
    "AvatarState",
    "TurnEngine",
    "TurnResult",
    "load_pack",
    "make_engine",
]
