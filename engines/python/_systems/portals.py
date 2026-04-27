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
from ._base import GameSystem


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

