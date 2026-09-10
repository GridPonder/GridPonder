"""Rotate a configured board entity when the player taps its cell."""
from __future__ import annotations

from .. import _events as ev
from .._game_def import GameDef
from .._models import Entity, GameState, Pos
from ._base import GameSystem, config_list


class CellRotationSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "cell_rotation")

    def execute_action_resolution(
        self, action: dict, state: GameState, game: GameDef
    ) -> list[dict]:
        config = game.system_config(self.id)
        if action.get("actionId") != config.get("rotateAction", "rotate_cell"):
            return []

        raw_position = action.get("params", {}).get("position")
        try:
            position = Pos.from_json(raw_position)
        except (KeyError, TypeError, ValueError, IndexError):
            return [ev.action_vetoed()]
        if not state.board.is_in_bounds(position):
            return [ev.action_vetoed()]

        layer_id = config.get("layer", "ground")
        entity = state.board.get_entity(layer_id, position)
        if entity is None:
            return [ev.action_vetoed()]

        cycles = config.get("cycles") or {}
        next_kind = cycles.get(entity.kind)
        if not isinstance(next_kind, str) or next_kind not in game.entity_kinds:
            return [ev.action_vetoed()]

        blocking_layers = config_list(config, "blockingLayers", ["objects"])
        blocking_tags = config_list(config, "blockingTags", [])
        for blocking_layer in blocking_layers:
            blocker = state.board.get_entity(str(blocking_layer), position)
            if blocker is None:
                continue
            if not blocking_tags or any(
                game.has_tag(blocker.kind, str(tag)) for tag in blocking_tags
            ):
                return [ev.action_vetoed()]

        state.board.set_entity(
            layer_id, position, Entity(next_kind, dict(entity.params))
        )
        return [ev.cell_transformed(position, entity.kind, next_kind, layer_id)]
