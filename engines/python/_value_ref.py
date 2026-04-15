"""
Value reference resolver.

Handles $event.<field>, $cell.<layer>.kind, $cell.<layer>.param.<key>,
$avatar.position, $avatar.item.

Mirrors Dart's value_ref.dart / resolveRef().
"""
from __future__ import annotations
from typing import Any
from ._models import Pos, GameState, Board


def resolve_ref(value: Any, event: dict, state: GameState) -> Any:
    """
    Resolve a value that may contain a $-reference string.
    Non-string values (and strings not starting with '$') are returned as-is.
    """
    if not isinstance(value, str) or not value.startswith("$"):
        return value

    parts = value[1:].split(".")

    if parts[0] == "event":
        if len(parts) < 2:
            return None
        raw = event.get(parts[1])
        # Convert Pos to [x, y] for JSON consumers (matches Dart behaviour)
        if isinstance(raw, Pos):
            return [raw.x, raw.y]
        return raw

    if parts[0] == "cell":
        # $cell.<layer>.kind  OR  $cell.<layer>.param.<key>
        pos_raw = event.get("position")
        if pos_raw is None:
            return None
        pos = pos_raw if isinstance(pos_raw, Pos) else Pos.from_json(pos_raw)
        if len(parts) < 3:
            return None
        layer_id = parts[1]
        entity = state.board.get_entity(layer_id, pos)
        if parts[2] == "kind":
            return entity.kind if entity else None
        if parts[2] == "param" and len(parts) >= 4:
            return entity.param(parts[3]) if entity else None
        return None

    if parts[0] == "avatar":
        if len(parts) < 2:
            return None
        field = parts[1]
        if field == "position":
            p = state.avatar.position
            return [p.x, p.y] if p else None
        if field == "item":
            return state.avatar.item
        return None

    return None
