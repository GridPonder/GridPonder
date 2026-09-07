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


@dataclass(eq=False)
class _FlowMover:
    index: int
    position: Pos
    entity: Entity
    path: list[Pos]
    active: bool = True
    delivered: bool = False


@dataclass
class _FlowIntent:
    flow: _FlowMover
    target: Pos
    next_heading: str
    delivered: bool


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
        movement_mode = config.get("movementMode", "single_step")

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

        if movement_mode == "until_blocked":
            return self._execute_until_blocked(
                state,
                game,
                movers,
                mover_layer_id=mover_layer_id,
                mover_tag=mover_tag,
                route_layer_id=route_layer_id,
                heading_param=heading_param,
                color_param=color_param,
                exit_layer_id=exit_layer_id,
                exit_tag=exit_tag,
                exit_color_param=exit_color_param,
                failure_variable=failure_variable,
                routes=routes,
                blocked_behavior=config.get("blockedBehavior", "fail"),
                allow_u_turns=bool(config.get("allowUTurns", True)),
                max_travel_steps=config.get("maxTravelSteps"),
            )

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

    def _execute_until_blocked(
        self,
        state: GameState,
        game: GameDef,
        movers: list[_Mover],
        *,
        mover_layer_id: str,
        mover_tag: str,
        route_layer_id: str,
        heading_param: str,
        color_param: str,
        exit_layer_id: str,
        exit_tag: str,
        exit_color_param: str,
        failure_variable: str,
        routes: dict,
        blocked_behavior: str,
        allow_u_turns: bool,
        max_travel_steps,
    ) -> list[dict]:
        mover_layer = state.board.layers[mover_layer_id]
        flows = [
            _FlowMover(i, mover.position, mover.entity, [mover.position])
            for i, mover in enumerate(movers)
        ]
        blocked_events: list[dict] = []
        failures: list[_Failure] = []
        seen_states: set[tuple] = set()
        default_limit = state.board.width * state.board.height * 4 * len(flows)
        travel_limit = (
            max_travel_steps
            if isinstance(max_travel_steps, int) and max_travel_steps > 0
            else max(1, default_limit)
        )
        rounds = 0

        while any(flow.active for flow in flows):
            signature = tuple(
                (
                    flow.index,
                    flow.position,
                    flow.entity.param(heading_param),
                    flow.active,
                )
                for flow in flows
                if not flow.delivered
            )
            if signature in seen_states:
                for flow in flows:
                    if flow.active:
                        flow.active = False
                        blocked_events.append(
                            self._blocked_event(
                                flow, flow.position, "route_cycle"
                            )
                        )
                break
            seen_states.add(signature)

            if rounds >= travel_limit:
                for flow in flows:
                    if flow.active:
                        flow.active = False
                        blocked_events.append(
                            self._blocked_event(
                                flow, flow.position, "travel_limit"
                            )
                        )
                break
            rounds += 1

            flow_by_position = {
                flow.position: flow for flow in flows if not flow.delivered
            }
            intents: dict[_FlowMover, _FlowIntent] = {}
            blocked: dict[_FlowMover, _Failure] = {}

            for flow in flows:
                if not flow.active:
                    continue
                heading = flow.entity.param(heading_param)
                mover = _Mover(flow.position, flow.entity)
                if heading not in CARDINALS:
                    blocked[flow] = _Failure(
                        mover, flow.position, "invalid_heading"
                    )
                    continue

                source_road = state.board.get_entity(
                    route_layer_id, flow.position
                )
                if source_road is None or not self._has_exit(
                    routes, source_road.kind, heading
                ):
                    blocked[flow] = _Failure(
                        mover, flow.position, "invalid_source_route"
                    )
                    continue

                target = flow.position.moved(heading)
                if not state.board.is_in_bounds(target):
                    blocked[flow] = _Failure(mover, target, "left_board")
                    continue

                target_road = state.board.get_entity(route_layer_id, target)
                next_heading = (
                    self._route(
                        routes, target_road.kind, dir_opposite(heading)
                    )
                    if target_road is not None
                    else None
                )
                if next_heading not in CARDINALS:
                    blocked[flow] = _Failure(
                        mover, target, "disconnected_road"
                    )
                    continue
                if not allow_u_turns and next_heading == dir_opposite(heading):
                    blocked[flow] = _Failure(mover, target, "u_turn")
                    continue

                occupant = mover_layer.get(target)
                if occupant is not None and not game.has_tag(
                    occupant.kind, mover_tag
                ):
                    blocked[flow] = _Failure(mover, target, "occupied")
                    continue

                exit_entity = state.board.get_entity(exit_layer_id, target)
                is_exit = exit_entity is not None and game.has_tag(
                    exit_entity.kind, exit_tag
                )
                if is_exit and flow.entity.param(
                    color_param
                ) != exit_entity.param(exit_color_param):
                    blocked[flow] = _Failure(mover, target, "wrong_exit")
                    continue

                intents[flow] = _FlowIntent(
                    flow, target, next_heading, is_exit
                )

            by_target: dict[Pos, list[_FlowIntent]] = {}
            for intent in intents.values():
                by_target.setdefault(intent.target, []).append(intent)
            for target, target_intents in by_target.items():
                if len(target_intents) < 2:
                    continue
                for intent in target_intents:
                    blocked[intent.flow] = _Failure(
                        _Mover(intent.flow.position, intent.flow.entity),
                        target,
                        "same_destination",
                    )

            for intent in intents.values():
                other = flow_by_position.get(intent.target)
                other_intent = intents.get(other) if other is not None else None
                if (
                    other_intent is not None
                    and other_intent.target == intent.flow.position
                ):
                    blocked[intent.flow] = _Failure(
                        _Mover(intent.flow.position, intent.flow.entity),
                        intent.target,
                        "head_on",
                    )

            propagated = True
            while propagated:
                propagated = False
                for intent in intents.values():
                    if intent.flow in blocked:
                        continue
                    occupant = flow_by_position.get(intent.target)
                    if occupant is None:
                        continue
                    if occupant not in intents or occupant in blocked:
                        blocked[intent.flow] = _Failure(
                            _Mover(
                                intent.flow.position, intent.flow.entity
                            ),
                            intent.target,
                            "blocked_by_mover",
                        )
                        propagated = True

            if blocked_behavior == "fail" and blocked:
                failures.extend(blocked.values())
                for flow in flows:
                    if flow.active:
                        flow.active = False
                break

            for flow, failure in blocked.items():
                flow.active = False
                blocked_events.append(
                    self._blocked_event(flow, failure.target, failure.reason)
                )

            moving = [
                intent
                for intent in intents.values()
                if intent.flow not in blocked
            ]
            if not moving:
                break

            for intent in moving:
                mover_layer.set(intent.flow.position, None)
            for intent in moving:
                flow = intent.flow
                params = dict(flow.entity.params)
                params[heading_param] = intent.next_heading
                flow.position = intent.target
                flow.entity = Entity(flow.entity.kind, params)
                flow.path.append(intent.target)
                if intent.delivered:
                    flow.delivered = True
                    flow.active = False
                else:
                    mover_layer.set(flow.position, flow.entity)

        events = [
            ev.entity_path_moved(
                flow.path,
                flow.entity.kind,
                params=flow.entity.params,
                layer=mover_layer_id,
                delivered=flow.delivered,
            )
            for flow in flows
            if len(flow.path) > 1
        ]
        events.extend(
            ev.object_removed(flow.position, flow.entity.kind)
            for flow in flows
            if flow.delivered
        )
        events.extend(blocked_events)

        if failures:
            old_value = int(state.variables.get(failure_variable, 0))
            new_value = old_value + 1
            state.variables[failure_variable] = new_value
            events.extend(
                {
                    "type": "routed_motion_failed",
                    "position": failure.target,
                    "kind": failure.mover.entity.kind,
                    "fromPosition": failure.mover.position,
                    "reason": failure.reason,
                }
                for failure in self._dedupe_failures(failures)
            )
            events.append(
                ev.variable_changed(failure_variable, old_value, new_value)
            )
        return events

    @staticmethod
    def _blocked_event(flow: _FlowMover, target: Pos, reason: str) -> dict:
        return {
            "type": "routed_motion_blocked",
            "position": target,
            "kind": flow.entity.kind,
            "fromPosition": flow.position,
            "reason": reason,
        }

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
