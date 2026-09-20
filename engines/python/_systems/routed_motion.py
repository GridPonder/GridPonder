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
    removed_at_end: bool


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
    removed_at_end: bool = False


@dataclass
class _FlowIntent:
    flow: _FlowMover
    target: Pos
    next_heading: str
    removed_at_end: bool


@dataclass
class _StepPlan:
    target: Pos
    next_heading: str | None = None
    removed_at_end: bool = False
    failure_reason: str | None = None


@dataclass(frozen=True)
class _RouteConfig:
    mover_layer_id: str
    mover_tag: str
    route_layer_id: str
    heading_param: str
    match_param: str | None
    exit_layer_id: str
    exit_tag: str
    exit_match_param: str | None
    exit_requires_route: bool
    gate_layer_id: str | None
    gate_closed_tag: str
    gate_entry_side_param: str
    route_selector_layer_id: str | None
    failure_variable: str
    routes: dict
    movement_mode: str
    blocked_behavior: str
    allow_u_turns: bool
    max_travel_steps: int | None

    @classmethod
    def from_dict(cls, data: dict) -> "_RouteConfig":
        def string_or(value: object, fallback: str) -> str:
            return value if isinstance(value, str) else fallback

        def optional_string(value: object) -> str | None:
            return value if isinstance(value, str) else None

        def bool_or(value: object, fallback: bool) -> bool:
            return value if isinstance(value, bool) else fallback

        match_param = data.get("matchParam")
        match_param = optional_string(match_param)
        exit_match_param = optional_string(data.get("exitMatchParam"))
        if match_param is not None and exit_match_param is None:
            exit_match_param = match_param
        if match_param is None:
            exit_match_param = None
        routes = data.get("routes")
        if not isinstance(routes, dict):
            routes = {}
        max_travel_steps = data.get("maxTravelSteps")
        if not isinstance(max_travel_steps, int) or isinstance(
            max_travel_steps, bool
        ):
            max_travel_steps = None
        return cls(
            mover_layer_id=string_or(data.get("moverLayer"), "objects"),
            mover_tag=string_or(data.get("moverTag"), "routed_mover"),
            route_layer_id=string_or(data.get("routeLayer"), "ground"),
            heading_param=string_or(data.get("headingParam"), "heading"),
            match_param=match_param,
            exit_layer_id=string_or(data.get("exitLayer"), "markers"),
            exit_tag=string_or(data.get("exitTag"), "route_exit"),
            exit_match_param=exit_match_param,
            exit_requires_route=bool_or(
                data.get("exitRequiresRoute"), True
            ),
            gate_layer_id=optional_string(data.get("gateLayer")),
            gate_closed_tag=string_or(
                data.get("gateClosedTag"), "route_closed"
            ),
            gate_entry_side_param=string_or(
                data.get("gateEntrySideParam"), "entrySide"
            ),
            route_selector_layer_id=optional_string(
                data.get("routeSelectorLayer")
            ),
            failure_variable=string_or(
                data.get("failureVariable"), "routedMotionFailures"
            ),
            routes=routes,
            movement_mode=string_or(
                data.get("movementMode"), "single_step"
            ),
            blocked_behavior=string_or(
                data.get("blockedBehavior"), "fail"
            ),
            allow_u_turns=bool_or(data.get("allowUTurns"), True),
            max_travel_steps=max_travel_steps,
        )


class RoutedMotionSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "routed_motion")

    def execute_npc_resolution(
        self, state: GameState, game: GameDef
    ) -> list[dict]:
        config = _RouteConfig.from_dict(game.system_config(self.id))

        mover_layer = state.board.layers.get(config.mover_layer_id)
        if mover_layer is None:
            return []
        movers = [
            _Mover(position, entity)
            for position, entity in mover_layer.entries()
            if game.has_tag(entity.kind, config.mover_tag)
        ]
        if not movers:
            return []

        if config.movement_mode == "until_blocked":
            return self._execute_until_blocked(
                state,
                game,
                movers,
                config,
            )

        mover_by_position = {mover.position: mover for mover in movers}
        intents: list[_Intent] = []
        failures: list[_Failure] = []

        for mover in movers:
            step = self._plan_step(state, game, mover, config)
            if step.failure_reason is not None:
                failures.append(_Failure(mover, step.target, step.failure_reason))
                continue
            intents.append(
                _Intent(
                    mover,
                    step.target,
                    step.next_heading,
                    step.removed_at_end,
                )
            )

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
            old_value = self._failure_count(state, config.failure_variable)
            new_value = old_value + 1
            state.variables[config.failure_variable] = new_value
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
                ev.variable_changed(config.failure_variable, old_value, new_value)
            ]

        for mover in movers:
            mover_layer.set(mover.position, None)

        events: list[dict] = []
        for intent in intents:
            params = dict(intent.mover.entity.params)
            params[config.heading_param] = intent.next_heading
            events.append(
                ev.tile_moved(
                    intent.mover.position,
                    intent.target,
                    intent.mover.entity.kind,
                    params=params,
                    layer=config.mover_layer_id,
                )
            )
            if intent.removed_at_end:
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
        config: _RouteConfig,
    ) -> list[dict]:
        mover_layer = state.board.layers[config.mover_layer_id]
        flows = [
            _FlowMover(i, mover.position, mover.entity, [mover.position])
            for i, mover in enumerate(movers)
        ]
        blocked_events: list[dict] = []
        seen_states: set[tuple] = set()
        default_limit = state.board.width * state.board.height * 4 * len(flows)
        travel_limit = (
            config.max_travel_steps
            if isinstance(config.max_travel_steps, int)
            and not isinstance(config.max_travel_steps, bool)
            and config.max_travel_steps > 0
            else max(1, default_limit)
        )
        rounds = 0

        while any(flow.active for flow in flows):
            signature = tuple(
                (
                    flow.index,
                    flow.position,
                    flow.entity.param(config.heading_param),
                    flow.active,
                )
                for flow in flows
                if not flow.removed_at_end
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
                flow.position: flow
                for flow in flows
                if not flow.removed_at_end
            }
            intents: dict[_FlowMover, _FlowIntent] = {}
            blocked: dict[_FlowMover, _Failure] = {}

            for flow in flows:
                if not flow.active:
                    continue
                mover = _Mover(flow.position, flow.entity)
                step = self._plan_step(state, game, mover, config)
                if step.failure_reason is not None:
                    blocked[flow] = _Failure(
                        mover, step.target, step.failure_reason
                    )
                    continue
                intents[flow] = _FlowIntent(
                    flow,
                    step.target,
                    step.next_heading,
                    step.removed_at_end,
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

            if config.blocked_behavior == "fail" and blocked:
                # `fail` is transactional for the whole continuous tick.
                # Restore movers that travelled in earlier microsteps, even
                # when one of them already reached and left through an exit.
                for flow in flows:
                    mover_layer.set(flow.position, None)
                for mover in movers:
                    mover_layer.set(mover.position, mover.entity)

                old_value = self._failure_count(
                    state, config.failure_variable
                )
                new_value = old_value + 1
                state.variables[config.failure_variable] = new_value
                events = [
                    {
                        "type": "routed_motion_failed",
                        "position": failure.target,
                        "kind": movers[flow.index].entity.kind,
                        "fromPosition": movers[flow.index].position,
                        "reason": failure.reason,
                    }
                    for flow, failure in blocked.items()
                ]
                events.append(
                    ev.variable_changed(
                        config.failure_variable, old_value, new_value
                    )
                )
                return events

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
                params[config.heading_param] = intent.next_heading
                flow.position = intent.target
                flow.entity = Entity(flow.entity.kind, params)
                flow.path.append(intent.target)
                if intent.removed_at_end:
                    flow.removed_at_end = True
                    flow.active = False
                else:
                    mover_layer.set(flow.position, flow.entity)

        events = [
            ev.entity_path_moved(
                flow.path,
                flow.entity.kind,
                params=flow.entity.params,
                layer=config.mover_layer_id,
                removed_at_end=flow.removed_at_end,
            )
            for flow in flows
            if len(flow.path) > 1
        ]
        events.extend(
            ev.object_removed(flow.position, flow.entity.kind)
            for flow in flows
            if flow.removed_at_end
        )
        events.extend(blocked_events)

        return events

    def _plan_step(
        self,
        state: GameState,
        game: GameDef,
        mover: _Mover,
        config: _RouteConfig,
    ) -> _StepPlan:
        heading = mover.entity.param(config.heading_param)
        if heading not in CARDINALS:
            return _StepPlan(mover.position, failure_reason="invalid_heading")

        source_route = state.board.get_entity(
            config.route_layer_id, mover.position
        )
        if source_route is None or not self._has_exit(
            config.routes, source_route.kind, heading
        ):
            return _StepPlan(
                mover.position, failure_reason="invalid_source_route"
            )

        target = mover.position.moved(heading)
        if not state.board.is_in_bounds(target):
            return _StepPlan(target, failure_reason="left_board")

        exit_entity = state.board.get_entity(config.exit_layer_id, target)
        is_exit = exit_entity is not None and game.has_tag(
            exit_entity.kind, config.exit_tag
        )
        if is_exit and not self._exit_matches(
            mover.entity, exit_entity, config
        ):
            return _StepPlan(target, failure_reason="wrong_exit")

        bypass_target_route = is_exit and not config.exit_requires_route
        target_route = state.board.get_entity(config.route_layer_id, target)
        next_heading = (
            self._route(
                state,
                config.routes,
                target_route.kind,
                dir_opposite(heading),
                target,
                config.route_selector_layer_id,
            )
            if target_route is not None
            else None
        )
        if bypass_target_route:
            next_heading = heading
        if not bypass_target_route and next_heading not in CARDINALS:
            return _StepPlan(target, failure_reason="disconnected_route")

        if self._gate_is_closed(
            state,
            game,
            target,
            dir_opposite(heading),
            config,
        ):
            return _StepPlan(target, failure_reason="closed_gate")
        if not config.allow_u_turns and next_heading == dir_opposite(heading):
            return _StepPlan(target, failure_reason="u_turn")

        occupant = state.board.get_entity(config.mover_layer_id, target)
        if occupant is not None and not game.has_tag(
            occupant.kind, config.mover_tag
        ):
            return _StepPlan(target, failure_reason="occupied")

        return _StepPlan(
            target,
            next_heading=next_heading,
            removed_at_end=is_exit,
        )

    @staticmethod
    def _exit_matches(
        mover: Entity,
        exit_entity: Entity,
        config: _RouteConfig,
    ) -> bool:
        if config.match_param is None:
            return True
        return mover.param(config.match_param) == exit_entity.param(
            config.exit_match_param
        )

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
    def _route(
        state: GameState,
        routes: dict,
        route_kind: str,
        incoming_side: str,
        position: Pos,
        selector_layer_id,
    ):
        route_options = routes.get(route_kind)
        if not isinstance(route_options, dict):
            return None
        value = route_options.get(incoming_side)
        if isinstance(value, str):
            return value
        if not isinstance(value, dict) or not selector_layer_id:
            return None
        selector = state.board.get_entity(selector_layer_id, position)
        if selector is None:
            return None
        selected = value.get(selector.kind)
        return selected if isinstance(selected, str) else None

    @staticmethod
    def _has_exit(routes: dict, route_kind: str, heading: str) -> bool:
        route_options = routes.get(route_kind)
        if not isinstance(route_options, dict):
            return False
        return any(
            value == heading
            or (isinstance(value, dict) and heading in value.values())
            for value in route_options.values()
        )

    @staticmethod
    def _gate_is_closed(
        state: GameState,
        game: GameDef,
        target: Pos,
        incoming_side: str,
        config: _RouteConfig,
    ) -> bool:
        gate_layer_id = config.gate_layer_id
        if not isinstance(gate_layer_id, str) or not gate_layer_id:
            return False
        gate = state.board.get_entity(gate_layer_id, target)
        if gate is None or not game.has_tag(gate.kind, config.gate_closed_tag):
            return False
        controlled_side = gate.param(config.gate_entry_side_param)
        return controlled_side in (None, "any", incoming_side)

    @staticmethod
    def _failure_count(state: GameState, variable: str) -> int:
        value = state.variables.get(variable, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0
        return int(value)

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
