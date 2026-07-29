"""Anonymous-mode helpers — Python port of agent.dart buildAnonKindToLabel / buildAnonReverseMap."""
from __future__ import annotations
import json
from typing import Any


def _anon_index_to_label(i: int) -> str:
    if i < 26:
        return chr(65 + i)
    return chr(65 + i // 26 - 1) + chr(65 + i % 26)


def build_anon_kind_to_label(game_def) -> dict[str, str]:
    """Sort entity kind IDs alphabetically and assign A, B, C, … labels.

    Kinds whose symbol is '.' or ' ' are excluded (they keep their original
    symbol so the board stays readable).
    """
    sorted_kinds = sorted(game_def.entity_kinds.keys())
    result: dict[str, str] = {}
    label_index = 0
    for kind_id in sorted_kinds:
        sym = game_def.entity_kinds[kind_id].get("symbol", "")
        if sym in (".", " "):
            continue
        result[kind_id] = _anon_index_to_label(label_index)
        label_index += 1
    return result


def build_anon_reverse_map(valid_actions: list[dict[str, Any]]) -> dict[str, dict]:
    """Sort actions by JSON representation, assign a1, a2, … Return label→action dict.

    Per-state: the labels are drawn from the *currently legal* actions and are
    renumbered every turn. Fine for the prompt-based benchmark, where the model
    is handed `valid_actions` anyway. Not usable where the legal-move list must
    stay hidden — use build_anon_action_shapes there.
    """
    sorted_actions = sorted(valid_actions, key=lambda a: json.dumps(a, sort_keys=True))
    return {f"a{i + 1}": a for i, a in enumerate(sorted_actions)}


def build_anon_action_shapes(game_def) -> tuple[list[dict], dict[str, dict]]:
    """Anonymise the action *schema*, not the legal-move list.

    Returns ``(shapes, table)``:

      shapes — game.json's `actions` with ids aliased to a1, a2, …, parameter
               names to p1, p2, … and enumerated values to v1, v2, …, in the
               same shape build_rules() consumes.
      table  — alias → {"action", "params": {alias: {"name", "values"}}}, used
               to translate an agent's anonymous action back to a real one.

    Derived from game.json alone, so the mapping is stable for the whole run
    and can be published in RULES.md. build_anon_reverse_map cannot be
    published that way: its labels enumerate the legal moves in the current
    state, which is exactly the hint an unassisted run must not get.

    Ordering is alphabetical at every level, so the mapping is deterministic
    for a given pack.
    """
    shapes: list[dict] = []
    table: dict[str, dict] = {}

    for a_idx, action in enumerate(sorted(game_def.actions, key=lambda a: a["id"])):
        alias = f"a{a_idx + 1}"
        params: dict = action.get("params") or {}
        shape_params: dict[str, dict] = {}
        table_params: dict[str, dict] = {}

        for p_idx, name in enumerate(sorted(params.keys())):
            spec = params[name]
            p_alias = f"p{p_idx + 1}"
            new_spec: dict[str, Any] = {}
            if "type" in spec:
                # The type is mechanical, not semantic: an agent cannot form a
                # position without knowing it is an [x, y] pair.
                new_spec["type"] = spec["type"]
            values = spec.get("values")
            if values:
                value_alias = {f"v{v_idx + 1}": v for v_idx, v in enumerate(sorted(values, key=str))}
                new_spec["values"] = list(value_alias.keys())
                table_params[p_alias] = {"name": name, "values": value_alias}
            else:
                table_params[p_alias] = {"name": name, "values": None}
            shape_params[p_alias] = new_spec

        shapes.append({"id": alias, "params": shape_params})
        table[alias] = {"action": action["id"], "params": table_params}

    return shapes, table


def resolve_anon_action(table: dict[str, dict], submitted: dict) -> dict | None:
    """Translate one anonymous action dict into its real form.

    Returns None when the alias is unknown, a parameter alias is unknown, or an
    enumerated value alias is unknown — all of which are schema errors the
    caller should report as such rather than silently pass to the engine.
    """
    entry = table.get(submitted.get("action"))
    if entry is None:
        return None

    real: dict[str, Any] = {"action": entry["action"]}
    for key, value in submitted.items():
        if key == "action":
            continue
        param = entry["params"].get(key)
        if param is None:
            return None
        if param["values"] is not None:
            if value not in param["values"]:
                return None
            real[param["name"]] = param["values"][value]
        else:
            real[param["name"]] = value
    return real
