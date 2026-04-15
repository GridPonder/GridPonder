"""
Event helpers.  Events are plain dicts with a 'type' key and payload fields.
Factory functions match the Dart GameEvent named constructors.
"""
from __future__ import annotations
from typing import Any, Optional
from ._models import Pos


def _pos_to_list(pos: Pos) -> list[int]:
    return [pos.x, pos.y]


# ---------------------------------------------------------------------------
# Factory functions (mirror Dart GameEvent named constructors)
# ---------------------------------------------------------------------------

def avatar_entered(pos: Pos, from_pos: Pos, direction: str) -> dict:
    return {
        "type": "avatar_entered",
        "position": pos,
        "fromPosition": from_pos,
        "direction": direction,
    }


def avatar_exited(pos: Pos) -> dict:
    return {"type": "avatar_exited", "position": pos}


def move_blocked(target: Pos, from_pos: Pos, direction: str, blocker_kind: str) -> dict:
    return {
        "type": "move_blocked",
        "position": target,
        "fromPosition": from_pos,
        "direction": direction,
        "blockerKind": blocker_kind,
    }


def object_placed(pos: Pos, kind: str, params: dict | None = None, **extra) -> dict:
    e: dict[str, Any] = {"type": "object_placed", "position": pos, "kind": kind, "params": params or {}}
    e.update(extra)
    return e


def object_removed(pos: Pos, kind: str, animation: str | None = None) -> dict:
    e: dict[str, Any] = {"type": "object_removed", "position": pos, "kind": kind}
    if animation:
        e["animation"] = animation
    return e


def cell_cleared(pos: Pos, previous_kind: str) -> dict:
    return {"type": "cell_cleared", "position": pos, "previousKind": previous_kind}


def cell_transformed(pos: Pos, from_kind: str, to_kind: str, layer: str) -> dict:
    return {
        "type": "cell_transformed",
        "position": pos,
        "fromKind": from_kind,
        "toKind": to_kind,
        "layer": layer,
    }


def inventory_changed(old_item: str | None, new_item: str | None) -> dict:
    return {"type": "inventory_changed", "oldItem": old_item, "newItem": new_item}


def object_pushed(kind: str, from_pos: Pos, to_pos: Pos, direction: str) -> dict:
    return {
        "type": "object_pushed",
        "kind": kind,
        "fromPosition": from_pos,
        "toPosition": to_pos,
        "direction": direction,
    }


def tiles_merged(pos: Pos, result_value: int, input_values: list[int]) -> dict:
    return {
        "type": "tiles_merged",
        "position": pos,
        "resultValue": result_value,
        "inputValues": input_values,
    }


def tiles_slid(direction: str, moved_count: int) -> dict:
    return {"type": "tiles_slid", "direction": direction, "movedCount": moved_count}


def item_released(emitter_id: str, kind: str, pos: Pos, params: dict | None = None) -> dict:
    return {
        "type": "item_released",
        "emitterId": emitter_id,
        "kind": kind,
        "position": pos,
        "params": params or {},
    }


def object_settled(kind: str, pos: Pos, from_pos: Pos) -> dict:
    return {
        "type": "object_settled",
        "kind": kind,
        "position": pos,
        "fromPosition": from_pos,
    }


def variable_changed(name: str, old_val: Any, new_val: Any) -> dict:
    return {
        "type": "variable_changed",
        "variable": name,
        "oldValue": old_val,
        "newValue": new_val,
    }


def turn_ended(turn_number: int) -> dict:
    return {"type": "turn_ended", "turnNumber": turn_number}


def overlay_moved(pos: list[int]) -> dict:
    return {"type": "overlay_moved", "position": pos}


def cells_flooded(cells: list[Pos]) -> dict:
    return {"type": "cells_flooded", "cells": cells}


def action_vetoed() -> dict:
    return {"type": "action_vetoed"}


def boxes_merged(pos: Pos, result_sides: int, a_sides: int, b_sides: int) -> dict:
    return {
        "type": "boxes_merged",
        "position": pos,
        "resultSides": result_sides,
        "aSides": a_sides,
        "bSides": b_sides,
    }


def region_transformed(op_type: str) -> dict:
    return {"type": "region_transformed", "opType": op_type}


# ---------------------------------------------------------------------------
# Accessor helpers
# ---------------------------------------------------------------------------

def event_position(event: dict) -> Optional[Pos]:
    p = event.get("position")
    if p is None:
        return None
    if isinstance(p, Pos):
        return p
    return Pos.from_json(p)
