"""
Effect execution.

Effects are stored as raw dicts from JSON rules. This module applies them
to a mutable GameState, returning newly emitted events.

Mirrors Dart's effect_executor.dart.
"""
from __future__ import annotations
from typing import Any
from ._models import Pos, Entity, GameState
from ._game_def import GameDef
from ._value_ref import resolve_ref
from . import _events as ev


def execute(effect: dict, event: dict, state: GameState, game: GameDef) -> list[dict]:
    """Apply one effect to state, return emitted events."""
    def r(v: Any) -> Any:
        return resolve_ref(v, event, state)

    etype = effect.get("type") or next(iter(effect))  # key is the type

    # Normalise: effects may be {type: ..., ...} or {spawn: {...}} shorthand
    if "type" in effect:
        data = effect
    else:
        # shorthand: {effect_type: {fields...}}
        etype = next(iter(effect))
        data = effect[etype]
        if not isinstance(data, dict):
            data = {}

    match etype:
        case "spawn":
            return _spawn(data, r, state)
        case "destroy":
            return _destroy(data, r, state)
        case "transform":
            return _transform(data, r, state)
        case "move_entity":
            return _move_entity(data, r, state)
        case "set_cell":
            return _set_cell(data, r, state)
        case "release_from_emitter":
            return _release_from_emitter(data, state)
        case "apply_gravity":
            return _apply_gravity(data, state, game)
        case "set_variable":
            return _set_variable(data, r, state)
        case "increment_variable":
            return _increment_variable(data, state)
        case "set_inventory":
            return _set_inventory(data, r, state)
        case "clear_inventory":
            return _clear_inventory(state)
        case "resolve_move":
            return _resolve_move(state)
        case _:
            return []


def _resolve_pos(raw) -> Pos | None:
    if raw is None:
        return None
    if isinstance(raw, Pos):
        return raw
    return Pos.from_json(raw)


def _spawn(data: dict, r, state: GameState) -> list[dict]:
    pos = _resolve_pos(r(data.get("position")))
    if pos is None:
        return []
    layer_id = data.get("layer", "objects")
    kind = r(data.get("kind"))
    if kind is None:
        return []
    params = {k: r(v) for k, v in data.items() if k not in ("position", "layer", "kind")}
    state.board.set_entity(layer_id, pos, Entity(kind, params))
    return [ev.object_placed(pos, kind, params)]


def _destroy(data: dict, r, state: GameState) -> list[dict]:
    pos = _resolve_pos(r(data.get("position")))
    if pos is None:
        return []
    layer_id = data.get("layer", "objects")
    existing = state.board.get_entity(layer_id, pos)
    if existing is None:
        return []
    kind = existing.kind
    anim = data.get("animation")
    state.board.set_entity(layer_id, pos, None)
    return [ev.object_removed(pos, kind, anim), ev.cell_cleared(pos, kind)]


def _transform(data: dict, r, state: GameState) -> list[dict]:
    pos = _resolve_pos(r(data.get("position")))
    if pos is None:
        return []
    layer_id = data.get("layer", "objects")
    to_kind = r(data.get("toKind"))
    if to_kind is None:
        return []
    existing = state.board.get_entity(layer_id, pos)
    from_kind = existing.kind if existing else ""
    anim = data.get("animation")
    state.board.set_entity(layer_id, pos, Entity(to_kind))
    events = [ev.cell_transformed(pos, from_kind, to_kind, layer_id)]
    if anim:
        events.append(ev.object_removed(pos, from_kind, anim))
    return events


def _move_entity(data: dict, r, state: GameState) -> list[dict]:
    from_pos = _resolve_pos(r(data.get("from")))
    to_pos = _resolve_pos(r(data.get("to")))
    if from_pos is None or to_pos is None:
        return []
    layer_id = data.get("layer", "objects")
    entity = state.board.get_entity(layer_id, from_pos)
    if entity is None:
        return []
    state.board.set_entity(layer_id, from_pos, None)
    state.board.set_entity(layer_id, to_pos, entity)
    return [ev.object_removed(from_pos, entity.kind), ev.object_placed(to_pos, entity.kind, entity.params)]


def _set_cell(data: dict, r, state: GameState) -> list[dict]:
    pos = _resolve_pos(r(data.get("position")))
    if pos is None:
        return []
    layer_id = data.get("layer", "objects")
    kind = r(data.get("kind"))
    if kind is None:
        return []
    params = {k: r(v) for k, v in data.items() if k not in ("position", "layer", "kind")}
    state.board.set_entity(layer_id, pos, Entity(kind, params))
    return [ev.object_placed(pos, kind, params)]


def _release_from_emitter(data: dict, state: GameState) -> list[dict]:
    emitter_id = data.get("emitterId", "")
    mco = state.board.get_multi_cell_object(emitter_id)
    if mco is None:
        return []
    queue = mco.params.get("queue", [])
    idx = mco.params.get("currentIndex", 0)
    if idx >= len(queue):
        return []
    value = queue[idx]
    mco.params["currentIndex"] = idx + 1
    exit_raw = mco.params.get("exitPosition")
    if exit_raw is None:
        return []
    exit_pos = Pos.from_json(exit_raw) if not isinstance(exit_raw, Pos) else exit_raw
    item_params = {"value": value}
    state.board.set_entity("objects", exit_pos, Entity("number", item_params))
    return [ev.item_released(emitter_id, "number", exit_pos, item_params)]


def _apply_gravity(data: dict, state: GameState, game: GameDef) -> list[dict]:
    selector = data.get("selector", {})
    tag = selector.get("tag")
    direction = data.get("direction", "down")
    dx, dy = {"left": (-1,0), "right": (1,0), "up": (0,-1), "down": (0,1)}.get(direction, (0,1))

    events = []
    board = state.board
    moved = True
    while moved:
        moved = False
        objects_layer = board.layers.get("objects")
        if objects_layer is None:
            break
        to_move = [
            (pos, entity)
            for pos, entity in objects_layer.entries()
            if tag is None or game.has_tag(entity.kind, tag)
        ]
        # Sort order: process from gravity-destination side first
        reverse = direction in ("down", "right")
        to_move.sort(key=lambda pe: (pe[0].y if dy else pe[0].x), reverse=reverse)
        for pos, entity in to_move:
            next_pos = Pos(pos.x + dx, pos.y + dy)
            if not board.is_in_bounds(next_pos):
                continue
            if board.is_void(next_pos):
                continue
            if board.get_entity("objects", next_pos) is not None:
                continue
            board.set_entity("objects", pos, None)
            board.set_entity("objects", next_pos, entity)
            events.append(ev.object_settled(entity.kind, next_pos, pos))
            moved = True
    return events


def _set_variable(data: dict, r, state: GameState) -> list[dict]:
    name = data.get("name", "")
    value = r(data.get("value"))
    old = state.variables.get(name)
    state.variables[name] = value
    return [ev.variable_changed(name, old, value)]


def _increment_variable(data: dict, state: GameState) -> list[dict]:
    name = data.get("name", "")
    amount = data.get("amount", 1)
    old = state.variables.get(name, 0)
    new_val = old + amount
    state.variables[name] = new_val
    return [ev.variable_changed(name, old, new_val)]


def _set_inventory(data: dict, r, state: GameState) -> list[dict]:
    item = r(data.get("item"))
    old = state.avatar.item
    state.avatar.item = item
    return [ev.inventory_changed(old, item)]


def _clear_inventory(state: GameState) -> list[dict]:
    old = state.avatar.item
    if old is None:
        return []
    state.avatar.item = None
    return [ev.inventory_changed(old, None)]


def _resolve_move(state: GameState) -> list[dict]:
    pm = state.pending_move
    if pm is None:
        return []
    state.pending_move = None
    state.avatar.position = pm.to_pos
    state.avatar.facing = pm.direction
    return [ev.avatar_exited(pm.from_pos), ev.avatar_entered(pm.to_pos, pm.from_pos, pm.direction)]
