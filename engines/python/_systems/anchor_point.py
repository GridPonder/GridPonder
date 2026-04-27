"""AnchorPointSystem — see docs/dsl/04_systems.md."""
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


class AnchorPointSystem(GameSystem):
    """Toggles between placing a marker at the avatar's position and teleporting to it.

    First activation places ``markerKind`` in ``markerLayer`` at the avatar's
    current cell.  A second activation teleports the avatar to the marker and
    removes it.  At most one marker exists at any time.

    Config keys:
        markerKind    (str, required)  entity kind to use as marker.
        markerLayer   (str, required)  layer to store the marker in.
        action        (str, required)  action id that triggers the toggle.
        blockedByTags (list, default: ["solid"])  tags on the objects layer that
                      prevent teleportation to the marker cell.
    """

    def __init__(self, sys_id: str):
        super().__init__(sys_id, "anchor_point")

    def execute_action_resolution(
        self, action: dict, state: GameState, game: GameDef
    ) -> list[dict]:
        config = game.system_config(self.id)
        marker_kind = config.get("markerKind")
        marker_layer_id = config.get("markerLayer")
        action_id = config.get("action")
        if not (marker_kind and marker_layer_id and action_id):
            return []
        if action.get("actionId") != action_id:
            return []

        avatar_pos = state.avatar.position
        if avatar_pos is None:
            return []

        marker_layer = state.board.layers.get(marker_layer_id)
        if marker_layer is None:
            return []

        # Find existing marker (at most one).
        marker_pos = None
        for pos, entity in marker_layer.entries():
            if entity.kind == marker_kind:
                marker_pos = pos
                break

        if marker_pos is None:
            # Place marker at avatar's current position.
            marker_layer.set(avatar_pos, Entity(marker_kind))
            return []

        # Attempt teleport to marker position.
        blocked_by_tags = config.get("blockedByTags", ["solid"])
        objects_layer = state.board.layers.get("objects")
        if objects_layer is not None:
            obj = objects_layer.get(marker_pos)
            if obj is not None and any(game.has_tag(obj.kind, t) for t in blocked_by_tags):
                return []  # destination blocked — keep marker in place

        # Remove marker and move avatar.
        from_pos = avatar_pos
        marker_layer.set(marker_pos, None)
        state.avatar.position = marker_pos

        # avatar_entered intentionally omits 'direction' so ice_slide does not
        # trigger a slide after the teleport.
        return [
            ev.avatar_exited(from_pos),
            {
                "type": "avatar_entered",
                "position": marker_pos,
                "fromPosition": from_pos,
            },
        ]

