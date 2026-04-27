"""IceSlideSystem — see docs/dsl/04_systems.md."""
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


class IceSlideSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "ice_slide")

    def execute_cascade_resolution(self, trigger_events: list[dict], state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        slippery_tag = config.get("slipperyTag", "slippery")

        result = self._handle_avatar_slide(trigger_events, state, game, slippery_tag)
        if result:
            return result
        return self._handle_object_slide(trigger_events, state, game, slippery_tag)

    def _handle_avatar_slide(self, trigger_events, state, game, slippery_tag):
        for event in trigger_events:
            if event["type"] != "avatar_entered":
                continue
            pos = state.avatar.position
            if pos is None:
                continue
            ground = state.board.get_entity("ground", pos)
            if ground is None or not game.has_tag(ground.kind, slippery_tag):
                continue
            dir_str = event.get("direction")
            if not dir_str:
                continue
            dx, dy = dir_delta(dir_str)
            next_pos = Pos(pos.x + dx, pos.y + dy)
            if not state.board.is_in_bounds(next_pos) or state.board.is_void(next_pos):
                continue
            obj_at_next = state.board.get_entity("objects", next_pos)
            if obj_at_next is not None and game.has_tag(obj_at_next.kind, "solid"):
                return self._try_push_during_slide(state, game, pos, next_pos, dir_str, obj_at_next)
            next_ground = state.board.get_entity("ground", next_pos)
            if next_ground is None or not game.has_tag(next_ground.kind, "walkable"):
                continue
            state.avatar.position = next_pos
            state.avatar.facing = dir_str
            return [ev.avatar_exited(pos), ev.avatar_entered(next_pos, pos, dir_str)]
        return []

    def _try_push_during_slide(self, state, game, avatar_pos, obj_pos, dir_str, obj):
        push_sys = game.get_system_by_type("push_objects")
        if push_sys is None:
            return []
        push_cfg = push_sys.get("config", {})
        pushable_tags = push_cfg.get("pushableTags", ["pushable"])
        valid_target_tags = push_cfg.get("validTargetTags", ["walkable"])
        if not any(game.has_tag(obj.kind, t) for t in pushable_tags):
            return []
        dx, dy = dir_delta(dir_str)
        push_dest = Pos(obj_pos.x + dx, obj_pos.y + dy)
        if not state.board.is_in_bounds(push_dest) or state.board.is_void(push_dest):
            return []
        if state.board.get_entity("objects", push_dest) is not None:
            return []
        ground_at_dest = state.board.get_entity("ground", push_dest)
        if ground_at_dest is None or not any(game.has_tag(ground_at_dest.kind, t) for t in valid_target_tags):
            return []
        state.board.set_entity("objects", obj_pos, None)
        state.board.set_entity("objects", push_dest, obj)
        state.avatar.position = obj_pos
        state.avatar.facing = dir_str
        return [
            ev.object_pushed(obj.kind, obj_pos, push_dest, dir_str),
            ev.object_placed(push_dest, obj.kind, obj.params),
            ev.avatar_exited(avatar_pos),
            ev.avatar_entered(obj_pos, avatar_pos, dir_str),
        ]

    def _handle_object_slide(self, trigger_events, state, game, slippery_tag):
        pushed_dirs: dict[Pos, str] = {}
        for event in trigger_events:
            if event["type"] != "object_pushed":
                continue
            to_raw = event.get("toPosition")
            dir_str = event.get("direction")
            if to_raw is None or dir_str is None:
                continue
            to_pos = to_raw if isinstance(to_raw, Pos) else Pos.from_json(to_raw)
            pushed_dirs[to_pos] = dir_str

        for event in trigger_events:
            if event["type"] != "object_placed":
                continue
            pos_raw = event.get("position")
            if pos_raw is None:
                continue
            pos = pos_raw if isinstance(pos_raw, Pos) else Pos.from_json(pos_raw)
            ground = state.board.get_entity("ground", pos)
            if ground is None or not game.has_tag(ground.kind, slippery_tag):
                continue
            dir_str = pushed_dirs.get(pos)
            if dir_str is None:
                continue
            entity = state.board.get_entity("objects", pos)
            if entity is None:
                continue
            dx, dy = dir_delta(dir_str)
            next_pos = Pos(pos.x + dx, pos.y + dy)
            if not state.board.is_in_bounds(next_pos) or state.board.is_void(next_pos):
                continue
            obj_at_next = state.board.get_entity("objects", next_pos)
            if obj_at_next is not None and game.has_tag(obj_at_next.kind, "solid"):
                continue
            next_ground = state.board.get_entity("ground", next_pos)
            if next_ground is None or not game.has_tag(next_ground.kind, "walkable"):
                continue
            state.board.set_entity("objects", pos, None)
            state.board.set_entity("objects", next_pos, entity)
            return [
                ev.cell_cleared(pos, entity.kind),
                ev.object_pushed(entity.kind, pos, next_pos, dir_str),
                ev.object_placed(next_pos, entity.kind, entity.params),
            ]
        return []

