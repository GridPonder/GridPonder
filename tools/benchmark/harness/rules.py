"""Generate the RULES.md an agent sees inside the sandbox.

Generated from the loaded pack, never hand-written: hand-written rules drift
from the pack and quietly make packs incomparable.

Emits action SHAPES (id + parameter names/types), not the set of
currently-legal action instances, and never anything about the intended
solution. Handing an agent the legal-move list would replace search with
menu-filtering, and would make the rejection counters meaningless; handing it
the gold path or its length would make the run meaningless.

Anonymous runs pass an anonymised shape list via `actions=` (see
`engines.python.anon.build_anon_action_shapes`). Those shapes are derived from
game.json alone, so they stay constant for the whole run and still say nothing
about which actions are legal right now.
"""
from __future__ import annotations

import json

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

A move that is not a legal action right now is rejected: the board does not
change and the move does not count against your action budget. A move whose
JSON does not match the shapes below is rejected the same way. Five rejections
in a row end the run, so read the reply before trying again.

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


def _example_json(action: dict) -> str:
    """The example call for one action, as real JSON.

    json.dumps, not str(dict) with quotes swapped: str() emits Python repr, so
    a value containing an apostrophe ("O'Reilly") or a Python literal (True,
    None) produces something the agent cannot paste back.
    """
    example = {"action": action["id"]}
    for name, spec in (action.get("params") or {}).items():
        example[name] = _example_value(spec)
    return json.dumps(example)


def _action_shape(action: dict) -> str:
    action_id = action["id"]
    params: dict = action.get("params") or {}

    lines = [f"### `{action_id}`", "", f"Shape: `{_example_json(action)}`"]
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


def build_rules(
    game_def,
    level_def: dict,
    *,
    goals_text: str,
    actions: list[dict] | None = None,
    anonymized: bool = False,
) -> str:
    """Return the full RULES.md body for one level.

    Pure function: no file I/O, no printing. Uses only pack-wide, static
    information (action shapes, the game's general mechanics blurb, the
    level title) plus the caller-supplied goal text — never board state,
    never the level's gold path or hints.

    `actions` overrides the shape list, which is how anonymous runs document
    their aliased ids; `anonymized` also drops the game's mechanics blurb,
    since that prose names real entities.
    """
    if actions is None:
        actions = game_def.actions

    level_title = level_def.get("title") if isinstance(level_def, dict) else None
    title_suffix = "" if anonymized else (f": {level_title}" if level_title else "")

    if anonymized:
        # Same contract as observation.build_prompt's anonymous branch: the
        # blurb names entities, so an anonymous run is told to discover the
        # rules instead of being handed them.
        mechanics = (
            "\n## Mechanics\n\n2D grid game. Entities and rules unknown — "
            "discover by observation and experimentation.\n"
        )
    else:
        description = getattr(game_def, "description", "") or ""
        mechanics = f"\n## Mechanics\n\n{description}\n" if description else ""

    example_json = _example_json(actions[0]) if actions else '{"action": "..."}'

    action_blocks = "\n".join(_action_shape(action) for action in actions)

    return _HEADER.format(
        title_suffix=title_suffix,
        goals=goals_text,
        mechanics=mechanics,
        example=example_json,
        actions=action_blocks,
    )
