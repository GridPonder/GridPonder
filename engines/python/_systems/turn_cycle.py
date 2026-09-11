"""Cycle configured entity kinds after selected accepted actions."""
from __future__ import annotations

from .. import _events as ev
from .._game_def import GameDef
from .._models import Entity, GameState
from ._base import GameSystem, config_list


class TurnCycleSystem(GameSystem):
    """Advance board entities through a deterministic kind cycle.

    The system records whether the current action is a configured trigger during
    action resolution, then applies the cycle at its position in NPC resolution.
    Systems declared earlier observe the old kind; systems declared later
    observe the new kind.
    """

    def __init__(self, sys_id: str):
        super().__init__(sys_id, "turn_cycle")
        # TurnEngine creates systems per turn; this only bridges the accepted
        # action resolution to the NPC phase of that same turn.
        self._advance_this_turn = False

    def execute_action_resolution(
        self, action: dict, state: GameState, game: GameDef
    ) -> list[dict]:
        config = game.system_config(self.id)
        raw_trigger_actions = config_list(config, "triggerActions", [])
        if not isinstance(raw_trigger_actions, list):
            raw_trigger_actions = []
        trigger_actions = {str(value) for value in raw_trigger_actions}
        self._advance_this_turn = (
            not trigger_actions
            or action.get("actionId") in trigger_actions
        )
        return []

    def execute_npc_resolution(
        self, state: GameState, game: GameDef
    ) -> list[dict]:
        if not self._advance_this_turn:
            return []

        config = game.system_config(self.id)
        layer_id = config.get("layer")
        if not isinstance(layer_id, str):
            layer_id = "markers"
        layer = state.board.layers.get(layer_id)
        cycles = config.get("cycles")
        if layer is None or not isinstance(cycles, dict):
            return []

        events: list[dict] = []
        for position, entity in list(layer.entries()):
            next_kind = cycles.get(entity.kind)
            if not isinstance(next_kind, str):
                continue
            if next_kind not in game.entity_kinds:
                continue
            layer.set(position, Entity(next_kind, dict(entity.params)))
            events.append(
                ev.cell_transformed(
                    position, entity.kind, next_kind, layer_id
                )
            )
        return events
