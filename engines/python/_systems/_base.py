"""GameSystem base class — all systems subclass this."""
from __future__ import annotations

from .._models import GameState
from .._game_def import GameDef


class GameSystem:
    def __init__(self, sys_id: str, sys_type: str):
        self.id = sys_id
        self.type = sys_type

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        return []

    def execute_movement_resolution(self, state: GameState, game: GameDef) -> list[dict]:
        return []

    def execute_cascade_resolution(self, trigger_events: list[dict], state: GameState, game: GameDef) -> list[dict]:
        return []

    def execute_npc_resolution(self, state: GameState, game: GameDef) -> list[dict]:
        return []

    def execute_load_settle(self, state: GameState, game: GameDef) -> list[dict]:
        """Settle derived board state once, at level load.

        Systems whose output is a pure function of the board (terrain driven by
        where bodies stand, for instance) need the opening board to agree with
        their own rules before the player sees it, otherwise an authored level
        can contradict itself for exactly one turn. Returns events for symmetry;
        the engine discards them, because nothing has happened yet.
        """
        return []

    # ── Observation hooks (text observations only; never change state) ──────

    def observation_object_lines(self, mco, state: GameState, game: GameDef) -> list[str]:
        """Public detail lines for one multi-cell object.

        Printed indented under the object in the "Multi-cell objects" block,
        in both named and anonymous mode, so they must not contain pack
        vocabulary (kind ids, names, layer ids). Default: none.
        """
        return []

    def observation_status_lines(
        self,
        state: GameState,
        game: GameDef,
        initial_board,
    ) -> list[str]:
        """A public status block this system maintains (header line first).

        ``initial_board`` is a zero-argument callable returning the level's
        authored board (built on first use). The renderer prints the block
        only in named mode, one block per system in declaration order.
        Default: none.
        """
        return []



def config_list(config: dict, key: str, default: list) -> list:
    """Read a list-valued config or param field, falling back only on a missing value.

    `config.get(key, default)` returns `None` for an explicit JSON null, which
    Dart's `?? default` does not. An empty list is kept: `[]` means "none of
    them", not "unset".
    """
    value = config.get(key)
    return default if value is None else value
