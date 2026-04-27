"""FloodFillSystem — see docs/dsl/04_systems.md."""
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


class FloodFillSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "flood_fill")

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        flood_action = config.get("floodAction", "flood")
        if action.get("actionId") != flood_action:
            return []
        affected_layer = config.get("affectedLayer", "objects")
        match_by = config.get("matchBy", "color")
        source_mode = config.get("sourcePosition", "avatar")
        color_cycle = config.get("colorCycle", ["red", "blue", "green", "yellow", "purple", "orange"])
        kind_transform = {k: str(v) for k, v in config.get("kindTransform", {}).items()}

        board = state.board
        layer = board.layers.get(affected_layer)
        if layer is None:
            return []

        DIRS = [Pos(0,-1), Pos(0,1), Pos(-1,0), Pos(1,0)]

        # all_of_kind mode (Classic Flood-It)
        if source_mode == "all_of_kind":
            source_kind = config.get("sourceKind", "cell_flooded")
            target_kinds = set(kind_transform.keys())
            visited = set()
            for y in range(board.height):
                for x in range(board.width):
                    if layer._cells[y][x] is not None and layer._cells[y][x].kind == source_kind:
                        visited.add(Pos(x, y))
            if not visited:
                return []
            queue: deque = deque()
            for src in list(visited):
                for d in DIRS:
                    nb = Pos(src.x + d.x, src.y + d.y)
                    if nb in visited or not board.is_in_bounds(nb):
                        continue
                    e = layer.get(nb)
                    if e is not None and e.kind in target_kinds:
                        visited.add(nb)
                        queue.append(nb)
            if not queue:
                return [ev.action_vetoed()]
            to_transform = []
            while queue:
                current = queue.popleft()
                to_transform.append(current)
                current_kind = layer.get(current).kind
                for d in DIRS:
                    nb = Pos(current.x + d.x, current.y + d.y)
                    if nb in visited or not board.is_in_bounds(nb):
                        continue
                    e = layer.get(nb)
                    if e is not None and e.kind == current_kind:
                        visited.add(nb)
                        queue.append(nb)
            affected = []
            for pos in to_transform:
                e = layer.get(pos)
                if e is None:
                    continue
                nk = kind_transform.get(e.kind)
                if nk:
                    layer.set(pos, Entity(nk, dict(e.params)))
                    affected.append(pos)
            if not affected:
                return [ev.action_vetoed()]
            return [ev.cells_flooded(affected)]

        # Single-position source
        if source_mode == "overlay_center":
            ov = state.overlay
            if ov is None:
                return []
            source_pos = Pos(ov.x + ov.width // 2, ov.y + ov.height // 2)
        elif source_mode == "action_param":
            pos_raw = action.get("params", {}).get("position")
            if pos_raw is None:
                return []
            source_pos = Pos.from_json(pos_raw)
            if state.avatar.position is not None:
                state.avatar.position = source_pos
        else:
            source_pos = state.avatar.position
            if source_pos is None:
                return []

        source_entity = layer.get(source_pos)
        if source_entity is None:
            return []

        match_value = (source_entity.param("color") or "") if match_by == "color" else source_entity.kind
        visited = {source_pos}
        queue = deque([source_pos])
        while queue:
            current = queue.popleft()
            for d in DIRS:
                nb = Pos(current.x + d.x, current.y + d.y)
                if nb in visited or not board.is_in_bounds(nb):
                    continue
                e = layer.get(nb)
                if e is None:
                    continue
                matches = (e.param("color") or "") == match_value if match_by == "color" else e.kind == match_value
                if matches:
                    visited.add(nb)
                    queue.append(nb)

        affected = []
        for pos in visited:
            e = layer.get(pos)
            if e is None:
                continue
            if match_by == "color":
                cur_color = e.param("color") or ""
                idx = color_cycle.index(cur_color) if cur_color in color_cycle else -1
                next_color = color_cycle[(idx + 1) % len(color_cycle)] if idx >= 0 else (color_cycle[0] if color_cycle else cur_color)
                new_params = {**e.params, "color": next_color}
                layer.set(pos, Entity(e.kind, new_params))
                affected.append(pos)
            else:
                nk = kind_transform.get(e.kind)
                if nk:
                    layer.set(pos, Entity(nk, dict(e.params)))
                    affected.append(pos)

        if not affected:
            return []
        return [ev.cells_flooded(affected)]

