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
    """Sort actions by JSON representation, assign a1, a2, … Return label→action dict."""
    sorted_actions = sorted(valid_actions, key=lambda a: json.dumps(a, sort_keys=True))
    return {f"a{i + 1}": a for i, a in enumerate(sorted_actions)}
