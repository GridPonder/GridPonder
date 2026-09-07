"""Atomic movement for entities that follow directional route tiles."""
from __future__ import annotations

from dataclasses import dataclass

from .. import _events as ev
from .._game_def import GameDef
from .._models import CARDINALS, Entity, GameState, Pos, dir_opposite
from ._base import GameSystem


@dataclass
class _Mover:
    position: Pos
    entity: Entity


@dataclass
class _Intent:
    mover: _Mover
    target: Pos
    next_heading: str
    delivered: bool


@dataclass
class _Failure:
    mover: _Mover
    target: Pos
    reason: str


class RoutedMotionSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "routed_motion")

    def execute_npc_resolution(
        self, state: GameState, game: GameDef
    ) -> list[dict]:
        config = game.system_config(self.id)
        mover_layer_id = config.get("moverLayer", "objects")
        mover_tag = config.get("moverTag", "routed_mover")
        route_layer_id = config.get("routeLayer", "ground")
        heading_param = config.get("headingParam", "heading")
        color_param = config.get("colorParam", "color")
        exit_layer_id = config.get("exitLayer", "markers")
        exit_tag = config.get("exitTag", "route_exit")
        exit_color_param = config.get("exitColorParam", color_param)
        failure_variable = config.get(
            "failureVariable", "routedMotionFailures"
        )
        routes = config.get("routes") or {}

        mover_layer = state.board.layers.get(mover_layer_id)
        if mover_layer is None:
            return []
        movers = [
            _Mover(position, entity)
            for position, entity in mover_layer.entries()
            if game.has_tag(entity.kind, mover_tag)
        ]
        if not movers:
            return []

        mover_by_position = {mover.position: mover for mover in movers}
        intents: list[_Intent] = []
        failures: list[_Failure] = []

        for mover in movers:
            heading = mover.entity.param(heading_param)
            if heading not in CARDINALS:
                failures.append(
                    _Failure(mover, mover.position, "invalid_heading")
                )
                continue

            source_road = state.board.get_entity(
                route_layer_id, mover.position
            )
            if source_road is None or not self._has_exit(
                routes, source_road.kind, heading
            ):
                failures.append(
                    _Failure(mover, mover.position, "invalid_source_route")
                )
                continue

            target = mover.position.moved(heading)
            if not state.board.is_in_bounds(target):
                failures.append(_Failure(mover, target, "left_board"))
                continue

            target_road = state.board.get_entity(route_layer_id, target)
            next_heading = (
                self._route(routes, target_road.kind, dir_opposite(heading))
                if target_road is not None
                else None
            )
            if next_heading not in CARDINALS:
                failures.append(
                    _Failure(mover, target, "disconnected_road")
                )
                continue

            occupant = mover_layer.get(target)
            if occupant is not None and not game.has_tag(
                occupant.kind, mover_tag
            ):
                failures.append(_Failure(mover, target, "occupied"))
                continue

            exit_entity = state.board.get_entity(exit_layer_id, target)
            is_exit = exit_entity is not None and game.has_tag(
                exit_entity.kind, exit_tag
            )
            if is_exit and mover.entity.param(color_param) != exit_entity.param(
                exit_color_param
            ):
                failures.append(_Failure(mover, target, "wrong_exit"))
                continue

            intents.append(_Intent(mover, target, next_heading, is_exit))

        intents_by_target: dict[Pos, list[_Intent]] = {}
        for intent in intents:
            intents_by_target.setdefault(intent.target, []).append(intent)
        for target, target_intents in intents_by_target.items():
            if len(target_intents) > 1:
                failures.extend(
                    _Failure(intent.mover, target, "same_destination")
                    for intent in target_intents
                )

        intent_by_source = {
            intent.mover.position: intent for intent in intents
        }
        for intent in intents:
            other = intent_by_source.get(intent.target)
            if other is not None and other.target == intent.mover.position:
                failures.append(
                    _Failure(intent.mover, intent.target, "head_on")
                )

        for intent in intents:
            occupant = mover_by_position.get(intent.target)
            if occupant is not None and occupant.position not in intent_by_source:
                failures.append(
                    _Failure(intent.mover, intent.target, "blocked_by_mover")
                )

        if failures:
            old_value = int(state.variables.get(failure_variable, 0))
            new_value = old_value + 1
            state.variables[failure_variable] = new_value
            failure_events = [
                {
                    "type": "routed_motion_failed",
                    "position": failure.target,
                    "kind": failure.mover.entity.kind,
                    "fromPosition": failure.mover.position,
                    "reason": failure.reason,
                }
                for failure in self._dedupe_failures(failures)
            ]
            return failure_events + [
                ev.variable_changed(failure_variable, old_value, new_value)
            ]

        for mover in movers:
            mover_layer.set(mover.position, None)

        events: list[dict] = []
        for intent in intents:
            params = dict(intent.mover.entity.params)
            params[heading_param] = intent.next_heading
            events.append(
                ev.tile_moved(
                    intent.mover.position,
                    intent.target,
                    intent.mover.entity.kind,
                    params=params,
                    layer=mover_layer_id,
                )
            )
            if intent.delivered:
                events.append(
                    ev.object_removed(
                        intent.target, intent.mover.entity.kind
                    )
                )
            else:
                mover_layer.set(
                    intent.target,
                    Entity(intent.mover.entity.kind, params),
                )
        return events

    @staticmethod
    def _route(routes: dict, road_kind: str, incoming_side: str):
        road_routes = routes.get(road_kind)
        if not isinstance(road_routes, dict):
            return None
        value = road_routes.get(incoming_side)
        return value if isinstance(value, str) else None

    @staticmethod
    def _has_exit(routes: dict, road_kind: str, heading: str) -> bool:
        road_routes = routes.get(road_kind)
        return isinstance(road_routes, dict) and heading in road_routes.values()

    @staticmethod
    def _dedupe_failures(failures: list[_Failure]) -> list[_Failure]:
        seen: set[tuple] = set()
        result: list[_Failure] = []
        for failure in failures:
            key = (
                failure.mover.position,
                failure.target,
                failure.reason,
            )
            if key not in seen:
                seen.add(key)
                result.append(failure)
        return result
