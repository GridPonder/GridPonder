"""SidedBoxSystem — see docs/dsl/04_systems.md."""
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


_SIDE_U, _SIDE_R, _SIDE_D, _SIDE_L = 1, 2, 4, 8


def _side_bit(direction: str) -> int:
    return {"up": _SIDE_U, "right": _SIDE_R, "down": _SIDE_D, "left": _SIDE_L}.get(direction, 0)


class SidedBoxSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "sided_box")

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        if action.get("actionId") != config.get("moveAction", "move"):
            return []
        dir_str = action.get("params", {}).get("direction")
        if not dir_str or not is_cardinal(dir_str):
            return []

        avatar = state.avatar
        if not avatar.enabled or avatar.position is None:
            return []
        pos = avatar.position
        board = state.board
        dx, dy = dir_delta(dir_str)
        target = Pos(pos.x + dx, pos.y + dy)

        if not board.is_in_bounds(target) or board.is_void(target):
            return []

        sided_tag = config.get("sidedTag", "sided")
        sides_param = config.get("sidesParam", "sides")
        valid_ground_tags = config.get("validGroundTags", ["walkable"])
        tool_interactions = config.get("toolInteractions", [])

        objects_layer = board.layers.get("objects")
        ground_layer = board.layers.get("ground")

        def is_sided(e: Optional[Entity]) -> bool:
            return e is not None and game.has_tag(e.kind, sided_tag)

        def sides(e: Entity) -> int:
            return e.param(sides_param) or 0

        def valid_ground(p: Pos) -> bool:
            if ground_layer is None:
                return False
            g = ground_layer.get(p)
            return g is not None and any(game.has_tag(g.kind, t) for t in valid_ground_tags)

        ea = objects_layer.get(pos) if objects_layer else None
        et = objects_layer.get(target) if objects_layer else None

        out_bit = _side_bit(dir_str)
        in_bit = _side_bit(dir_opposite(dir_str))
        perp_mask = (_SIDE_L | _SIDE_R) if dir_str in ("up", "down") else (_SIDE_U | _SIDE_D)

        # CASE 1: Carry
        if is_sided(ea) and (sides(ea) & out_bit) != 0:
            if not board.is_in_bounds(target) or board.is_void(target):
                return []
            if et is not None and not is_sided(et) and game.has_tag(et.kind, "solid"):
                return []
            if is_sided(et):
                if (sides(et) & in_bit) != 0:
                    return []
                if (sides(ea) & sides(et) & perp_mask) != 0:
                    return []
                merged = sides(ea) | sides(et)
                merged_entity = Entity(ea.kind, {**ea.params, sides_param: merged})
                board.set_entity("objects", pos, None)
                board.set_entity("objects", target, merged_entity)
                state.avatar.position = target
                state.avatar.facing = dir_str
                return [ev.boxes_merged(target, merged, sides(ea), sides(et)), ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]
            if et is not None and not is_sided(et):
                return []
            board.set_entity("objects", pos, None)
            board.set_entity("objects", target, ea)
            state.avatar.position = target
            state.avatar.facing = dir_str
            return [ev.object_pushed(ea.kind, pos, target, dir_str), ev.object_placed(target, ea.kind, ea.params), ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]

        # CASE 2: Target has sided box
        if is_sided(et):
            if (sides(et) & in_bit) != 0:
                push_dest = Pos(target.x + dx, target.y + dy)
                if not board.is_in_bounds(push_dest) or board.is_void(push_dest) or not valid_ground(push_dest):
                    return []
                ed = objects_layer.get(push_dest) if objects_layer else None
                if is_sided(ed):
                    if (sides(et) & sides(ed) & perp_mask) != 0:
                        return []
                    merged = sides(et) | sides(ed)
                    me = Entity(et.kind, {**et.params, sides_param: merged})
                    board.set_entity("objects", target, None)
                    board.set_entity("objects", push_dest, me)
                    state.avatar.position = target
                    state.avatar.facing = dir_str
                    return [ev.object_pushed(et.kind, target, push_dest, dir_str), ev.boxes_merged(push_dest, merged, sides(et), sides(ed)), ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]
                if ed is not None:
                    return []
                board.set_entity("objects", target, None)
                board.set_entity("objects", push_dest, et)
                state.avatar.position = target
                state.avatar.facing = dir_str
                return [ev.object_pushed(et.kind, target, push_dest, dir_str), ev.object_placed(push_dest, et.kind, et.params), ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]
            else:
                state.avatar.position = target
                state.avatar.facing = dir_str
                return [ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]

        # CASE 3: Non-sided solid
        if et is not None and game.has_tag(et.kind, "solid"):
            for interaction in tool_interactions:
                req_item = interaction.get("item")
                target_tag = interaction.get("targetTag")
                if req_item is None or target_tag is None:
                    continue
                if state.avatar.item != req_item or not game.has_tag(et.kind, target_tag):
                    continue
                board.set_entity("objects", target, None)
                state.avatar.position = target
                state.avatar.facing = dir_str
                if interaction.get("consumeItem", False):
                    state.avatar.item = None
                anim = interaction.get("animation")
                return [ev.object_removed(target, et.kind, anim), ev.cell_cleared(target, et.kind), ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]
            return []

        # CASE 4: Clear
        state.avatar.position = target
        state.avatar.facing = dir_str
        return [ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]

