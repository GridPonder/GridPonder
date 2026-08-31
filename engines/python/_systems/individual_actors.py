"""IndividualActorsSystem.

Selects one actor with a tap action, then moves only that selected actor with
the configured move action. Optionally claims territory and enforces per-actor
successful-move budgets.
"""
from __future__ import annotations

from .._game_def import GameDef
from .._models import (
    CARDINALS, Entity, GameState, Pos, dir_delta, transform_delta)
from .. import _events as ev
from ._base import GameSystem
from ._claim import apply_claim

# up, down, left, right — the canonical bucket order shared with coupled_actors.
_CANONICAL_BUCKETS = ((0, -1), (0, 1), (-1, 0), (1, 0))
_DELTA_DIRS = {(0, -1): "up", (0, 1): "down", (-1, 0): "left", (1, 0): "right"}


def _delta_dir(dx: int, dy: int) -> str:
    return _DELTA_DIRS.get((dx, dy), "")


class IndividualActorsSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "individual_actors")

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        select_action = config.get("selectAction", "tap_cell")
        move_action = config.get("moveAction", "move")
        interact_action = config.get("interactAction")

        if action.get("actionId") == select_action:
            return self._select(action, state, game, config)
        if action.get("actionId") == move_action:
            return self._move(action, state, game, config)
        if interact_action and action.get("actionId") == interact_action:
            return self._interact(action, state, game, config)
        return []

    def _select(self, action: dict, state: GameState, game: GameDef, config: dict) -> list[dict]:
        pos_raw = action.get("params", {}).get("position")
        if pos_raw is None:
            return [ev.action_vetoed()]

        pos = Pos.from_json(pos_raw)
        actor_layer_id = config.get("actorLayer", "actors")
        entity = state.board.get_entity(actor_layer_id, pos)
        if entity is None or not game.has_tag(entity.kind, config.get("actorTag", "actor")):
            return [ev.action_vetoed()]

        selected_key = config.get("selectedVariable", "selectedActorKind")
        selected_position_key = config.get(
            "selectedPositionVariable", "selectedActorPosition")
        state.variables[selected_key] = entity.kind
        state.variables[selected_position_key] = [pos.x, pos.y]
        self._ensure_budget_state(state, config)
        return [ev.actor_selected(entity.kind, pos)]

    def _move(self, action: dict, state: GameState, game: GameDef, config: dict) -> list[dict]:
        allowed = config.get("directions", list(CARDINALS))
        direction = action.get("params", {}).get("direction")
        if not direction or direction not in allowed:
            return []

        selected_key = config.get("selectedVariable", "selectedActorKind")
        selected_position_key = config.get(
            "selectedPositionVariable", "selectedActorPosition")
        selected_kind = state.variables.get(selected_key)
        if not selected_kind:
            return [ev.action_vetoed()]

        remaining = self._ensure_budget_state(state, config)
        if remaining is not None and int(remaining.get(selected_kind, 0)) <= 0:
            return [ev.action_vetoed()]

        dx, dy = dir_delta(direction)
        if (dx, dy) == (0, 0):
            return []

        actor_layer_id = config.get("actorLayer", "actors")
        ground_layer_id = config.get("groundLayer", "ground")
        wall_tag = config.get("wallTag", "solid")
        board = state.board
        actor_layer = board.layers.get(actor_layer_id)
        if actor_layer is None:
            return [ev.action_vetoed()]

        selected_position = _parse_position(
            state.variables.get(selected_position_key))
        pos = None
        entity = None
        occupied = set()
        for actor_pos, actor_entity in actor_layer.entries():
            occupied.add(actor_pos)
            if (selected_position is not None
                    and actor_pos == selected_position
                    and actor_entity.kind == selected_kind):
                pos = actor_pos
                entity = actor_entity

        # Backward compatibility for states created before position-based
        # selection: a kind is sufficient only when it identifies one actor.
        if selected_position is None:
            matches = [
                (actor_pos, actor_entity)
                for actor_pos, actor_entity in actor_layer.entries()
                if actor_entity.kind == selected_kind
            ]
            if len(matches) == 1:
                pos, entity = matches[0]

        if pos is None or entity is None:
            return [ev.action_vetoed()]

        target = Pos(pos.x + dx, pos.y + dy)
        blocked = (
            not board.is_in_bounds(target)
            or board.has_tag_at(ground_layer_id, target, wall_tag, game.entity_kinds)
            or target in occupied
        )
        if not blocked:
            extra_by_kind = config.get("extraBlockLayersByKind", {})
            for layer_cfg in extra_by_kind.get(selected_kind, []):
                layer_id = layer_cfg.get("layer")
                exclude_tags = layer_cfg.get("excludeTags", [])
                extra_layer = board.layers.get(layer_id)
                if extra_layer:
                    entity_at = extra_layer.get(target)
                    if entity_at:
                        kind_def = game.entity_kinds.get(entity_at.kind, {})
                        entity_tags = kind_def.get("tags", [])
                        if not any(t in entity_tags for t in exclude_tags):
                            blocked = True
                            break
        if blocked:
            return [ev.actor_blocked(entity.kind, pos)]

        board.set_entity(actor_layer_id, pos, None)
        board.set_entity(actor_layer_id, target, entity)
        state.variables[selected_position_key] = [target.x, target.y]
        events = [
            ev.actor_moved(entity.kind, pos, target, direction),
            ev.actor_entered(entity.kind, target, pos, direction),
        ]

        claim_event = apply_claim(
            board, game, config.get("claim"), ground_layer_id, target, entity.kind)
        if claim_event is not None:
            events.append(claim_event)

        if remaining is not None:
            remaining[entity.kind] = int(remaining.get(entity.kind, 0)) - 1

        events += self._react(
            state, game, config, (dx, dy), actor_layer_id, ground_layer_id, wall_tag)

        return events

    def _interact(self, action: dict, state: GameState, game: GameDef, config: dict) -> list[dict]:
        selected_key = config.get("selectedVariable", "selectedActorKind")
        selected_position_key = config.get("selectedPositionVariable", "selectedActorPosition")
        selected_kind = state.variables.get(selected_key)
        if not selected_kind:
            return [ev.action_vetoed()]

        selected_position = _parse_position(state.variables.get(selected_position_key))
        if selected_position is None:
            return [ev.action_vetoed()]

        actor_layer_id = config.get("actorLayer", "actors")
        actor_layer = state.board.layers.get(actor_layer_id)
        entity = actor_layer.get(selected_position) if actor_layer else None
        if entity is None or entity.kind != selected_kind:
            return [ev.action_vetoed()]

        return [ev.actor_interacted(selected_kind, selected_position)]

    def _react(self, state: GameState, game: GameDef, config: dict,
               delta: tuple[int, int], actor_layer_id: str,
               ground_layer_id: str, wall_tag: str) -> list[dict]:
        """Move every reactive-kind actor in response to a successful player move.

        Rivals answer the *player's* direction through their own transform, so
        the move the player makes is also the move the opposition makes. Runs
        only after a real step — a blocked attempt gives the rivals nothing.
        Resolution mirrors ``coupled_actors``: bucket by effective direction in
        canonical order, front-first within a bucket, with a live ``occupied``
        set, so the outcome is fully deterministic.

        Emits ``actor_reacted`` rather than ``actor_moved`` so that move
        counters and budgets keyed on player movement stay honest; a level that
        wants rival landings to anchor captures names ``actor_reacted`` in the
        capture system's ``triggerEvents``.
        """
        reactive = config.get("reactiveKinds") or {}
        if not reactive:
            return []

        board = state.board
        actor_layer = board.layers.get(actor_layer_id)
        if actor_layer is None:
            return []

        occupied = {pos for pos, _ in actor_layer.entries()}
        triples = [
            (pos, entity, transform_delta(delta, reactive.get(entity.kind)))
            for pos, entity in actor_layer.entries()
            if entity.kind in reactive
        ]

        ordered: list[tuple[Pos, Entity, tuple[int, int]]] = []
        for bucket in _CANONICAL_BUCKETS:
            bdx, bdy = bucket
            members = [t for t in triples if t[2] == bucket]
            members.sort(key=lambda t: (
                -(t[0].x * bdx + t[0].y * bdy),
                t[0].x * abs(bdy) + t[0].y * abs(bdx),
                t[1].kind,
            ))
            ordered.extend(members)

        events: list[dict] = []
        for pos, entity, (rdx, rdy) in ordered:
            if (rdx, rdy) == (0, 0):
                continue
            target = Pos(pos.x + rdx, pos.y + rdy)
            blocked = (
                not board.is_in_bounds(target)
                or board.has_tag_at(ground_layer_id, target, wall_tag, game.entity_kinds)
                or target in occupied
            )
            if blocked:
                continue
            board.set_entity(actor_layer_id, pos, None)
            board.set_entity(actor_layer_id, target, entity)
            occupied.discard(pos)
            occupied.add(target)
            events.append(ev.actor_reacted(
                entity.kind, pos, target, _delta_dir(rdx, rdy)))
        return events

    def _ensure_budget_state(self, state: GameState, config: dict) -> dict | None:
        budgets = config.get("budgets")
        if not budgets:
            return None

        key = config.get("budgetVariable", "actorMovesRemaining")
        current = state.variables.get(key)
        if not isinstance(current, dict):
            current = {kind: int(value) for kind, value in budgets.items()}
            state.variables[key] = current
        return current


def _parse_position(raw) -> Pos | None:
    if isinstance(raw, Pos):
        return raw
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return Pos(int(raw[0]), int(raw[1]))
    return None
