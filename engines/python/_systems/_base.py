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



def config_list(config: dict, key: str, default: list) -> list:
    """Read a list-valued config or param field, falling back only on a missing value.

    `config.get(key, default)` returns `None` for an explicit JSON null, which
    Dart's `?? default` does not. An empty list is kept: `[]` means "none of
    them", not "unset".
    """
    value = config.get(key)
    return default if value is None else value
