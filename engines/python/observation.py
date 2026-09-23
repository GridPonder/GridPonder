"""Observation builder — Python port of LlmAgent.buildPrompt() in llm_agent.dart.

`build_prompt()` produces an identical prompt string to the Dart runner.
`build_observation()` wraps build_prompt and returns the full observation dict
used by runner.py.
"""
from __future__ import annotations
import json
from typing import Any

from .text_renderer import render as render_board
from .goal_renderer import render_goals
from .action_enum import enumerate_actions
from .anon import build_anon_kind_to_label, build_anon_reverse_map
from .gold_path import gold_path_length
from ._models import Pos


_IMAGE_BOARD_NOTE = (
    "(See the attached image of the current board. Columns are numbered "
    "along the top (0..); rows are numbered down the left (0..). Use those "
    "coordinates to refer to specific cells.)"
)

# Image mode attaches only the current board, so the BOARD BEFORE slot says
# so instead of pointing at an image that is not there.
_IMAGE_PREVIOUS_NOTE = (
    "(Not shown: only the current board is attached as an image.)"
)

# What each non-sprite mark the image renderer can draw means. Keys are the
# marks board_image.render_board_image reports; only drawn marks are named.
_IMAGE_MARK_TEXT = {
    "selected": "a gold ring marks the selected piece",
    "overlay": "an amber frame marks the overlay region (the cells your "
               "selection-based actions operate on)",
    "hidden": "a small boxed inset in a cell's lower-left corner shows an "
              "item lying underneath what is drawn on top of it",
}


def _image_marks_sentence(marks) -> str:
    parts = [_IMAGE_MARK_TEXT[m] for m in _IMAGE_MARK_TEXT if m in (marks or ())]
    return ("Image marks: " + "; ".join(parts) + ".") if parts else ""


def build_prompt(
    game_def,
    level_def: dict,
    state,
    *,
    attempt_number: int = 1,
    total_actions: int = 0,
    last_action: dict | None = None,
    previous_board_text: str | None = None,
    previous_inventory: str | None = None,
    anonymize: bool = False,
    kind_symbol_overrides: dict[str, str] | None = None,
    inference_mode: str = "single",
    step_size: int = 3,
    max_n: int | None = None,
    memory: str = "",
    text_board: bool = True,
    attach_image: bool = False,
    valid_actions: list[dict[str, Any]] | None = None,
    previous_attempt: str | None = None,
    rejected_action: dict | None = None,
    rejection_detail: str | None = None,
    image_marks: list[str] | None = None,
) -> str:
    """Build the full LLM prompt string matching the Dart runner output.

    text_board: when False, the rendered grid + legend are replaced with a
    short note pointing to the attached image. Used for input mode "image".
    attach_image: signals that an image is attached alongside the prompt.
    Combined with text_board=True (text+image mode) it adds an explicit
    "the image is the same current board" note so the model doesn't waste
    reasoning on what the image is or whether it matches the text grid.
    previous_attempt: how the previous attempt ended (e.g. "lost — move limit
    of 6 reached"); shown as `PREVIOUS ATTEMPT: ...` before `CURRENT BOARD`
    on an attempt's first prompt (only when last_action is None).
    rejected_action / rejection_detail: the most recently submitted action was
    rejected; the prompt says so and shows only the current board.
    image_marks: the marks the attached image carries (as reported by
    board_image.render_board_image); explained next to the image note.
    """
    if valid_actions is None:
        valid_actions = enumerate_actions(game_def, state)

    # ── Anon maps ────────────────────────────────────────────────────────────
    kind_to_label: dict[str, str] = {}
    action_forward: dict[str, str] = {}
    if anonymize:
        kind_to_label = build_anon_kind_to_label(game_def)
        kind_symbol_overrides = kind_to_label
        sorted_actions = sorted(valid_actions, key=lambda a: json.dumps(a, sort_keys=True))
        action_forward = {
            json.dumps(a, sort_keys=True): f"a{i + 1}"
            for i, a in enumerate(sorted_actions)
        }

    # ── Board unchanged? (compared before any image-mode substitution) ────────
    board_unchanged = False
    if last_action is not None and rejected_action is None and previous_board_text is not None:
        current_bare = render_board(
            state, game_def, include_legend=False,
            kind_symbol_overrides=kind_symbol_overrides,
        )
        current_inv = state.avatar.item if state.avatar.enabled else None
        board_unchanged = (
            current_bare == previous_board_text and current_inv == previous_inventory
        )

    # ── Board text (current) ──────────────────────────────────────────────────
    marks_sentence = _image_marks_sentence(image_marks) if attach_image else ""
    if text_board:
        board_text = render_board(state, game_def, kind_symbol_overrides=kind_symbol_overrides)
    else:
        board_text = _IMAGE_BOARD_NOTE
        if marks_sentence:
            board_text += "\n" + marks_sentence
        if previous_board_text is not None:
            previous_board_text = _IMAGE_PREVIOUS_NOTE

    # ── Goals ─────────────────────────────────────────────────────────────────
    goal_descriptions = render_goals(
        level_def, state, game_def, anonymize=anonymize, kind_to_label=kind_to_label
    )

    # ── Actions desc ──────────────────────────────────────────────────────────
    if anonymize:
        actions_desc = ", ".join(
            '{"action": "' + (action_forward.get(json.dumps(a, sort_keys=True), "?")) + '"}'
            for a in valid_actions
        )
    else:
        actions_desc = ", ".join(json.dumps(a, sort_keys=True) for a in valid_actions)

    # ── Inventory / moves ─────────────────────────────────────────────────────
    inv = state.avatar.item if state.avatar.enabled else None
    # The inventory holds a kind id; an anonymous prompt shows its alias, as
    # the board and legend do, so the raw kind name never leaks.
    def _shown_item(item):
        return kind_to_label.get(item, item) if anonymize else item

    inventory_line = f"\nInventory: {_shown_item(inv)}" if inv is not None else ""

    moves_line = status_lines(
        game_def, level_def, state,
        anonymize=anonymize, kind_to_label=kind_to_label,
    )

    memory_section = (
        f"\nMEMORY FROM PREVIOUS ACTION:\n{memory}\n" if memory else ""
    )

    prev_inventory_line = (
        f"\nInventory: {_shown_item(previous_inventory)}"
        if previous_inventory is not None else ""
    )

    # ── Last action label ─────────────────────────────────────────────────────
    last_action_label = ""
    if last_action is not None:
        if anonymize:
            label = action_forward.get(json.dumps(last_action, sort_keys=True), "?")
            last_action_label = '{"action": "' + label + '"}'
        else:
            last_action_label = json.dumps(last_action, sort_keys=True)

    # ── Last action section ───────────────────────────────────────────────────
    if rejected_action is not None:
        # The action exactly as submitted (an anonymous label in anon mode).
        rejected_label = json.dumps(
            {k: v for k, v in rejected_action.items() if k != "memory"},
            sort_keys=True,
        )
        last_action_section = (
            f"LAST ACTION: {rejected_label} — REJECTED ({rejection_detail or 'not legal in this state'}); "
            f"no action was spent, the board is unchanged.\n"
            f"CURRENT BOARD:\n"
            f"{board_text}{inventory_line}{moves_line}"
        )
    elif last_action is not None:
        inv_changed_line = (
            "If your inventory changed, note what was gained or lost.\n"
            if (inv is not None or previous_inventory is not None)
            else ""
        )
        unchanged_line = (
            "\nThe board did not change."
            if board_unchanged else ""
        )
        compare_line = (
            "Compare the two boards to understand exactly what your last action did "
            "(tiles removed, pushed, merged, etc.).\n"
            if text_board else
            "Compare the current board with your notes on the previous one to understand "
            "exactly what your last action did (tiles removed, pushed, merged, etc.).\n"
        )
        last_action_section = (
            f"LAST ACTION: {last_action_label}\n"
            f"BOARD BEFORE:\n"
            f"{previous_board_text}{prev_inventory_line}\n"
            f"\n"
            f"BOARD AFTER (current):\n"
            f"{board_text}{inventory_line}{moves_line}{unchanged_line}\n"
            f"\n"
            f"{compare_line}"
            f"{inv_changed_line}"
            f"Update your memory with any new observations about game mechanics or level layout.\n"
            f"Memory is your only way to retain knowledge across actions."
        )
    else:
        previous_attempt_line = (
            f"PREVIOUS ATTEMPT: {previous_attempt}\n" if previous_attempt else ""
        )
        last_action_section = (
            f"{previous_attempt_line}"
            f"CURRENT BOARD (first move of this attempt):\n"
            f"{board_text}{inventory_line}{moves_line}"
        )

    # ── Header ────────────────────────────────────────────────────────────────
    title_line = (
        "You are playing a grid puzzle."
        if anonymize
        else f'You are playing a grid puzzle called "{game_def.title}".'
    )
    if anonymize:
        description_section = (
            "\n2D grid game. Entities and rules unknown — "
            "discover by observation and experimentation.\n"
        )
    elif game_def.description:
        description_section = f"\n{game_def.description}\n"
    else:
        description_section = ""

    # In text+image mode we explicitly anchor the image to the current board
    # so the model doesn't speculate about what the attachment depicts. (Pure
    # image mode already substitutes the board section with a note that
    # references the image.)
    image_note = (
        "\nThe attached image is a sprite rendering of the current board "
        "(same state as the text grid above).\n"
        + (marks_sentence + "\n" if marks_sentence else "")
        if (text_board and attach_image) else ""
    )

    header = (
        f"{title_line}\n"
        f"Minimize total actions — give up early if stuck rather than wasting moves.\n"
        f"Attempt {attempt_number} | Total actions across all attempts: {total_actions}\n"
        f"{description_section}{memory_section}\n"
        f"GOAL: {goal_descriptions}\n"
        f"{last_action_section}{image_note}\n"
        f"\n"
        f"AVAILABLE ACTIONS:\n"
        f"{actions_desc}\n"
        f'{{"action": "give_up"}} — reset and start a fresh attempt'
    )

    # ── Examples ──────────────────────────────────────────────────────────────
    n = len(valid_actions)
    if anonymize:
        ex1 = '{"action": "a1"}'
        ex2 = f'{{"action": "a{n}"}}' if n > 1 else ex1
    else:
        ex1 = json.dumps(valid_actions[0], sort_keys=True) if valid_actions else '{"action": "..."}'
        ex2 = json.dumps(valid_actions[-1], sort_keys=True) if len(valid_actions) > 1 else ex1

    tail = _prompt_tail(inference_mode, step_size, max_n, ex1=ex1, ex2=ex2)

    return f"{header}\n\n{tail}"


def _max_actions_limit(level_def: dict) -> int | None:
    """Limit of the level's first `max_actions` lose condition, if any."""
    for condition in level_def.get("loseConditions") or []:
        if condition.get("type") != "max_actions":
            continue
        limit = (condition.get("config") or {}).get("limit")
        if isinstance(limit, int) and not isinstance(limit, bool):
            return limit
    return None


def _format_value(value) -> str:
    """Render a state variable for the status block. Integral floats print as
    integers so the text matches however the number was stored."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _individual_actors_config(game_def, level_def: dict) -> dict | None:
    effective = game_def.with_system_overrides(level_def.get("systemOverrides"))
    for system in effective.systems:
        if system.get("type") == "individual_actors" and system.get("enabled", True):
            return system.get("config") or {}
    return None


def status_lines(
    game_def,
    level_def: dict,
    state,
    *,
    anonymize: bool = False,
    kind_to_label: dict[str, str] | None = None,
) -> str:
    """Public status lines printed under the board, each prefixed by a newline.

    In order: the move counter (`k of N allowed` when the level has a
    `max_actions` lose condition; the bare count when it has other lose
    conditions only; nothing otherwise), the `individual_actors` selection and
    per-actor budgets when that system is enabled for the level, then every
    `ui.readouts` entry the pack declares. No other variable is printed.
    """
    kind_to_label = kind_to_label or {}

    def name_of(kind: str) -> str:
        if anonymize:
            return kind_to_label.get(kind, kind)
        kind_def = game_def.entity_kinds.get(kind)
        return (kind_def.get("uiName") if kind_def else None) or kind.replace("_", " ")

    lines: list[str] = []
    limit = _max_actions_limit(level_def)
    if limit is not None:
        lines.append(f"Moves this attempt: {state.action_count} of {limit} allowed")
    elif level_def.get("loseConditions"):
        lines.append(f"Moves this attempt: {state.action_count}")

    config = _individual_actors_config(game_def, level_def)
    if config is not None:
        selected_kind = state.variables.get(
            config.get("selectedVariable", "selectedActorKind"))
        raw_pos = state.variables.get(
            config.get("selectedPositionVariable", "selectedActorPosition"))
        if not selected_kind:
            lines.append("Selected: none")
        elif isinstance(raw_pos, (list, tuple)) and len(raw_pos) >= 2:
            x, y = int(raw_pos[0]), int(raw_pos[1])
            entity = state.board.get_entity(config.get("actorLayer", "actors"), Pos(x, y))
            if entity is not None and entity.kind == selected_kind:
                lines.append(f"Selected: {name_of(str(selected_kind))} at ({x},{y})")
            else:
                lines.append(
                    f"Selected: none (the piece selected at ({x},{y}) is gone or changed)")
        else:
            lines.append(f"Selected: {name_of(str(selected_kind))}")

        budgets = config.get("budgets")
        if isinstance(budgets, dict) and budgets:
            remaining = state.variables.get(
                config.get("budgetVariable", "actorMovesRemaining"))
            if not isinstance(remaining, dict):
                remaining = {}
            parts = []
            for kind, initial in budgets.items():
                value = remaining.get(kind, initial)
                parts.append(f"{name_of(str(kind))} {_format_value(value)}")
            lines.append("Moves left: " + ", ".join(parts))

    for i, readout in enumerate(getattr(game_def, "ui_readouts", []) or [], start=1):
        variable = readout["variable"]
        if variable not in state.variables:
            continue
        value = state.variables[variable]
        blank = readout.get("blankWhen")
        if (blank is not None and not isinstance(value, bool)
                and isinstance(value, (int, float)) and value == blank):
            shown = "-"
        else:
            shown = _format_value(value)
        label = f"Readout {i}" if anonymize else readout.get("label", "")
        lines.append(f"{label}: {shown}")

    return "".join(f"\n{line}" for line in lines)


def _prompt_tail(
    inference_mode: str,
    step_size: int,
    max_n: int | None,
    *,
    ex1: str,
    ex2: str,
) -> str:
    ex2_mem = ex2[:-1] + ', "memory": "Useful observation about the level."}'

    if inference_mode == "fixed-n":
        return (
            f"Respond with ONLY a JSON array of up to {step_size} actions on a single line, "
            f"no explanation or surrounding text. You may output fewer if the goal is reachable in fewer steps.\n"
            f"You will receive updated board state after the batch is applied.\n"
            f'Add a "memory" field to the last action to update your notes (replaces previous memory).\n'
            f"Examples:\n"
            f"  [{ex1}, {ex2}]\n"
            f"  [{ex2_mem}]\n"
            f'  [{{"action": "give_up", "memory": "Dead end. Must try a different approach."}}]\n'
            f"\n"
            f"Choose actions most likely to reach the goal in fewest total actions (summed across attempts)."
        )
    elif inference_mode == "flex-n":
        count_line = (
            f"Respond with ONLY a JSON array of 1 to {max_n} actions on a single line, "
            "no explanation or surrounding text."
            if max_n is not None
            else "Respond with ONLY a JSON array of one or more actions on a single line, "
            "no explanation or surrounding text."
        )
        return (
            f"{count_line}\n"
            f"Each action beyond the first counts as only 0.5 toward your total action score "
            f"(e.g. outputting 3 actions = 2 effective actions). Minimize your effective total across all attempts.\n"
            f'Add a "memory" field to the last action to update your notes (replaces previous memory).\n'
            f"Examples:\n"
            f"  [{ex1}]\n"
            f"  [{ex1}, {ex2}, {ex2_mem}]\n"
            f'  [{{"action": "give_up", "memory": "Dead end. Must try a different approach."}}]\n'
            f"\n"
            f"Choose actions most likely to reach the goal in fewest effective actions (summed across attempts)."
        )
    elif inference_mode == "full":
        return (
            f"Respond with a JSON array containing every action needed to solve the level. "
            f"No further board state will be shown — plan the complete sequence now.\n"
            f'Add a "memory" field to the last action if useful.\n'
            f"Example:\n"
            f"  [{ex1}, {ex2}, {ex2_mem}]\n"
            f"\n"
            f"Output the shortest sequence you are confident will solve the level."
        )
    else:  # single
        return (
            f"Respond with ONLY a JSON object on a single line.\n"
            f'You may optionally update your persistent memory by adding a "memory" field '
            f"(replaces previous memory).\n"
            f"Examples:\n"
            f"  {ex1}\n"
            f"  {ex2_mem}\n"
            f'  {{"action": "give_up", "memory": "Dead end. Must try a different approach."}}\n'
            f"\n"
            f"Choose the action most likely to reach the goal in fewest total actions (summed across attempts)."
        )


def build_observation(
    game_def,
    level_def: dict,
    state,
    *,
    attempt_number: int = 1,
    total_actions: int = 0,
    last_action: dict | None = None,
    previous_board_text: str | None = None,
    previous_inventory: str | None = None,
    anonymize: bool = False,
    kind_symbol_overrides: dict[str, str] | None = None,
    inference_mode: str = "single",
    step_size: int = 3,
    max_n: int | None = None,
    memory: str = "",
) -> dict[str, Any]:
    """Build the full observation dict for runner.py.

    Returns a dict with:
      - 'prompt': the complete LLM prompt string
      - 'valid_actions': list of valid action dicts (plus give_up)
      - metadata fields matching the Dart runner's state event
    """
    if anonymize and kind_symbol_overrides is None:
        kind_symbol_overrides = build_anon_kind_to_label(game_def)

    prompt = build_prompt(
        game_def,
        level_def,
        state,
        attempt_number=attempt_number,
        total_actions=total_actions,
        last_action=last_action,
        previous_board_text=previous_board_text,
        previous_inventory=previous_inventory,
        anonymize=anonymize,
        kind_symbol_overrides=kind_symbol_overrides,
        inference_mode=inference_mode,
        step_size=step_size,
        max_n=max_n,
        memory=memory,
    )

    valid_actions = enumerate_actions(game_def, state)
    gold_path_len = gold_path_length(level_def)

    return {
        "prompt": prompt,
        "valid_actions": valid_actions,
        "gold_path_length": gold_path_len,
    }
