"""DirectionalPusherSystem — see docs/dsl/04_systems.md §2.27.

A pusher is a board entity with a baked-in direction. When the avatar
arrives, this turn, on the single cell the pusher points at (the first cell
in its direction, never any other), the avatar is shoved on in that
direction until the next cell is blocked, stopping one cell short of the
blocker.

Runs in ``movement_resolution`` (phase 3), after the avatar's own step, and
fires at most once per turn — the slide never re-triggers another pusher,
since this phase does not re-run on the events the slide itself emits.
"""
from __future__ import annotations

from typing import Optional

from .._models import Entity, Pos, GameState, dir_delta
from .._game_def import GameDef
from .. import _conditions as cond
from .. import _events as ev
from ._base import GameSystem, config_list
from .avatar_navigation import predict_npc_step

# Fixed probe order, so a cell targeted by several pushers resolves the
# same way in both engines.
_PROBE_ORDER = ("up", "down", "left", "right")


class DirectionalPusherSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "directional_pusher")

    def execute_movement_resolution(self, state: GameState, game: GameDef) -> list[dict]:
        avatar = state.avatar
        pos = avatar.position
        start = state.avatar_position_at_turn_start
        if not avatar.enabled or pos is None or start is None or pos == start:
            return []

        config = game.system_config(self.id)
        pusher_layer = str(config.get("pusherLayer", "objects"))
        pusher_tag = str(config.get("pusherTag", "pusher"))
        direction_param = str(config.get("directionParam", "direction"))

        found = self._find_pusher(state, game, pos, pusher_layer, pusher_tag, direction_param)
        if found is None:
            return []
        pusher_pos, dir_str = found

        # The condition sees the step that landed on the trigger cell, so it
        # can use the same grammar (and event fields) as a rule's `if`.
        condition = config.get("condition")
        if condition is not None:
            step_event = ev.avatar_entered(pos, start, dir_str)
            if not cond.evaluate(condition, step_event, state, game):
                return []

        stop_layers = [str(l) for l in config_list(config, "stopLayers", ["objects"])]
        crash_layers = [str(l) for l in config_list(config, "crashLayers", [])]
        crash_variable = str(config.get("crashVariable", "caught"))
        ground_layer = str(config.get("groundLayer", "ground"))
        valid_ground_tags = [str(t) for t in config_list(config, "validGroundTags", ["walkable"])]

        dx, dy = dir_delta(dir_str)
        board = state.board
        hazards = self._hazards(state, game, crash_layers)
        events: list[dict] = []
        crash_event: Optional[dict] = None
        current = pos
        while True:
            nxt = Pos(current.x + dx, current.y + dy)
            if not board.is_in_bounds(nxt) or board.is_void(nxt):
                break
            if valid_ground_tags:
                ground = board.get_entity(ground_layer, nxt)
                if ground is None or not any(game.has_tag(ground.kind, t) for t in valid_ground_tags):
                    break
            if any(board.get_entity(layer, nxt) is not None for layer in stop_layers):
                break
            # One enter/exit pair per cell crossed, like ice_slide, so the
            # renderer can walk the slide cell by cell.
            events.append(ev.avatar_exited(current))
            events.append(ev.avatar_entered(nxt, current, dir_str))
            prev, current = current, nxt

            # Hazards move in the same turn as the slide, so they are met
            # where they will be, not where they were: a hazard leaving this
            # cell lets the slide through; one arriving at, staying on, or
            # crossing head-on through it ends the slide here in a crash.
            hit = None
            for h_pos, entity, h_next in hazards:
                if h_next == nxt:
                    hit = (h_pos, entity, h_next)
                    break
                if h_pos == nxt and h_next == prev:
                    hit = (h_pos, entity, h_next)
                    break
            if hit is not None:
                h_pos, entity, h_next = hit
                # A hazard stepping onto the avatar's final cell is already
                # reported by its own system's contact check; only the cases
                # it can't see (standing still, or crossing through) are
                # recorded here, so a crash is never counted twice.
                if h_next == h_pos or h_next == prev:
                    state.variables[crash_variable] = int(state.variables.get(crash_variable, 0)) + 1
                    crash_event = ev.avatar_caught(nxt, entity.kind, entity.param("id"))
                break

        if current == pos:
            return []

        avatar.position = current
        avatar.facing = dir_str
        events.append({
            "type": "avatar_pushed",
            "position": current,
            "fromPosition": pos,
            "pusherPosition": pusher_pos,
            "direction": dir_str,
            "distance": abs(current.x - pos.x) + abs(current.y - pos.y),
        })
        if crash_event is not None:
            events.append(crash_event)
        return events

    @staticmethod
    def _hazards(state: GameState, game: GameDef, crash_layers: list[str]) -> list[tuple[Pos, Entity, Pos]]:
        """Every crash-layer entity with its position now and where it will
        be after this turn's NPC resolution. An entity whose step can't be
        predicted is assumed to stay put."""
        out = []
        for layer_id in crash_layers:
            layer = state.board.layers.get(layer_id)
            if layer is None:
                continue
            for h_pos, entity in layer.entries():
                h_next = predict_npc_step(entity, h_pos, state, game)
                out.append((h_pos, entity, h_pos if h_next is None else h_next))
        return out

    @staticmethod
    def _find_pusher(
        state: GameState,
        game: GameDef,
        pos: Pos,
        pusher_layer: str,
        pusher_tag: str,
        direction_param: str,
    ) -> Optional[tuple[Pos, str]]:
        """The pusher whose front cell is [pos], if any: a pusher facing
        `d` must sit exactly one cell behind [pos] (at pos - d)."""
        for dir_str in _PROBE_ORDER:
            dx, dy = dir_delta(dir_str)
            behind = Pos(pos.x - dx, pos.y - dy)
            if not state.board.is_in_bounds(behind):
                continue
            entity = state.board.get_entity(pusher_layer, behind)
            if entity is None or not game.has_tag(entity.kind, pusher_tag):
                continue
            if entity.param(direction_param) == dir_str:
                return behind, dir_str
        return None
