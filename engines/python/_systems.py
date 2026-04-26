"""
All system implementations + SystemRegistry.

Each system class implements zero or more of:
  execute_action_resolution(action, state, game) → list[dict]
  execute_movement_resolution(state, game) → list[dict]
  execute_cascade_resolution(trigger_events, state, game) → list[dict]
  execute_npc_resolution(state, game) → list[dict]

Mirrors Dart's systems/*.dart + system_registry.dart.
"""
from __future__ import annotations
from collections import deque
from typing import Any, Optional

from ._models import Pos, Entity, GameState, PendingMove, OverlayCursor, dir_delta, dir_opposite, is_cardinal, CARDINALS
from ._game_def import GameDef
from . import _events as ev


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class GameSystem:
    def __init__(self, sys_id: str, sys_type: str):
        self.id = sys_id
        self.type = sys_type

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        return []

    def execute_movement_resolution(self, state: GameState, game: GameDef) -> list[dict]:
        return []

    def execute_cascade_resolution(self, trigger_events: list[dict], state: GameState, game: GameDef) -> list[dict]:
        return []

    def execute_npc_resolution(self, state: GameState, game: GameDef) -> list[dict]:
        return []


# ---------------------------------------------------------------------------
# avatar_navigation
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# push_objects
# ---------------------------------------------------------------------------

class PushObjectsSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "push_objects")

    def execute_movement_resolution(self, state: GameState, game: GameDef) -> list[dict]:
        pm = state.pending_move
        if pm is None:
            return []

        config = game.system_config(self.id)
        pushable_tags = [t for t in config.get("pushableTags", ["pushable"])]
        valid_target_tags = [t for t in config.get("validTargetTags", ["walkable"])]
        chain_push = config.get("chainPush", False)
        tool_interactions = config.get("toolInteractions", [])

        board = state.board
        objects_layer = board.layers.get("objects")
        ground_layer = board.layers.get("ground")
        if objects_layer is None:
            return []

        entity_at_target = objects_layer.get(pm.to_pos)
        if entity_at_target is None:
            return []

        from_pos, to_pos, direction = pm.from_pos, pm.to_pos, pm.direction
        dx, dy = dir_delta(direction)

        # Tool interactions (pickaxe breaks rock, torch burns wood)
        for interaction in tool_interactions:
            req_item = interaction.get("item")
            target_tag = interaction.get("targetTag")
            if req_item is None or target_tag is None:
                continue
            if state.avatar.item != req_item:
                continue
            if not game.has_tag(entity_at_target.kind, target_tag):
                continue
            # Destroy entity, move avatar
            board.set_entity("objects", to_pos, None)
            state.pending_move = None
            state.avatar.position = to_pos
            state.avatar.facing = direction
            if interaction.get("consumeItem", False):
                state.avatar.item = None
            anim = interaction.get("animation")
            return [
                ev.object_removed(to_pos, entity_at_target.kind, anim),
                ev.cell_cleared(to_pos, entity_at_target.kind),
                ev.avatar_exited(from_pos),
                ev.avatar_entered(to_pos, from_pos, direction),
            ]

        is_pushable = any(game.has_tag(entity_at_target.kind, t) for t in pushable_tags)
        if not is_pushable:
            return []

        push_dest = Pos(to_pos.x + dx, to_pos.y + dy)
        if not board.is_in_bounds(push_dest) or board.is_void(push_dest):
            return []

        entity_at_push_dest = objects_layer.get(push_dest)

        if entity_at_push_dest is not None:
            if not chain_push:
                return []
            chain_pushable = any(game.has_tag(entity_at_push_dest.kind, t) for t in pushable_tags)
            if not chain_pushable:
                return []
            chain_dest = Pos(push_dest.x + dx, push_dest.y + dy)
            if not board.is_in_bounds(chain_dest) or board.is_void(chain_dest):
                return []
            if objects_layer.get(chain_dest) is not None:
                return []
            if not _valid_ground(ground_layer, chain_dest, valid_target_tags, game):
                return []
            board.set_entity("objects", push_dest, None)
            board.set_entity("objects", chain_dest, entity_at_push_dest)

        if not _valid_ground(ground_layer, push_dest, valid_target_tags, game):
            return []

        board.set_entity("objects", to_pos, None)
        board.set_entity("objects", push_dest, entity_at_target)
        state.pending_move = None
        state.avatar.position = to_pos
        state.avatar.facing = direction

        return [
            ev.object_pushed(entity_at_target.kind, to_pos, push_dest, direction),
            ev.object_placed(push_dest, entity_at_target.kind, entity_at_target.params),
            ev.avatar_exited(from_pos),
            ev.avatar_entered(to_pos, from_pos, direction),
        ]


def _valid_ground(ground_layer, pos: Pos, valid_tags: list[str], game: GameDef) -> bool:
    if ground_layer is None:
        return False
    g = ground_layer.get(pos)
    if g is None:
        return False
    return any(game.has_tag(g.kind, t) for t in valid_tags)


# ---------------------------------------------------------------------------
# portals
# ---------------------------------------------------------------------------

class PortalsSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "portals")

    def _config(self, game: GameDef) -> dict:
        cfg = game.system_config(self.id)
        tags_raw = cfg.get("teleportTags", ["teleport"])
        return {
            "tags": [str(t) for t in tags_raw],
            "matchKey": cfg.get("matchKey", "channel"),
            "endMovement": cfg.get("endMovement", True),
        }

    def execute_movement_resolution(self, state: GameState, game: GameDef) -> list[dict]:
        cfg = self._config(game)
        events = []
        pos = state.avatar.position
        if pos is not None:
            events.extend(self._try_teleport_avatar(state, game, pos, cfg["tags"], cfg["matchKey"], cfg["endMovement"]))
        return events

    def execute_cascade_resolution(self, trigger_events: list[dict], state: GameState, game: GameDef) -> list[dict]:
        cfg = self._config(game)
        events = []

        # Avatar portal check
        avatar_pos = state.avatar.position
        if avatar_pos is not None:
            for e in trigger_events:
                if e["type"] != "avatar_entered":
                    continue
                entered_pos = e.get("position")
                if isinstance(entered_pos, Pos):
                    ep = entered_pos
                else:
                    ep = Pos.from_json(entered_pos) if entered_pos else None
                if ep != avatar_pos:
                    continue
                # Bounce guard
                from_raw = e.get("fromPosition")
                from_pos = (from_raw if isinstance(from_raw, Pos) else Pos.from_json(from_raw)) if from_raw else None
                portal = self._portal_at(state.board, avatar_pos, cfg["tags"], game)
                if portal:
                    ch = portal[0].param(cfg["matchKey"])
                    if ch is not None:
                        exit_pos = self._find_exit_portal(state.board, avatar_pos, portal[0].kind, ch, cfg["matchKey"])
                        if exit_pos is not None and from_pos == exit_pos:
                            break
                events.extend(self._try_teleport_avatar(state, game, avatar_pos, cfg["tags"], cfg["matchKey"], cfg["endMovement"]))
                break

        # Object portal check
        arrived = {
            (e.get("position") if isinstance(e.get("position"), Pos) else Pos.from_json(e["position"]))
            for e in trigger_events
            if e["type"] == "object_placed" and not e.get("wasTeleported")
            and e.get("position") is not None
        }
        if arrived:
            events.extend(self._try_teleport_objects(state, game, cfg, arrived))

        return events

    def _try_teleport_avatar(self, state, game, avatar_pos, teleport_tags, match_key, end_movement):
        board = state.board
        portal = self._portal_at(board, avatar_pos, teleport_tags, game)
        if portal is None:
            return []
        channel = portal[0].param(match_key)
        if channel is None:
            return []
        exit_pos = self._find_exit_portal(board, avatar_pos, portal[0].kind, channel, match_key)
        if exit_pos is None:
            return []
        obj_at_exit = board.get_entity("objects", exit_pos)
        if obj_at_exit is not None and game.has_tag(obj_at_exit.kind, "solid"):
            return []
        old_pos = avatar_pos
        state.avatar.position = exit_pos
        if end_movement:
            facing = state.avatar.facing
            return [ev.avatar_exited(old_pos), ev.avatar_entered(exit_pos, old_pos, facing)]
        return []

    def _try_teleport_objects(self, state, game, cfg, only_at: set[Pos]):
        board = state.board
        objects_layer = board.layers.get("objects")
        if objects_layer is None:
            return []
        events = []
        for layer_id, layer in board.layers.items():
            if layer_id in ("objects", "actors"):
                continue
            for portal_pos, entity in layer.entries():
                if portal_pos not in only_at:
                    continue
                if not any(game.has_tag(entity.kind, t) for t in cfg["tags"]):
                    continue
                ch = entity.param(cfg["matchKey"])
                if ch is None:
                    continue
                obj = objects_layer.get(portal_pos)
                if obj is None:
                    continue
                exit_pos = self._find_exit_portal(board, portal_pos, entity.kind, ch, cfg["matchKey"])
                if exit_pos is None:
                    continue
                if objects_layer.get(exit_pos) is not None:
                    continue
                board.set_entity("objects", portal_pos, None)
                board.set_entity("objects", exit_pos, obj)
                events.append(ev.object_removed(portal_pos, obj.kind))
                events.append({**ev.object_placed(exit_pos, obj.kind, obj.params), "wasTeleported": True})
        return events

    def _portal_at(self, board, pos: Pos, teleport_tags: list[str], game: GameDef):
        for layer in board.layers.values():
            entity = layer.get(pos)
            if entity and any(game.has_tag(entity.kind, t) for t in teleport_tags):
                return (entity,)
        return None

    def _find_exit_portal(self, board, source_pos: Pos, kind: str, channel, match_key: str) -> Optional[Pos]:
        for layer in board.layers.values():
            for pos, entity in layer.entries():
                if pos == source_pos:
                    continue
                if entity.kind != kind:
                    continue
                ch = entity.param(match_key)
                if ch is not None and str(ch) == str(channel):
                    return pos
        return None


# ---------------------------------------------------------------------------
# ice_slide
# ---------------------------------------------------------------------------

class IceSlideSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "ice_slide")

    def execute_cascade_resolution(self, trigger_events: list[dict], state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        slippery_tag = config.get("slipperyTag", "slippery")

        result = self._handle_avatar_slide(trigger_events, state, game, slippery_tag)
        if result:
            return result
        return self._handle_object_slide(trigger_events, state, game, slippery_tag)

    def _handle_avatar_slide(self, trigger_events, state, game, slippery_tag):
        for event in trigger_events:
            if event["type"] != "avatar_entered":
                continue
            pos = state.avatar.position
            if pos is None:
                continue
            ground = state.board.get_entity("ground", pos)
            if ground is None or not game.has_tag(ground.kind, slippery_tag):
                continue
            dir_str = event.get("direction")
            if not dir_str:
                continue
            dx, dy = dir_delta(dir_str)
            next_pos = Pos(pos.x + dx, pos.y + dy)
            if not state.board.is_in_bounds(next_pos) or state.board.is_void(next_pos):
                continue
            obj_at_next = state.board.get_entity("objects", next_pos)
            if obj_at_next is not None and game.has_tag(obj_at_next.kind, "solid"):
                return self._try_push_during_slide(state, game, pos, next_pos, dir_str, obj_at_next)
            next_ground = state.board.get_entity("ground", next_pos)
            if next_ground is None or not game.has_tag(next_ground.kind, "walkable"):
                continue
            state.avatar.position = next_pos
            state.avatar.facing = dir_str
            return [ev.avatar_exited(pos), ev.avatar_entered(next_pos, pos, dir_str)]
        return []

    def _try_push_during_slide(self, state, game, avatar_pos, obj_pos, dir_str, obj):
        push_sys = game.get_system_by_type("push_objects")
        if push_sys is None:
            return []
        push_cfg = push_sys.get("config", {})
        pushable_tags = push_cfg.get("pushableTags", ["pushable"])
        valid_target_tags = push_cfg.get("validTargetTags", ["walkable"])
        if not any(game.has_tag(obj.kind, t) for t in pushable_tags):
            return []
        dx, dy = dir_delta(dir_str)
        push_dest = Pos(obj_pos.x + dx, obj_pos.y + dy)
        if not state.board.is_in_bounds(push_dest) or state.board.is_void(push_dest):
            return []
        if state.board.get_entity("objects", push_dest) is not None:
            return []
        ground_at_dest = state.board.get_entity("ground", push_dest)
        if ground_at_dest is None or not any(game.has_tag(ground_at_dest.kind, t) for t in valid_target_tags):
            return []
        state.board.set_entity("objects", obj_pos, None)
        state.board.set_entity("objects", push_dest, obj)
        state.avatar.position = obj_pos
        state.avatar.facing = dir_str
        return [
            ev.object_pushed(obj.kind, obj_pos, push_dest, dir_str),
            ev.object_placed(push_dest, obj.kind, obj.params),
            ev.avatar_exited(avatar_pos),
            ev.avatar_entered(obj_pos, avatar_pos, dir_str),
        ]

    def _handle_object_slide(self, trigger_events, state, game, slippery_tag):
        pushed_dirs: dict[Pos, str] = {}
        for event in trigger_events:
            if event["type"] != "object_pushed":
                continue
            to_raw = event.get("toPosition")
            dir_str = event.get("direction")
            if to_raw is None or dir_str is None:
                continue
            to_pos = to_raw if isinstance(to_raw, Pos) else Pos.from_json(to_raw)
            pushed_dirs[to_pos] = dir_str

        for event in trigger_events:
            if event["type"] != "object_placed":
                continue
            pos_raw = event.get("position")
            if pos_raw is None:
                continue
            pos = pos_raw if isinstance(pos_raw, Pos) else Pos.from_json(pos_raw)
            ground = state.board.get_entity("ground", pos)
            if ground is None or not game.has_tag(ground.kind, slippery_tag):
                continue
            dir_str = pushed_dirs.get(pos)
            if dir_str is None:
                continue
            entity = state.board.get_entity("objects", pos)
            if entity is None:
                continue
            dx, dy = dir_delta(dir_str)
            next_pos = Pos(pos.x + dx, pos.y + dy)
            if not state.board.is_in_bounds(next_pos) or state.board.is_void(next_pos):
                continue
            obj_at_next = state.board.get_entity("objects", next_pos)
            if obj_at_next is not None and game.has_tag(obj_at_next.kind, "solid"):
                continue
            next_ground = state.board.get_entity("ground", next_pos)
            if next_ground is None or not game.has_tag(next_ground.kind, "walkable"):
                continue
            state.board.set_entity("objects", pos, None)
            state.board.set_entity("objects", next_pos, entity)
            return [
                ev.cell_cleared(pos, entity.kind),
                ev.object_pushed(entity.kind, pos, next_pos, dir_str),
                ev.object_placed(next_pos, entity.kind, entity.params),
            ]
        return []


# ---------------------------------------------------------------------------
# flood_fill
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# slide_merge
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# overlay_cursor
# ---------------------------------------------------------------------------

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

        size = config.get("size", [2, 2])
        ow = size[0] if size else 2
        oh = size[1] if len(size) > 1 else 2
        constrained = config.get("boundsConstrained", True)
        dx, dy = dir_delta(dir_str)
        nx, ny = overlay.x + dx, overlay.y + dy
        if constrained:
            nx = max(0, min(nx, state.board.width - ow))
            ny = max(0, min(ny, state.board.height - oh))
        state.overlay = OverlayCursor(nx, ny, overlay.width, overlay.height)
        return [ev.overlay_moved([nx, ny])]


# ---------------------------------------------------------------------------
# region_transform
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# queued_emitters
# ---------------------------------------------------------------------------

class QueuedEmittersSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "queued_emitters")

    def execute_npc_resolution(self, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        emitter_kind = config.get("emitterKind", "pipe")
        board = state.board
        events: list[dict] = []

        for mco in board.multi_cell_objects:
            if mco.kind != emitter_kind:
                continue
            exit_raw = mco.params.get("exitPosition")
            if exit_raw is None:
                continue
            exit_pos = Pos.from_json(exit_raw) if not isinstance(exit_raw, Pos) else exit_raw
            exit_dir = mco.params.get("exitDirection")
            spawn_pos = Pos(exit_pos.x + dir_delta(exit_dir)[0], exit_pos.y + dir_delta(exit_dir)[1]) if exit_dir else exit_pos

            queue = mco.params.get("queue", [])

            exit2_raw = mco.params.get("exit2Position")
            if exit2_raw is not None:
                exit2_pos = Pos.from_json(exit2_raw) if not isinstance(exit2_raw, Pos) else exit2_raw
                exit2_dir = mco.params.get("exit2Direction")
                spawn2_pos = Pos(exit2_pos.x + dir_delta(exit2_dir)[0], exit2_pos.y + dir_delta(exit2_dir)[1]) if exit2_dir else exit2_pos
                self._emit_bidirectional(board, mco, events, queue, exit_pos, spawn_pos, exit2_pos, spawn2_pos)
            else:
                idx = mco.params.get("currentIndex", 0)
                if idx >= len(queue):
                    continue
                if board.get_entity("objects", exit_pos) is not None:
                    continue
                if spawn_pos != exit_pos and board.get_entity("objects", spawn_pos) is not None:
                    continue
                val = queue[idx]
                p = {"value": val}
                board.set_entity("objects", spawn_pos, Entity("number", p))
                mco.params["currentIndex"] = idx + 1
                events.append(ev.item_released(mco.id, "number", spawn_pos, p))

        return events

    def _emit_bidirectional(self, board, mco, events, queue, exit1, spawn1, exit2, spawn2):
        pipe_len = len(mco.cells)
        if mco.params.get("pipeSlots") is None:
            slots = [None] * pipe_len
            for i, v in enumerate(queue[:pipe_len]):
                slots[i] = v
            mco.params["pipeSlots"] = slots

        slots = list(mco.params["pipeSlots"])
        last = pipe_len - 1
        if all(v is None for v in slots):
            return

        def clear(exit_p, spawn_p):
            return (board.get_entity("objects", exit_p) is None and
                    (spawn_p == exit_p or board.get_entity("objects", spawn_p) is None))

        can1 = clear(exit1, spawn1)
        can2 = clear(exit2, spawn2)

        if slots[0] is not None and can1:
            val = slots[0]
            p = {"value": val}
            board.set_entity("objects", spawn1, Entity("number", p))
            events.append(ev.item_released(mco.id, "number", spawn1, p))
            slots[0] = None
        if slots[last] is not None and can2:
            val = slots[last]
            p = {"value": val}
            board.set_entity("objects", spawn2, Entity("number", p))
            events.append(ev.item_released(mco.id, "number", spawn2, p))
            slots[last] = None

        new_slots = [None] * pipe_len
        for i, v in enumerate(slots):
            if v is None:
                continue
            d1 = i
            d2 = last - i
            if d1 < d2:
                target = i - 1
            elif d2 < d1:
                target = i + 1
            else:
                if can1 and not can2:
                    target = i - 1
                elif can2 and not can1:
                    target = i + 1
                else:
                    target = i
            target = max(0, min(last, target))
            if new_slots[target] is not None:
                target = i
            new_slots[target] = v

        mco.params["pipeSlots"] = new_slots


# ---------------------------------------------------------------------------
# tile_teleport
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# sided_box
# ---------------------------------------------------------------------------

_SIDE_U, _SIDE_R, _SIDE_D, _SIDE_L = 1, 2, 4, 8

def _side_bit(direction: str) -> int:
    return {"up": _SIDE_U, "right": _SIDE_R, "down": _SIDE_D, "left": _SIDE_L}.get(direction, 0)


class SidedBoxSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "sided_box")

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        if action.get("actionId") != config.get("moveAction", "move"):
            return []
        dir_str = action.get("params", {}).get("direction")
        if not dir_str or not is_cardinal(dir_str):
            return []

        avatar = state.avatar
        if not avatar.enabled or avatar.position is None:
            return []
        pos = avatar.position
        board = state.board
        dx, dy = dir_delta(dir_str)
        target = Pos(pos.x + dx, pos.y + dy)

        if not board.is_in_bounds(target) or board.is_void(target):
            return []

        sided_tag = config.get("sidedTag", "sided")
        sides_param = config.get("sidesParam", "sides")
        valid_ground_tags = config.get("validGroundTags", ["walkable"])
        tool_interactions = config.get("toolInteractions", [])

        objects_layer = board.layers.get("objects")
        ground_layer = board.layers.get("ground")

        def is_sided(e: Optional[Entity]) -> bool:
            return e is not None and game.has_tag(e.kind, sided_tag)

        def sides(e: Entity) -> int:
            return e.param(sides_param) or 0

        def valid_ground(p: Pos) -> bool:
            if ground_layer is None:
                return False
            g = ground_layer.get(p)
            return g is not None and any(game.has_tag(g.kind, t) for t in valid_ground_tags)

        ea = objects_layer.get(pos) if objects_layer else None
        et = objects_layer.get(target) if objects_layer else None

        out_bit = _side_bit(dir_str)
        in_bit = _side_bit(dir_opposite(dir_str))
        perp_mask = (_SIDE_L | _SIDE_R) if dir_str in ("up", "down") else (_SIDE_U | _SIDE_D)

        # CASE 1: Carry
        if is_sided(ea) and (sides(ea) & out_bit) != 0:
            if not board.is_in_bounds(target) or board.is_void(target):
                return []
            if et is not None and not is_sided(et) and game.has_tag(et.kind, "solid"):
                return []
            if is_sided(et):
                if (sides(et) & in_bit) != 0:
                    return []
                if (sides(ea) & sides(et) & perp_mask) != 0:
                    return []
                merged = sides(ea) | sides(et)
                merged_entity = Entity(ea.kind, {**ea.params, sides_param: merged})
                board.set_entity("objects", pos, None)
                board.set_entity("objects", target, merged_entity)
                state.avatar.position = target
                state.avatar.facing = dir_str
                return [ev.boxes_merged(target, merged, sides(ea), sides(et)), ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]
            if et is not None and not is_sided(et):
                return []
            board.set_entity("objects", pos, None)
            board.set_entity("objects", target, ea)
            state.avatar.position = target
            state.avatar.facing = dir_str
            return [ev.object_pushed(ea.kind, pos, target, dir_str), ev.object_placed(target, ea.kind, ea.params), ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]

        # CASE 2: Target has sided box
        if is_sided(et):
            if (sides(et) & in_bit) != 0:
                push_dest = Pos(target.x + dx, target.y + dy)
                if not board.is_in_bounds(push_dest) or board.is_void(push_dest) or not valid_ground(push_dest):
                    return []
                ed = objects_layer.get(push_dest) if objects_layer else None
                if is_sided(ed):
                    if (sides(et) & sides(ed) & perp_mask) != 0:
                        return []
                    merged = sides(et) | sides(ed)
                    me = Entity(et.kind, {**et.params, sides_param: merged})
                    board.set_entity("objects", target, None)
                    board.set_entity("objects", push_dest, me)
                    state.avatar.position = target
                    state.avatar.facing = dir_str
                    return [ev.object_pushed(et.kind, target, push_dest, dir_str), ev.boxes_merged(push_dest, merged, sides(et), sides(ed)), ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]
                if ed is not None:
                    return []
                board.set_entity("objects", target, None)
                board.set_entity("objects", push_dest, et)
                state.avatar.position = target
                state.avatar.facing = dir_str
                return [ev.object_pushed(et.kind, target, push_dest, dir_str), ev.object_placed(push_dest, et.kind, et.params), ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]
            else:
                state.avatar.position = target
                state.avatar.facing = dir_str
                return [ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]

        # CASE 3: Non-sided solid
        if et is not None and game.has_tag(et.kind, "solid"):
            for interaction in tool_interactions:
                req_item = interaction.get("item")
                target_tag = interaction.get("targetTag")
                if req_item is None or target_tag is None:
                    continue
                if state.avatar.item != req_item or not game.has_tag(et.kind, target_tag):
                    continue
                board.set_entity("objects", target, None)
                state.avatar.position = target
                state.avatar.facing = dir_str
                if interaction.get("consumeItem", False):
                    state.avatar.item = None
                anim = interaction.get("animation")
                return [ev.object_removed(target, et.kind, anim), ev.cell_cleared(target, et.kind), ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]
            return []

        # CASE 4: Clear
        state.avatar.position = target
        state.avatar.facing = dir_str
        return [ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]


# ---------------------------------------------------------------------------
# follower_npcs (stub — not used in current packs)
# ---------------------------------------------------------------------------

class FollowerNpcsSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "follower_npcs")


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


# ---------------------------------------------------------------------------
# SystemRegistry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[GameSystem]] = {
    "anchor_point": AnchorPointSystem,
    "avatar_navigation": AvatarNavigationSystem,
    "push_objects": PushObjectsSystem,
    "portals": PortalsSystem,
    "ice_slide": IceSlideSystem,
    "flood_fill": FloodFillSystem,
    "slide_merge": SlideMergeSystem,
    "overlay_cursor": OverlayCursorSystem,
    "region_transform": RegionTransformSystem,
    "queued_emitters": QueuedEmittersSystem,
    "tile_teleport": TileTeleportSystem,
    "sided_box": SidedBoxSystem,
    "follower_npcs": FollowerNpcsSystem,
}


def instantiate_systems(game: GameDef, overrides: Optional[dict] = None) -> list[GameSystem]:
    systems = []
    for sys_def in game.systems:
        if not sys_def.get("enabled", True):
            continue
        cls = _REGISTRY.get(sys_def["type"])
        if cls is not None:
            systems.append(cls(sys_def["id"]))
    return systems
