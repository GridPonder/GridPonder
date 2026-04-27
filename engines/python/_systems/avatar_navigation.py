"""AvatarNavigationSystem — see docs/dsl/04_systems.md."""
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


class AvatarNavigationSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "avatar_navigation")

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        move_action = config.get("moveAction", "move")
        if action.get("actionId") != move_action:
            return []
        allowed = config.get("directions", list(CARDINALS))
        dir_str = action.get("params", {}).get("direction")
        if not dir_str or dir_str not in allowed:
            return []

        avatar = state.avatar
        if not avatar.enabled or avatar.position is None:
            return []

        pos = avatar.position
        board = state.board
        dx, dy = dir_delta(dir_str)
        target = Pos(pos.x + dx, pos.y + dy)

        if not board.is_in_bounds(target):
            return []
        if board.is_void(target):
            return []

        solid_handling = config.get("solidHandling", "block")
        entity_at_target = board.get_entity("objects", target)

        if entity_at_target is not None and game.has_tag(entity_at_target.kind, "solid"):
            if solid_handling == "block":
                return []
            elif solid_handling == "delegate":
                state.pending_move = PendingMove(pos, target, dir_str)
                return [ev.move_blocked(target, pos, dir_str, entity_at_target.kind)]
            return []

        state.avatar.position = target
        state.avatar.facing = dir_str
        return [ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]

