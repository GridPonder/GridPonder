"""Action enumerator — Python port of AgentObservation._enumerateActions() in agent.dart."""
from __future__ import annotations
from typing import Any


def enumerate_actions(game_def, state) -> list[dict[str, Any]]:
    """Return list of all valid action dicts for the current state.

    Each dict has at least an 'action' key plus any param keys.
    Actions whose required entity kind is absent from the board are skipped.
    """
    present_kinds: set[str] = set()
    for layer in state.board.layers.values():
        for _pos, entity in layer.entries():
            present_kinds.add(entity.kind)

    actions: list[dict[str, Any]] = []
    for action_def in game_def.actions:
        entity_kind = action_def.get("entityKind")
        if entity_kind is not None and entity_kind not in present_kinds:
            continue
        params_def: dict = action_def.get("params", {})
        if not params_def:
            actions.append({"action": action_def["id"]})
        else:
            _enumerate(action_def["id"], list(params_def.items()), {}, actions)
    return actions


def _enumerate(
    action_id: str,
    param_entries: list[tuple[str, dict]],
    current: dict[str, Any],
    out: list[dict[str, Any]],
) -> None:
    if not param_entries:
        out.append({"action": action_id, **current})
        return
    name, param_def = param_entries[0]
    rest = param_entries[1:]
    for value in param_def.get("values", []):
        _enumerate(action_id, rest, {**current, name: value}, out)
