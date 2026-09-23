"""Action enumerator — Python port of AgentObservation._enumerateActions() in agent.dart."""
from __future__ import annotations
from typing import Any


def enumerate_actions(game_def, state, engine=None) -> list[dict[str, Any]]:
    """Return action dictionaries available in the current state.

    Each dict has at least an 'action' key plus any param keys.
    Actions whose required entity kind is absent from the board are skipped.
    When ``engine`` is supplied, syntactic candidates are transactionally
    probed and vetoed/no-effect actions are removed.
    """
    present_kinds: set[str] = set()
    for layer in state.board.layers.values():
        for _pos, entity in layer.entries():
            present_kinds.add(entity.kind)

    actions: list[dict[str, Any]] = []
    for action_def in game_def.actions:
        entity_kind = action_def.get("entityKind")
        if entity_kind is not None and not present_kinds.intersection(entity_kind):
            continue
        params_def: dict = action_def.get("params", {})
        if not params_def:
            actions.append({"action": action_def["id"]})
        else:
            _enumerate(action_def["id"], list(params_def.items()), {}, actions, state)
    if engine is None:
        return actions
    # Asked once per state: whether a turn that only advances the counter
    # still changes what the board will do next.
    matters = getattr(engine, "turn_count_matters", None)
    beat_matters = bool(matters()) if callable(matters) else False
    return [action for action in actions
            if _is_effectful(engine, action, beat_matters)]


def _enumerate(
    action_id: str,
    param_entries: list[tuple[str, dict]],
    current: dict[str, Any],
    out: list[dict[str, Any]],
    state,
) -> None:
    if not param_entries:
        out.append({"action": action_id, **current})
        return
    name, param_def = param_entries[0]
    rest = param_entries[1:]
    if param_def.get("type") == "position":
        values = [
            [x, y]
            for y in range(state.board.height)
            for x in range(state.board.width)
        ]
    else:
        values = param_def.get("values", [])

    for value in values:
        _enumerate(action_id, rest, {**current, name: value}, out, state)


#: Events that do not by themselves make an action effectful: the pipeline's
#: tick, and a selection event that re-selects what is already selected (a
#: real selection change also changes the state key).
_NON_EFFECT_EVENTS = frozenset({"turn_ended", "actor_selected"})


def _is_effectful(engine, action: dict[str, Any], beat_matters: bool = False) -> bool:
    """Accepted AND (state key changed OR a meaningful event OR won OR lost OR
    the turn counter advanced while some system's behaviour depends on it)."""
    before = engine.state_key()
    turns_before = engine.state.turn_count
    action_id = action["action"]
    params = {key: value for key, value in action.items() if key != "action"}
    result = engine.execute_turn(action_id, params)
    if not result.accepted:
        return False
    after = engine.state_key()
    beat_advanced = beat_matters and engine.state.turn_count != turns_before
    meaningful_event = any(
        event.get("type") not in _NON_EFFECT_EVENTS for event in result.events
    )
    restored = engine.undo()
    if not restored:
        raise RuntimeError(f"Action probe could not restore state for {action!r}")
    return (before != after or meaningful_event or beat_advanced
            or result.is_won or result.is_lost)
