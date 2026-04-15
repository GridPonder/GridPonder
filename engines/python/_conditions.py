"""
Condition evaluation.

Conditions are stored as raw dicts (parsed from JSON rules). This module
evaluates them against a (event, state, game_def) context.

Mirrors Dart's condition.dart + condition_evaluator.dart.
"""
from __future__ import annotations
from typing import Any, Optional
from ._models import Pos, GameState
from ._game_def import GameDef


def _event_pos(event: dict) -> Optional[Pos]:
    p = event.get("position")
    if p is None:
        return None
    return p if isinstance(p, Pos) else Pos.from_json(p)


def evaluate(condition: Optional[dict], event: dict, state: GameState, game: GameDef) -> bool:
    """
    Evaluate a condition dict against the current event + state.
    None condition → True (unconditional rule).
    """
    if condition is None:
        return True

    # Compound
    if "all_of" in condition:
        return all(evaluate(c, event, state, game) for c in condition["all_of"])
    if "any_of" in condition:
        return any(evaluate(c, event, state, game) for c in condition["any_of"])
    if "not" in condition:
        return not evaluate(condition["not"], event, state, game)

    # Spatial / event conditions (used in `where`)
    if "position_has_tag" in condition:
        c = condition["position_has_tag"]
        pos = _event_pos(event)
        if pos is None:
            return False
        return game.has_tag(
            (state.board.get_entity(c["layer"], pos) or _dummy).kind,
            c["tag"],
        )

    if "position" in condition:
        pos = _event_pos(event)
        if pos is None:
            return False
        target = Pos.from_json(condition["position"])
        return pos == target

    if "event" in condition:
        c = condition["event"]
        if "kind" in c and event.get("kind") != c["kind"]:
            return False
        if "param" in c and "equals" in c:
            if event.get(c["param"]) != c["equals"]:
                return False
        return True

    # State conditions (used in `if`)
    if "cell" in condition:
        c = condition["cell"]
        pos = Pos.from_json(c["position"])
        layer_id = c["layer"]
        entity = state.board.get_entity(layer_id, pos)
        if "kind" in c:
            return (entity.kind if entity else None) == c["kind"]
        if "isEmpty" in c:
            return (entity is None) == c["isEmpty"]
        if "hasTag" in c:
            return game.has_tag(entity.kind if entity else "", c["hasTag"])
        return False

    if "avatar" in condition:
        c = condition["avatar"]
        if "at" in c:
            target = Pos.from_json(c["at"])
            if state.avatar.position != target:
                return False
        if "hasItem" in c:
            has_item_val = c["hasItem"]
            item = state.avatar.item
            if isinstance(has_item_val, bool):
                if has_item_val and item is None:
                    return False
                if not has_item_val and item is not None:
                    return False
            elif isinstance(has_item_val, str):
                if item != has_item_val:
                    return False
        return True

    if "variable" in condition:
        c = condition["variable"]
        name, op, target_val = c["name"], c["op"], c["value"]
        current = state.variables.get(name)
        return _compare(current, op, target_val)

    if "emitter_has_next" in condition:
        emitter_id = condition["emitter_has_next"]["emitterId"]
        mco = state.board.get_multi_cell_object(emitter_id)
        if mco is None:
            return False
        queue = mco.params.get("queue", [])
        idx = mco.params.get("currentIndex", 0)
        return idx < len(queue)

    if "board_count" in condition:
        c = condition["board_count"]
        kind = c.get("kind")
        tag = c.get("tag")
        layer_id = c.get("layer")
        op = c["op"]
        target_val = c["value"]
        count = _count_entities(state, game, kind=kind, tag=tag, layer_id=layer_id)
        return _compare(count, op, target_val)

    return False


def _compare(a: Any, op: str, b: Any) -> bool:
    try:
        if op == "eq":  return a == b
        if op == "neq": return a != b
        if op == "gt":  return a > b
        if op == "gte": return a >= b
        if op == "lt":  return a < b
        if op == "lte": return a <= b
    except TypeError:
        return a == b if op == "eq" else a != b if op == "neq" else False
    return False


def _count_entities(state: GameState, game: GameDef, *, kind=None, tag=None, layer_id=None) -> int:
    count = 0
    layers = (
        [(layer_id, state.board.layers[layer_id])]
        if layer_id and layer_id in state.board.layers
        else list(state.board.layers.items())
    )
    for _, layer in layers:
        for _, entity in layer.entries():
            if kind is not None and entity.kind == kind:
                count += 1
            elif tag is not None and game.has_tag(entity.kind, tag):
                count += 1
    return count


class _Dummy:
    kind = ""

_dummy = _Dummy()
