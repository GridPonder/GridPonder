"""TileTeleportSystem — see docs/dsl/04_systems.md."""
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


class TileTeleportSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "tile_teleport")

    def execute_npc_resolution(self, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        layer_id = config.get("layer", "objects")
        board = state.board
        ground_layer = board.layers.get("ground")
        layer = board.layers.get(layer_id)
        if ground_layer is None or layer is None:
            return []

        channel_positions: dict[str, list[Pos]] = {}
        for pos, entity in ground_layer.entries():
            if not game.has_tag(entity.kind, "teleport"):
                continue
            ch = str(entity.param("channel") or "")
            channel_positions.setdefault(ch, []).append(pos)

        events: list[dict] = []
        for positions in channel_positions.values():
            if len(positions) != 2:
                continue
            p1, p2 = positions
            e1 = layer.get(p1)
            e2 = layer.get(p2)
            if e1 is not None and e2 is None:
                layer.set(p2, e1)
                layer.set(p1, None)
                events += [ev.object_removed(p1, e1.kind), ev.object_placed(p2, e1.kind, e1.params)]
            elif e2 is not None and e1 is None:
                layer.set(p1, e2)
                layer.set(p2, None)
                events += [ev.object_removed(p2, e2.kind), ev.object_placed(p1, e2.kind, e2.params)]

        return events

