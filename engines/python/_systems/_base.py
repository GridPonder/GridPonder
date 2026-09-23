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

    def execute_derive_state(self, state: GameState, game: GameDef) -> None:
        """Write variables that are pure functions of the settled state.

        Runs once per accepted turn, after every system's NPC resolution and
        the rules pass over NPC events (so after the board has finished
        changing), and once at level load, after every system's load settle.
        A system must only *read* the board here and write variables derived
        from it: a derived variable adds nothing to the state key that the
        board does not already determine, so solver dedup, undo and preview
        are unaffected. Emits no events.
        """
        return None

    def depends_on_turn_count(self, state: GameState, game: GameDef) -> bool:
        """True when this system's behaviour in ``state`` reads the turn counter.

        The state key excludes ``turn_count``, so two states with the same key
        can still play differently when a system gates on the beat (an NPC
        that acts every Nth turn). Callers that compare state keys — the
        effectful-action probe — ask this to learn that a turn which only
        advanced the counter still changed something. Default: no.
        """
        return False


def config_list(config: dict, key: str, default: list) -> list:
    """Read a list-valued config or param field, falling back only on a missing value.

    `config.get(key, default)` returns `None` for an explicit JSON null, which
    Dart's `?? default` does not. An empty list is kept: `[]` means "none of
    them", not "unset".
    """
    value = config.get(key)
    return default if value is None else value
