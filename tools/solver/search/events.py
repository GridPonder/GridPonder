"""
Generic DSL event formatting and constraint checking.

Events use the same vocabulary as the Dart engine's event.dart.  Because the
event types are DSL-level (not game-level), both functions work for any game
that emits standard events from its apply() call — no per-game code needed.
"""

from __future__ import annotations

from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Event formatting
# ---------------------------------------------------------------------------

def format_event(event: Dict[str, Any]) -> str:
    """Return a human-readable description of a single DSL event dict."""
    t = event.get("type", "")

    if t == "avatar_entered":
        pos = event.get("position", "?")
        frm = event.get("from", "?")
        direction = event.get("direction", "?")
        return f"avatar moved {direction} from {frm} to {pos}"

    if t == "avatar_exited":
        return f"avatar left {event.get('position', '?')}"

    if t == "move_blocked":
        blocker = event.get("blockerKind", "obstacle")
        pos = event.get("position", "?")
        return f"move blocked by {blocker} at {pos}"

    if t == "object_removed":
        kind = event.get("kind", "object")
        pos = event.get("position", "?")
        anim = event.get("animation")
        if anim:
            return f"{kind} at {pos} destroyed (animation: {anim})"
        return f"{kind} removed from {pos}"

    if t == "object_placed":
        kind = event.get("kind", "object")
        pos = event.get("position", "?")
        return f"{kind} placed at {pos}"

    if t == "inventory_changed":
        old = event.get("oldItem")
        new = event.get("newItem")
        if new and not old:
            return f"picked up {new}"
        if old and not new:
            return f"{old} used/consumed"
        return f"inventory: {old} → {new}"

    if t == "object_pushed":
        kind = event.get("kind", "object")
        frm = event.get("from", "?")
        to = event.get("to", "?")
        direction = event.get("direction", "?")
        return f"{kind} pushed {direction} from {frm} to {to}"

    if t == "boxes_merged":
        pos = event.get("position", "?")
        a = event.get("aSides", "?")
        b = event.get("bSides", "?")
        r = event.get("resultSides", "?")
        suffix = "  ★ complete box!" if r == 15 else ""
        return (f"box fragments merged at {pos}: "
                f"[{_sides_str(a)}] + [{_sides_str(b)}] → [{_sides_str(r)}]{suffix}")

    if t == "tiles_merged":
        pos = event.get("position", "?")
        result = event.get("resultValue", "?")
        inputs = event.get("inputValues", [])
        return f"tiles merged at {pos}: {' + '.join(str(v) for v in inputs)} → {result}"

    if t == "tiles_slid":
        direction = event.get("direction", "?")
        count = event.get("movedCount", "?")
        return f"{count} tile(s) slid {direction}"

    if t == "cells_flooded":
        cells = event.get("cells", [])
        return f"{len(cells)} cell(s) flooded"

    if t == "cell_transformed":
        pos = event.get("position", "?")
        frm = event.get("fromKind", "?")
        to = event.get("toKind", "?")
        return f"cell at {pos} transformed: {frm} → {to}"

    if t == "variable_changed":
        name = event.get("variable", "?")
        old = event.get("oldValue", "?")
        new = event.get("newValue", "?")
        return f"variable '{name}' changed: {old} → {new}"

    if t == "turn_ended":
        return f"turn {event.get('turnNumber', '?')} ended"

    if t == "action_vetoed":
        return "action vetoed (no effect)"

    # Generic fallback
    payload = {k: v for k, v in event.items() if k != "type"}
    return f"{t}: {payload}" if payload else t


def _sides_str(sides: Any) -> str:
    """Human-readable bitmask: e.g. 6 → 'R+D', 15 → 'U+R+D+L'."""
    if not isinstance(sides, int):
        return str(sides)
    names = []
    if sides & 1:  names.append("U")
    if sides & 2:  names.append("R")
    if sides & 4:  names.append("D")
    if sides & 8:  names.append("L")
    return "+".join(names) if names else "none"


# ---------------------------------------------------------------------------
# Constraint checking
# ---------------------------------------------------------------------------

def violates_constraint(
    events: List[Dict[str, Any]],
    constraint: Dict[str, Any],
) -> bool:
    """
    Return True if any event in *events* violates *constraint*.

    All constraints have the form::

        {"type": "must_not", "event": "<event_type>", <field>: <value>, ...}

    Every field besides "type" and "event" is matched against the corresponding
    field in each event dict.  List values in constraints are compared as tuples
    (since position fields are stored as lists in events).

    Examples::

        {"type": "must_not", "event": "object_removed",
         "kind": "rock", "position": [2, 3]}

        {"type": "must_not", "event": "avatar_entered",
         "position": [0, 0]}

        {"type": "must_not", "event": "boxes_merged",
         "position": [1, 2]}
    """
    if constraint.get("type") != "must_not":
        return False

    target_type = constraint.get("event")
    if not target_type:
        return False

    match_fields = {
        k: v for k, v in constraint.items()
        if k not in ("type", "event")
    }

    for e in events:
        if e.get("type") != target_type:
            continue
        if _fields_match(e, match_fields):
            return True

    return False


def _fields_match(event: Dict[str, Any], match_fields: Dict[str, Any]) -> bool:
    """Return True if every match field equals the corresponding event field."""
    for key, expected in match_fields.items():
        actual = event.get(key)
        # Normalise lists/Pos-like objects to tuples for position comparison
        if isinstance(expected, list):
            expected = tuple(expected)
        if isinstance(actual, list):
            actual = tuple(actual)
        elif hasattr(actual, "x") and hasattr(actual, "y") and not isinstance(actual, tuple):
            actual = (actual.x, actual.y)
        if actual != expected:
            return False
    return True
