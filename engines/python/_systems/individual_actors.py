"""IndividualActorsSystem.

Selects one actor with a tap action, then moves only that selected actor with
the configured move action. Optionally claims territory and enforces per-actor
successful-move budgets.
"""
from __future__ import annotations

from .._game_def import GameDef
from .._models import CARDINALS, Entity, GameState, Pos, dir_delta
from .. import _events as ev
from ._base import GameSystem
from ._claim import apply_claim


class IndividualActorsSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "individual_actors")

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        select_action = config.get("selectAction", "tap_cell")
        move_action = config.get("moveAction", "move")

        if action.get("actionId") == select_action:
            return self._select(action, state, game, config)
        if action.get("actionId") == move_action:
            return self._move(action, state, game, config)
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
        state.variables[selected_key] = entity.kind
        self._ensure_budget_state(state, config)
        return [ev.actor_selected(entity.kind, pos)]

    def _move(self, action: dict, state: GameState, game: GameDef, config: dict) -> list[dict]:
        allowed = config.get("directions", list(CARDINALS))
        direction = action.get("params", {}).get("direction")
        if not direction or direction not in allowed:
            return []

        selected_key = config.get("selectedVariable", "selectedActorKind")
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

        pos = None
        entity = None
        occupied = set()
        for actor_pos, actor_entity in actor_layer.entries():
            occupied.add(actor_pos)
            if actor_entity.kind == selected_kind:
                pos = actor_pos
                entity = actor_entity

        if pos is None or entity is None:
            return [ev.action_vetoed()]

        target = Pos(pos.x + dx, pos.y + dy)
        blocked = (
            not board.is_in_bounds(target)
            or board.has_tag_at(ground_layer_id, target, wall_tag, game.entity_kinds)
            or target in occupied
        )
        if blocked:
            return [ev.actor_blocked(entity.kind, pos)]

        board.set_entity(actor_layer_id, pos, None)
        board.set_entity(actor_layer_id, target, entity)
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
