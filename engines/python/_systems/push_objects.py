"""PushObjectsSystem — see docs/dsl/04_systems.md."""
from __future__ import annotations
from collections import deque
from typing import Any, Optional

from .._models import (
    Pos, Entity, GameState, PendingMove, OverlayCursor,
    dir_delta, dir_opposite, is_cardinal, CARDINALS,
)
from .._game_def import GameDef
from .. import _events as ev
from ._base import GameSystem


class PushObjectsSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "push_objects")

    def execute_movement_resolution(self, state: GameState, game: GameDef) -> list[dict]:
        pm = state.pending_move
        if pm is None:
            return []

        config = game.system_config(self.id)
        pushable_tags = [t for t in config.get("pushableTags", ["pushable"])]
        valid_target_tags = [t for t in config.get("validTargetTags", ["walkable"])]
        chain_push = config.get("chainPush", False)
        tool_interactions = config.get("toolInteractions", [])

        board = state.board
        objects_layer = board.layers.get("objects")
        ground_layer = board.layers.get("ground")
        if objects_layer is None:
            return []

        entity_at_target = objects_layer.get(pm.to_pos)
        if entity_at_target is None:
            return []

        from_pos, to_pos, direction = pm.from_pos, pm.to_pos, pm.direction
        dx, dy = dir_delta(direction)

        # Tool interactions (pickaxe breaks rock, torch burns wood)
        for interaction in tool_interactions:
            req_item = interaction.get("item")
            target_tag = interaction.get("targetTag")
            if req_item is None or target_tag is None:
                continue
            if state.avatar.item != req_item:
                continue
            if not game.has_tag(entity_at_target.kind, target_tag):
                continue
            # Destroy entity, move avatar
            board.set_entity("objects", to_pos, None)
            state.pending_move = None
            state.avatar.position = to_pos
            state.avatar.facing = direction
            if interaction.get("consumeItem", False):
                state.avatar.item = None
            anim = interaction.get("animation")
            return [
                ev.object_removed(to_pos, entity_at_target.kind, anim),
                ev.cell_cleared(to_pos, entity_at_target.kind),
                ev.avatar_exited(from_pos),
                ev.avatar_entered(to_pos, from_pos, direction),
            ]

        is_pushable = any(game.has_tag(entity_at_target.kind, t) for t in pushable_tags)
        if not is_pushable:
            return []

        push_dest = Pos(to_pos.x + dx, to_pos.y + dy)
        if not board.is_in_bounds(push_dest) or board.is_void(push_dest):
            return []

        entity_at_push_dest = objects_layer.get(push_dest)

        if entity_at_push_dest is not None:
            if not chain_push:
                return []
            chain_pushable = any(game.has_tag(entity_at_push_dest.kind, t) for t in pushable_tags)
            if not chain_pushable:
                return []
            chain_dest = Pos(push_dest.x + dx, push_dest.y + dy)
            if not board.is_in_bounds(chain_dest) or board.is_void(chain_dest):
                return []
            if objects_layer.get(chain_dest) is not None:
                return []
            if not _valid_ground(ground_layer, chain_dest, valid_target_tags, game):
                return []
            board.set_entity("objects", push_dest, None)
            board.set_entity("objects", chain_dest, entity_at_push_dest)

        if not _valid_ground(ground_layer, push_dest, valid_target_tags, game):
            return []

        board.set_entity("objects", to_pos, None)
        board.set_entity("objects", push_dest, entity_at_target)
        state.pending_move = None
        state.avatar.position = to_pos
        state.avatar.facing = direction

        return [
            ev.object_pushed(entity_at_target.kind, to_pos, push_dest, direction),
            ev.object_placed(push_dest, entity_at_target.kind, entity_at_target.params),
            ev.avatar_exited(from_pos),
            ev.avatar_entered(to_pos, from_pos, direction),
        ]


def _valid_ground(ground_layer, pos: Pos, valid_tags: list[str], game: GameDef) -> bool:
    if ground_layer is None:
        return False
    g = ground_layer.get(pos)
    if g is None:
        return False
    return any(game.has_tag(g.kind, t) for t in valid_tags)

