"""OverlayCursorSystem — see docs/dsl/04_systems.md."""
from __future__ import annotations
from collections import deque
from typing import Any, Optional

from .._models import (
    Pos, Entity, GameState, PendingMove, OverlayCursor,
    dir_delta, dir_opposite, is_cardinal, CARDINALS,
)
from .._game_def import GameDef
from .. import _events as ev
from ._base import GameSystem, config_list


class OverlayCursorSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "overlay_cursor")

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        if action.get("actionId") != config.get("moveAction", "move"):
            return []
        dir_str = action.get("params", {}).get("direction")
        if not dir_str or not is_cardinal(dir_str):
            return []
        overlay = state.overlay
        if overlay is None:
            return []

        anchor = config.get("anchorToAvatar", False)
        if anchor:
            ap = state.avatar.position
            nx = ap.x if ap else overlay.x
            ny = ap.y if ap else overlay.y
            return [ev.overlay_moved([nx, ny])]

        size = config_list(config, "size", [2, 2])
        ow = size[0] if size else 2
        oh = size[1] if len(size) > 1 else 2
        constrained = config.get("boundsConstrained", True)
        dx, dy = dir_delta(dir_str)
        nx, ny = overlay.x + dx, overlay.y + dy
        if constrained:
            nx = max(0, min(nx, state.board.width - ow))
            ny = max(0, min(ny, state.board.height - oh))
        if (nx, ny) != (overlay.x, overlay.y):
            _carry(state, config, overlay, nx, ny)
        state.overlay = OverlayCursor(nx, ny, overlay.width, overlay.height)
        return [ev.overlay_moved([nx, ny])]


def _carry(state: GameState, config: dict, overlay: OverlayCursor, nx: int, ny: int) -> None:
    """Translate every entity inside the old footprint on each `carryLayers`
    layer by the overlay's displacement, so the cursor can hold things."""
    board = state.board
    for layer_id in (str(l) for l in config_list(config, "carryLayers", [])):
        layer = board.layers.get(layer_id)
        if layer is None:
            continue
        held: list[tuple[int, int, Entity]] = []
        for dy in range(overlay.height):
            for dx in range(overlay.width):
                p = Pos(overlay.x + dx, overlay.y + dy)
                e = layer.get(p)
                if e is not None:
                    held.append((dx, dy, e))
                    layer.set(p, None)
        for dx, dy, e in held:
            layer.set(Pos(nx + dx, ny + dy), e)

