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


_IMAGE_BOARD_NOTE = (
    "(See the attached image of the current board. Columns are numbered "
    "along the top (0..); rows are numbered down the left (0..). Use those "
    "coordinates to refer to specific cells.)"
)


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
) -> str:
    """Build the full LLM prompt string matching the Dart runner output.

    text_board: when False, the rendered grid + legend are replaced with a
    short note pointing to the attached image. Used for input mode "image".
    attach_image: signals that an image is attached alongside the prompt.
    Combined with text_board=True (text+image mode) it adds an explicit
    "the image is the same current board" note so the model doesn't waste
    reasoning on what the image is or whether it matches the text grid.
    """
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

    # ── Board text (current) ──────────────────────────────────────────────────
    if text_board:
        board_text = render_board(state, game_def, kind_symbol_overrides=kind_symbol_overrides)
    else:
        board_text = _IMAGE_BOARD_NOTE
        if previous_board_text is not None:
            previous_board_text = _IMAGE_BOARD_NOTE

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
    inventory_line = f"\nInventory: {inv}" if inv is not None else ""

    has_lose_conditions = bool(level_def.get("loseConditions"))
    moves_line = f"\nMoves this attempt: {state.action_count}" if has_lose_conditions else ""

    memory_section = (
        f"\nMEMORY FROM PREVIOUS ACTION:\n{memory}\n" if memory else ""
    )

    prev_inventory_line = (
        f"\nInventory: {previous_inventory}" if previous_inventory is not None else ""
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
    if last_action is not None:
        inv_changed_line = (
            "If your inventory changed, note what was gained or lost.\n"
            if (inv is not None or previous_inventory is not None)
            else ""
        )
        last_action_section = (
            f"LAST ACTION: {last_action_label}\n"
            f"BOARD BEFORE:\n"
            f"{previous_board_text}{prev_inventory_line}\n"
            f"\n"
            f"BOARD AFTER (current):\n"
            f"{board_text}{inventory_line}{moves_line}\n"
            f"\n"
            f"Compare the two boards to understand exactly what your last action did "
            f"(tiles removed, pushed, merged, etc.).\n"
            f"{inv_changed_line}"
            f"Update your memory with any new observations about game mechanics or level layout.\n"
            f"Memory is your only way to retain knowledge across actions."
        )
    else:
        last_action_section = (
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
