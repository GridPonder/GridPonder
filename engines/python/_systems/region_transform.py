"""RegionTransformSystem — see docs/dsl/04_systems.md."""
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


class RegionTransformSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "region_transform")

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        operations = config.get("operations", {})
        action_id = action.get("actionId")

        matched_op_type = None
        for _, op_def in operations.items():
            if op_def.get("action") == action_id:
                matched_op_type = op_def.get("type")
                break
        if matched_op_type is None:
            return []

        overlay = state.overlay
        if overlay is None:
            return []

        affected_layers = [str(l) for l in config.get("affectedLayers", ["objects"])]
        board = state.board
        ox, oy = overlay.x, overlay.y
        ow, oh = overlay.width, overlay.height

        if config.get("blockOnVoid", False):
            for dy2 in range(oh):
                for dx2 in range(ow):
                    if board.is_void(Pos(ox + dx2, oy + dy2)):
                        return []

        dir_str = action.get("params", {}).get("direction")

        for layer_id in affected_layers:
            layer = board.layers.get(layer_id)
            if layer is None:
                continue
            # Snapshot
            snapshot: dict[Pos, Optional[Entity]] = {}
            for dy2 in range(oh):
                for dx2 in range(ow):
                    p = Pos(ox + dx2, oy + dy2)
                    if board.is_in_bounds(p):
                        snapshot[p] = layer.get(p)
            mapping = self._compute_mapping(matched_op_type, ox, oy, ow, oh, dir_str)
            mapping = {s: d for s, d in mapping.items() if not board.is_void(s) and not board.is_void(d)}
            if not mapping:
                continue
            new_values = dict(snapshot)
            for src, dst in mapping.items():
                if src in snapshot and dst in new_values:
                    new_values[dst] = snapshot[src]
            for p, e in new_values.items():
                if board.is_in_bounds(p):
                    layer.set(p, e)

        return [ev.region_transformed(matched_op_type)]

    def _compute_mapping(self, op_type, ox, oy, w, h, direction) -> dict[Pos, Pos]:
        if op_type == "rotate":
            return {Pos(ox+lx, oy+ly): Pos(ox+(h-1-ly), oy+lx) for ly in range(h) for lx in range(w)}
        if op_type == "flip":
            return {Pos(ox+lx, oy+ly): Pos(ox+(w-1-lx), oy+ly) for ly in range(h) for lx in range(w)}
        if op_type == "diagonal_swap":
            swaps = {
                "up_left":    (Pos(ox+1, oy+1), Pos(ox,   oy)),
                "up_right":   (Pos(ox,   oy+1), Pos(ox+1, oy)),
                "down_left":  (Pos(ox+1, oy),   Pos(ox,   oy+1)),
                "down_right": (Pos(ox,   oy),   Pos(ox+1, oy+1)),
            }
            pair = swaps.get(direction)
            if pair is None:
                return {}
            a, b = pair
            return {a: b, b: a}
        return {}

