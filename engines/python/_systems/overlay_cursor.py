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
        # A move clamped to where the overlay already is changes nothing. Packs
        # that count actions can refuse it, so bumping the edge costs no turn.
        if (nx, ny) == (overlay.x, overlay.y) and config.get("rejectNoOpMoves", False):
            return [ev.action_vetoed()]
        if (nx, ny) != (overlay.x, overlay.y):
            if not _carry(state, config, overlay, nx, ny):
                return [ev.action_vetoed()]
        state.overlay = OverlayCursor(nx, ny, overlay.width, overlay.height)
        return [ev.overlay_moved([nx, ny])]


def _carry(
    state: GameState,
    config: dict,
    overlay: OverlayCursor,
    nx: int,
    ny: int,
) -> bool:
    """Translate every entity inside the old footprint on each `carryLayers`
    layer by the overlay's displacement, so the cursor can hold things.

    Validate the complete move before mutating any layer. A carried entity may
    move into the old footprint because that cell is vacated by the same
    transaction, but it may not leave the board or overwrite an outside entity.
    """
    board = state.board
    moves: list[tuple[Any, Pos, Pos, Entity]] = []

    def inside_old_footprint(pos: Pos) -> bool:
        return (
            overlay.x <= pos.x < overlay.x + overlay.width
            and overlay.y <= pos.y < overlay.y + overlay.height
        )

    carry_layers = dict.fromkeys(
        str(layer_id) for layer_id in config_list(config, "carryLayers", [])
    )
    for layer_id in carry_layers:
        layer = board.layers.get(layer_id)
        if layer is None:
            continue
        for dy in range(overlay.height):
            for dx in range(overlay.width):
                source = Pos(overlay.x + dx, overlay.y + dy)
                entity = layer.get(source)
                if entity is None:
                    continue
                destination = Pos(nx + dx, ny + dy)
                if not board.is_in_bounds(destination):
                    return False
                if not inside_old_footprint(destination):
                    if layer.get(destination) is not None:
                        return False
                moves.append((layer, source, destination, entity))

    for layer, source, _, _ in moves:
        layer.set(source, None)
    for layer, _, destination, entity in moves:
        layer.set(destination, entity)
    return True
