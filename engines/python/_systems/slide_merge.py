"""SlideMergeSystem — see docs/dsl/04_systems.md."""
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


class SlideMergeSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "slide_merge")

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        if action.get("actionId") != config.get("mergeAction", "move"):
            return []
        dir_str = action.get("params", {}).get("direction")
        if not dir_str:
            return []
        dx, dy = dir_delta(dir_str)

        mergeable_tags = config.get("mergeableTags", ["mergeable"])
        blocker_tags = config.get("blockerTags", ["solid"])
        merge_pred = config.get("mergePredicate", "equal_value")
        merge_result_mode = config.get("mergeResult", "sum")
        merge_limit = config.get("mergeLimit", 1)
        wrap = config.get("wrapAround", False)
        emit_motion = config.get("emitMotion", True)

        board = state.board
        objects_layer = board.layers.get("objects")
        if objects_layer is None:
            return []

        mergeable_tiles = [
            (pos, entity)
            for pos, entity in objects_layer.entries()
            if any(game.has_tag(entity.kind, t) for t in mergeable_tags)
        ]
        if not mergeable_tiles:
            return []

        # Sort: process from the destination side first
        reverse = dir_str in ("right", "down")
        axis = (lambda pe: pe[0].x) if dx else (lambda pe: pe[0].y)
        mergeable_tiles.sort(key=axis, reverse=reverse)

        working: dict[Pos, Entity] = {pos: entity for pos, entity in mergeable_tiles}
        merge_counts: dict[Pos, int] = {}
        orig_positions = {pos for pos, _ in mergeable_tiles}
        events_list: list[dict] = []
        moved_count = 0

        for start_pos, entity in mergeable_tiles:
            if start_pos not in working:
                continue  # consumed by earlier merge
            e = working[start_pos]

            current_pos = start_pos
            if wrap:
                next_pos = Pos((current_pos.x + dx) % board.width, (current_pos.y + dy) % board.height)
            else:
                next_pos = Pos(current_pos.x + dx, current_pos.y + dy)
            did_merge = False

            while True:
                if not board.is_in_bounds(next_pos) or board.is_void(next_pos):
                    break
                next_e = working.get(next_pos)
                if next_e is None:
                    # Check real board for non-mergeable blockers
                    if next_pos not in orig_positions:
                        real_e = objects_layer.get(next_pos)
                        if real_e is not None and any(game.has_tag(real_e.kind, t) for t in blocker_tags):
                            break
                    # Ground solid?
                    g = board.get_entity("ground", next_pos)
                    if g and game.has_tag(g.kind, "solid"):
                        break
                    current_pos = next_pos
                    if g and game.has_tag(g.kind, "teleport"):
                        break
                    if wrap:
                        next_pos = Pos((current_pos.x + dx) % board.width, (current_pos.y + dy) % board.height)
                    else:
                        next_pos = Pos(current_pos.x + dx, current_pos.y + dy)
                    continue

                # Another tile at next_pos
                if not any(game.has_tag(next_e.kind, t) for t in mergeable_tags):
                    break
                mc = merge_counts.get(next_pos, 0)
                cmc = merge_counts.get(current_pos, 0)
                if mc >= merge_limit or cmc >= merge_limit:
                    break
                can_merge = False
                if merge_pred == "equal_value":
                    can_merge = e.param("value") is not None and e.param("value") == next_e.param("value")
                elif merge_pred == "same_kind":
                    can_merge = e.kind == next_e.kind
                if not can_merge:
                    break
                av = e.param("value") or 0
                bv = next_e.param("value") or 0
                result = av * 2 if merge_result_mode == "double" else av + bv
                merged_params = {**next_e.params, "value": result}
                merged = Entity(next_e.kind, merged_params)
                del working[start_pos]
                working[next_pos] = merged
                merge_counts[next_pos] = mc + 1
                if start_pos != next_pos:
                    events_list.append(ev.cell_cleared(start_pos, e.kind))
                    if emit_motion:
                        events_list.append(ev.tile_moved(
                            start_pos, next_pos, e.kind, dict(e.params)))
                events_list.append(ev.tiles_merged(
                    next_pos, result, [av, bv],
                    sources=[start_pos, next_pos] if emit_motion else None,
                    kind=merged.kind if emit_motion else None,
                ))
                moved_count += 1
                did_merge = True
                break

            if not did_merge and current_pos != start_pos:
                del working[start_pos]
                working[current_pos] = e
                moved_count += 1
                events_list.append(ev.cell_cleared(start_pos, e.kind))
                if emit_motion:
                    events_list.append(ev.tile_moved(
                        start_pos, current_pos, e.kind, dict(e.params)))

        # Commit
        for pos, _ in mergeable_tiles:
            objects_layer.set(pos, None)
        for pos, entity in working.items():
            objects_layer.set(pos, entity)

        if moved_count == 0:
            return []
        return [ev.tiles_slid(dir_str, moved_count), *events_list]

