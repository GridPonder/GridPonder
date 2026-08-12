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

        # Turn to face the attempted direction even when the step is refused.
        # A blocked move still spends the turn, so without this the player gets
        # no signal that anything happened — and leaning on an obstacle is a
        # deliberate way to let a turn pass.
        state.avatar.facing = dir_str

        if not board.is_in_bounds(target):
            return []
        if board.is_void(target):
            return []

        # Optional stricter ground test: the destination's ground cell must carry
        # one of these tags. Empty (the default) keeps the void-only check, so
        # every pack that omits the field behaves exactly as before.
        valid_ground_tags = config.get("validGroundTags", [])
        if valid_ground_tags:
            ground_layer = config.get("groundLayer", "ground")
            ground_entity = board.get_entity(ground_layer, target)
            if ground_entity is None or not any(
                game.has_tag(ground_entity.kind, tag) for tag in valid_ground_tags
            ):
                return []

        solid_handling = config.get("solidHandling", "block")
        # Layers checked for a `solid` blocker, in order. Defaults to objects
        # only, so packs that place blockers on other layers (NPCs on `actors`,
        # for instance) have to opt in.
        solid_layers = config.get("solidLayers", ["objects"])
        entity_at_target = None
        for layer_id in solid_layers:
            candidate = board.get_entity(str(layer_id), target)
            if candidate is not None and game.has_tag(candidate.kind, "solid"):
                entity_at_target = candidate
                break

        if entity_at_target is not None:
            if solid_handling == "block":
                return []
            elif solid_handling == "delegate":
                state.pending_move = PendingMove(pos, target, dir_str)
                return [ev.move_blocked(target, pos, dir_str, entity_at_target.kind)]
            return []

        state.avatar.position = target
        state.avatar.facing = dir_str
        return [ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]

