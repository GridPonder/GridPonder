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
from ._base import GameSystem, config_list


class RegionTransformSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "region_transform")

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        operations = config.get("operations", {})
        action_id = action.get("actionId")

        matched_op_type = None
        matched_op: dict = {}
        for _, op_def in operations.items():
            if op_def.get("action") == action_id:
                matched_op_type = op_def.get("type")
                matched_op = op_def
                break
        if matched_op_type is None:
            return []

        overlay = state.overlay
        if overlay is None:
            return []

        affected_layers = [str(l) for l in config_list(config, "affectedLayers", ["objects"])]
        board = state.board
        ox, oy = overlay.x, overlay.y
        ow, oh = overlay.width, overlay.height

        if config.get("blockOnVoid", False):
            for dy2 in range(oh):
                for dx2 in range(ow):
                    if board.is_void(Pos(ox + dx2, oy + dy2)):
                        return []

        if matched_op_type == "exchange":
            return self._exchange(matched_op, state, ox, oy, ow, oh)

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

    def _exchange(self, op: dict, state: GameState, ox: int, oy: int, w: int, h: int) -> list[dict]:
        """Swap the contents of two layers cell by cell inside the overlay.

        `pairs` translates kinds on the way across: `[first, second]` turns a
        `first` on the first layer into a `second` on the second layer and back.
        A null side means "nothing": `[null, "slot_empty"]` fills an emptied
        second-layer cell with a visible placeholder and treats that
        placeholder as nothing when it crosses back. Unpaired kinds cross
        unchanged.
        """
        layer_ids = [str(l) for l in config_list(op, "layers", [])]
        if len(layer_ids) != 2:
            return []
        board = state.board
        first = board.layers.get(layer_ids[0])
        second = board.layers.get(layer_ids[1])
        if first is None or second is None:
            return []
        to_second: dict = {}
        to_first: dict = {}
        for pair in config_list(op, "pairs", []):
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            a, b = pair
            to_second.setdefault(a, b)
            to_first.setdefault(b, a)

        def cross(entity: Optional[Entity], table: dict) -> Optional[Entity]:
            kind = entity.kind if entity is not None else None
            if kind not in table:
                return entity.copy() if entity is not None else None
            new_kind = table[kind]
            if new_kind is None:
                return None
            return Entity(str(new_kind), dict(entity.params) if entity is not None else {})

        def blank(entity: Optional[Entity], table: dict) -> bool:
            return entity is None or (entity.kind in table and table[entity.kind] is None)

        events: list[dict] = []
        for dy in range(h):
            for dx in range(w):
                p = Pos(ox + dx, oy + dy)
                if not board.is_in_bounds(p) or board.is_void(p):
                    continue
                a = first.get(p)
                b = second.get(p)
                first.set(p, cross(b, to_first))
                second.set(p, cross(a, to_second))
                a_blank = blank(a, to_second)
                b_blank = blank(b, to_first)
                if a_blank and b_blank:
                    continue
                mode = "swap" if not a_blank and not b_blank else ("lift" if b_blank else "drop")
                events.append(ev.cell_exchanged(
                    p, mode, layer_ids,
                    None if a_blank else a.kind,
                    None if b_blank else b.kind,
                ))
        events.append(ev.region_transformed("exchange"))
        return events

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

