"""PortalsSystem — see docs/dsl/04_systems.md."""
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


class PortalsSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "portals")

    def _config(self, game: GameDef) -> dict:
        cfg = game.system_config(self.id)
        tags_raw = config_list(cfg, "teleportTags", ["teleport"])
        return {
            "tags": [str(t) for t in tags_raw],
            "matchKey": cfg.get("matchKey", "channel"),
            "endMovement": cfg.get("endMovement", True),
            "actorLayer": cfg.get("actorLayer"),
            "actorPositionVariable": cfg.get("actorPositionVariable"),
            "trailClearing": cfg.get("trailClearing", []),
            "clearTrailAtPortalCells": cfg.get("clearTrailAtPortalCells", False),
            "exitFoodLayers": cfg.get("exitFoodLayers", []),
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

        # Actor portal check (supports individual_actors system)
        actor_layer_id = cfg.get("actorLayer")
        if actor_layer_id:
            actor_layer = state.board.layers.get(actor_layer_id)
            if actor_layer is not None:
                for e in trigger_events:
                    if e["type"] != "actor_entered":
                        continue
                    entered_raw = e.get("position")
                    ep = (entered_raw if isinstance(entered_raw, Pos)
                          else Pos.from_json(entered_raw)) if entered_raw else None
                    if ep is None:
                        continue
                    from_raw = e.get("fromPosition")
                    from_pos = (from_raw if isinstance(from_raw, Pos)
                                else Pos.from_json(from_raw)) if from_raw else None
                    portal = self._portal_at(state.board, ep, cfg["tags"], game)
                    if portal is None:
                        continue
                    channel = portal[0].param(cfg["matchKey"])
                    if channel is None:
                        continue
                    exit_pos = self._find_exit_portal(
                        state.board, ep, portal[0].kind, channel, cfg["matchKey"])
                    if exit_pos is None:
                        continue
                    if from_pos == exit_pos:
                        continue  # bounce guard
                    actor = actor_layer.get(ep)
                    if actor is None:
                        continue
                    state.board.set_entity(actor_layer_id, ep, None)
                    state.board.set_entity(actor_layer_id, exit_pos, actor)
                    actor_pos_var = cfg.get("actorPositionVariable")
                    if actor_pos_var is not None:
                        state.variables[actor_pos_var] = [exit_pos.x, exit_pos.y]
                    self._clear_actor_trail(state, cfg, actor.kind)
                    self._collect_exit_food(state, game, cfg, exit_pos, actor.kind)

        # Keep portal cells free of trail tiles so they remain permanently usable.
        if cfg.get("clearTrailAtPortalCells") and cfg.get("trailClearing"):
            self._clear_trails_at_portal_positions(state, cfg, game)

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

    def _clear_trails_at_portal_positions(self, state: GameState, cfg: dict, game: GameDef) -> None:
        """Erase trail tiles on portal cells so they stay permanently traversable.

        Budget is not restored — the move that placed the trail is already paid.
        """
        for layer in state.board.layers.values():
            for pos, entity in layer.entries():
                if not any(game.has_tag(entity.kind, t) for t in cfg["tags"]):
                    continue
                for tc in cfg.get("trailClearing", []):
                    trail_layer_id = tc.get("trailLayer")
                    trail_kind = tc.get("trailKind")
                    restore_kind = tc.get("restoreKind")
                    trail_layer = state.board.layers.get(trail_layer_id)
                    if trail_layer is None:
                        continue
                    trail_cell = trail_layer.get(pos)
                    if trail_cell is not None and trail_cell.kind == trail_kind:
                        new_ent = Entity(restore_kind) if restore_kind else None
                        state.board.set_entity(trail_layer_id, pos, new_ent)

    def _clear_actor_trail(self, state, cfg: dict, actor_kind: str) -> None:
        """Clear all trail tiles for the teleporting actor and restore its budget."""
        for tc in cfg.get("trailClearing", []):
            if tc.get("actorKind") != actor_kind:
                continue
            trail_layer_id = tc.get("trailLayer")
            trail_kind = tc.get("trailKind")
            restore_kind = tc.get("restoreKind")
            budget_var = tc.get("budgetVariable")
            layer = state.board.layers.get(trail_layer_id)
            if layer is None:
                break
            to_restore = [
                pos for pos, ent in layer.entries()
                if ent.kind == trail_kind
            ]
            for pos in to_restore:
                new_ent = Entity(restore_kind) if restore_kind else None
                state.board.set_entity(trail_layer_id, pos, new_ent)
            if to_restore and budget_var is not None:
                current = state.variables.get(budget_var, 0)
                state.variables[budget_var] = (current if isinstance(current, int) else 0) + len(to_restore)
            break

    def _collect_exit_food(self, state, game, cfg: dict, exit_pos: Pos, actor_kind: str) -> None:
        """Award food sitting on the portal's exit cell.

        Teleporting relocates the actor without emitting a fresh
        actor_entered event for the exit cell, so eat_food_* rules never see
        the landing and the actor silently overlaps the food without
        collecting it — same class of bug as the water terrain_skip system,
        fixed the same way here.
        """
        for food_check in cfg.get("exitFoodLayers", []):
            layer_id = food_check.get("layer")
            food_tag = food_check.get("foodTag", "food")
            amount_prefix = food_check.get("amountTagPrefix", "food_v")
            budget_prefix = food_check.get("budgetVariablePrefix", "moveBudget_")
            if not layer_id:
                continue
            exit_entity = state.board.get_entity(layer_id, exit_pos)
            if exit_entity is None:
                continue
            kind_def = game.entity_kinds.get(exit_entity.kind, {})
            entity_tags = kind_def.get("tags", []) if isinstance(kind_def, dict) else getattr(kind_def, "tags", [])
            if food_tag not in entity_tags:
                continue
            amount = None
            for t in entity_tags:
                if t.startswith(amount_prefix) and t[len(amount_prefix):].isdigit():
                    amount = int(t[len(amount_prefix):])
                    break
            if amount is None:
                continue
            color = actor_kind.rsplit("_", 1)[-1]
            budget_var = f"{budget_prefix}{color}"
            current = state.variables.get(budget_var, 0)
            state.variables[budget_var] = (current if isinstance(current, int) else 0) + amount
            state.board.set_entity(layer_id, exit_pos, None)
            break

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