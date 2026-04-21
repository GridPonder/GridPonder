"""Goal renderer — Python port of goal description logic in llm_agent.dart."""
from __future__ import annotations
from typing import Any


def render_goals(
    level_def: dict,
    state,
    game_def,
    *,
    anonymize: bool = False,
    kind_to_label: dict[str, str] | None = None,
) -> str:
    """Return a semicolon-separated string describing all level goals."""
    goal_parts: list[str] = []
    for goal in level_def.get("goals", []):
        goal_type = goal.get("type", "")
        config: dict = goal.get("config", {})
        goal_id: str = goal.get("id", "")

        if goal_type == "reach_target":
            kind_id = config.get("targetKind")
            tag = config.get("targetTag")
            if anonymize:
                name = _resolve_entity_name_anon(game_def, kind_id, tag, kind_to_label or {})
            else:
                name = _resolve_entity_name(game_def, kind_id, tag)
            goal_parts.append(f"Reach the {name}")

        elif goal_type == "board_match":
            target_grid = _render_target_grid(
                game_def, config, kind_to_label=kind_to_label if anonymize else None
            )
            if target_grid:
                goal_parts.append(f"Arrange tiles to match the target pattern:\n{target_grid}")
            else:
                goal_parts.append("Arrange tiles to match the target pattern")

        elif goal_type == "sequence_match":
            sequence = [int(n) for n in (config.get("sequence") or [])]
            matched = state.sequence_indices.get(goal_id, 0)
            done = ", ".join(f"✓{n}" for n in sequence[:matched])
            pending = ", ".join(str(n) for n in sequence[matched:])
            progress = ", ".join(p for p in [done, pending] if p)
            goal_parts.append(
                f"Merge numbers in sequence [{progress}] ({matched}/{len(sequence)} done)"
            )

        elif goal_type == "all_cleared":
            kind_id = config.get("kind")
            tag = config.get("tag")
            if anonymize:
                name = _resolve_entity_name_anon(game_def, kind_id, tag, kind_to_label or {})
            else:
                name = _resolve_entity_name(game_def, kind_id, tag)
            goal_parts.append(f"Clear all {name}s from the board")

        elif goal_type == "sum_constraint":
            goal_parts.append(_describe_sum_constraint(config))

        elif goal_type == "count_constraint":
            goal_parts.append(_describe_count_constraint(config))

        elif goal_type == "param_match":
            goal_parts.append(
                _describe_param_match(
                    game_def, config, kind_to_label=kind_to_label if anonymize else None
                )
            )

        else:
            goal_parts.append(goal_type)

    return "; ".join(goal_parts)


def _resolve_entity_name(game_def, kind_id: str | None, tag: str | None) -> str:
    if kind_id is not None:
        kind_def = game_def.entity_kinds.get(kind_id)
        return (kind_def.get("uiName") if kind_def else None) or kind_id.replace("_", " ")
    if tag is not None:
        for k_id, k_def in game_def.entity_kinds.items():
            if tag in k_def.get("tags", []):
                return k_def.get("uiName") or k_id.replace("_", " ")
        return tag
    return "target"


def _resolve_entity_name_anon(
    game_def, kind_id: str | None, tag: str | None, kind_to_label: dict[str, str]
) -> str:
    resolved = kind_id
    if resolved is None and tag is not None:
        for k_id, k_def in game_def.entity_kinds.items():
            if tag in k_def.get("tags", []):
                resolved = k_id
                break
    if resolved is not None:
        return kind_to_label.get(resolved, resolved)
    return "?"


def _render_target_grid(
    game_def, config: dict, kind_to_label: dict[str, str] | None = None
) -> str | None:
    target_layers = config.get("targetLayers")
    if not target_layers:
        return None

    height: int | None = None
    width: int | None = None
    for rows in target_layers.values():
        height = len(rows)
        width = len(rows[0]) if rows else 0
        break
    if height is None or width is None:
        return None

    grid = [["." for _ in range(width)] for _ in range(height)]
    for layer_rows in target_layers.values():
        for y, row in enumerate(layer_rows):
            for x, kind_id in enumerate(row):
                if kind_id is None:
                    continue
                if kind_to_label is not None:
                    sym = kind_to_label.get(kind_id, kind_id[0])
                else:
                    kind_def = game_def.entity_kinds.get(kind_id)
                    sym = (kind_def.get("symbol") if kind_def else None) or kind_id[0]
                grid[y][x] = sym

    return "\n".join("".join(row) for row in grid)


def _describe_sum_constraint(config: dict) -> str:
    scope = config.get("scope", "board")
    target = config.get("target")
    comparison = config.get("comparison", "eq")
    index = config.get("index")

    scope_label = {
        "all_rows": "every row",
        "all_cols": "every column",
        "row": f"row {index or '?'}",
        "col": f"column {index or '?'}",
    }.get(scope, scope)

    op_label = {
        "eq": f"= {target}",
        "gte": f"≥ {target}",
        "lte": f"≤ {target}",
    }.get(comparison, f"{comparison} {target}")

    return f"{scope_label} sums to {op_label}"


def _describe_count_constraint(config: dict) -> str:
    scope = config.get("scope", "board")
    predicate = config.get("predicate", "")
    target = config.get("target")
    comparison = config.get("comparison", "eq")
    index = config.get("index")

    scope_label = {
        "all_rows": "every row",
        "all_cols": "every column",
        "row": f"row {index or '?'}",
        "col": f"column {index or '?'}",
    }.get(scope, scope)

    if predicate == "even":
        predicate_label = "even"
    elif predicate == "odd":
        predicate_label = "odd"
    elif predicate.startswith("gte_"):
        predicate_label = f"≥ {predicate[4:]}"
    elif predicate.startswith("lte_"):
        predicate_label = f"≤ {predicate[4:]}"
    elif predicate.startswith("eq_"):
        predicate_label = predicate[3:]
    else:
        predicate_label = predicate

    try:
        n = int(target)
    except (TypeError, ValueError):
        n = 0

    count_label = {
        "eq": f"exactly {n}",
        "gte": f"at least {n}",
        "lte": f"at most {n}",
    }.get(comparison, f"{comparison} {n}")

    tile_word = "tile" if n == 1 else "tiles"
    return f"In {scope_label}: {count_label} {predicate_label} {tile_word}"


def _describe_param_match(
    game_def, config: dict, kind_to_label: dict[str, str] | None = None
) -> str:
    marker_kind = config.get("markerKind")
    check_kind = config.get("checkKind")
    check_param = config.get("checkParam")
    check_value = config.get("checkValue")

    def _name(kind_id: str | None, fallback: str) -> str:
        if kind_id is None:
            return fallback
        if kind_to_label is not None:
            return kind_to_label.get(kind_id, kind_id)
        kind_def = game_def.entity_kinds.get(kind_id)
        return (kind_def.get("uiName") if kind_def else None) or kind_id.replace("_", " ")

    marker_name = _name(marker_kind, "target")
    check_name = _name(check_kind, "piece")

    if check_param == "sides" and check_value == 15:
        return f"Fill every {marker_name} cell with a complete {check_name} (all 4 sides connected)"
    return f"Place a {check_name} on every {marker_name} where {check_param} = {check_value}"
