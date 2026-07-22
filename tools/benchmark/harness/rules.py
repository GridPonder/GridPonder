"""Generate the RULES.md an agent sees inside the sandbox.

Generated from the loaded pack, never hand-written: hand-written rules drift
from the pack and quietly make packs incomparable.

Emits action SHAPES (id + parameter names/types), not the set of
currently-legal action instances, and never anything about the intended
solution. Handing an agent the legal-move list would replace search with
menu-filtering, and would make rejected_count meaningless; handing it the
gold path or its length would make the run meaningless.
"""
from __future__ import annotations

_HEADER = """# The Puzzle{title_suffix}

You are playing a grid puzzle. Solve it in as few actions as possible.

## Goal

{goals}
{mechanics}
## How to play

Run these commands. They are the only way to interact with the puzzle.

    ./play state          Show the current board.
    ./play move '<json>'  Apply one action, e.g. ./play move '{example}'
    ./play history         List the actions you have taken this attempt.
    ./play give_up         Abandon this attempt and restart from the initial board.

An illegal move is rejected and the board does not change. A rejected move
still costs you nothing but a turn, so think before moving.

There is a limit on total actions. When you reach it the run ends.

## Actions

Every move is submitted as a JSON object with an "action" field naming the
action, plus whichever parameters that action takes.

{actions}
## Board notation

The board is printed as a text grid with a legend naming each symbol. Read the
legend — symbols differ between puzzles.
"""

# Human-readable gloss for parameter types that don't carry an explicit
# `values` list (direction/enum params already list their own values).
_TYPE_GLOSS = {
    "position": "a `[x, y]` board coordinate",
    "integer": "a whole number",
    "string": "a text value",
}


def _example_value(spec: dict):
    """A single representative value for a param, used to build a concrete
    example JSON call. Picking one legal value here is not the same as
    listing legal action *instances* — every action gets exactly one fixed
    example regardless of board state, purely to show the JSON shape."""
    values = spec.get("values")
    if values:
        return values[0]
    ptype = spec.get("type")
    if ptype == "position":
        return [0, 0]
    if ptype == "integer":
        return 0
    return "..."


def _describe_param(name: str, spec: dict) -> str:
    values = spec.get("values")
    if values:
        return f"- `{name}` — one of: {', '.join(str(v) for v in values)}"
    ptype = spec.get("type", "value")
    gloss = _TYPE_GLOSS.get(ptype, f"a {ptype} value")
    return f"- `{name}` — {gloss}"


def _action_shape(action: dict) -> str:
    action_id = action["id"]
    params: dict = action.get("params") or {}

    example = {"action": action_id}
    for name, spec in params.items():
        example[name] = _example_value(spec)

    lines = [f"### `{action_id}`", "", f"Shape: `{example}`".replace("'", '"')]
    if params:
        lines.append("")
        lines.append("Parameters:")
        for name, spec in params.items():
            lines.append(_describe_param(name, spec))
    else:
        lines.append("")
        lines.append("No parameters.")
    lines.append("")
    return "\n".join(lines)


def build_rules(game_def, level_def: dict, *, goals_text: str) -> str:
    """Return the full RULES.md body for one level.

    Pure function: no file I/O, no printing. Uses only pack-wide, static
    information (action shapes, the game's general mechanics blurb, the
    level title) plus the caller-supplied goal text — never board state,
    never the level's gold path or hints.
    """
    actions: list[dict] = game_def.actions

    level_title = level_def.get("title") if isinstance(level_def, dict) else None
    title_suffix = f": {level_title}" if level_title else ""

    mechanics = ""
    description = getattr(game_def, "description", "") or ""
    if description:
        mechanics = f"\n## Mechanics\n\n{description}\n"

    if actions:
        example_action = actions[0]
        example_params = {
            name: _example_value(spec)
            for name, spec in (example_action.get("params") or {}).items()
        }
        example = {"action": example_action["id"], **example_params}
        example_json = str(example).replace("'", '"')
    else:
        example_json = '{"action": "..."}'

    action_blocks = "\n".join(_action_shape(action) for action in actions)

    return _HEADER.format(
        title_suffix=title_suffix,
        goals=goals_text,
        mechanics=mechanics,
        example=example_json,
        actions=action_blocks,
    )
