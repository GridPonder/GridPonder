"""Goal renderer — Python port of goal description logic in llm_agent.dart."""
from __future__ import annotations
from typing import Any

from ._goal import balance_connected_counts, balance_counts
from .text_renderer import order_layer_ids


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
    overrides = getattr(game_def, "goal_descriptions", {}) or {}
    for goal in level_def.get("goals", []):
        goal_type = goal.get("type", "")
        config: dict = goal.get("config", {})
        goal_id: str = goal.get("id", "")

        # Per-game goal-text override (set in game.json `goalDescriptions`).
        # Skipped in anonymise mode since the override may name entities.
        # Goal types with live progress keep it after the override text, so a
        # hand-written description never hides how close the board is.
        if not anonymize and goal_id in overrides:
            progress = _goal_progress(goal_type, goal_id, config, state, game_def)
            if progress is not None:
                goal_parts.append(f"{overrides[goal_id]} (now: {progress})")
            else:
                goal_parts.append(overrides[goal_id])
            continue

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
                f"Merge numbers in sequence [{progress}] "
                f"({_sequence_progress(goal_id, config, state)})"
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

        elif goal_type == "balance":
            goal_parts.append(
                _describe_balance(
                    game_def, config, state,
                    kind_to_label=kind_to_label if anonymize else None,
                )
            )

        elif goal_type == "param_match":
            goal_parts.append(
                _describe_param_match(
                    game_def, config, kind_to_label=kind_to_label if anonymize else None
                )
            )

        else:
            goal_parts.append(goal_type)

    return "; ".join(goal_parts)


def _list_names(names: list[str]) -> str:
    if not names:
        return "the owners"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def _describe_balance(
    game_def, config: dict, state, *, kind_to_label: dict[str, str] | None
) -> str:
    """Describe a `balance` goal: divide the claimable cells between owners.

    Generic over the config rather than written for any one pack — the two
    flags are what the win condition actually reads, so the sentence changes
    with them. Written because the fallback branch renders an unhandled goal as
    its *type name*: an anonymous run of a pack with a balance goal was told,
    in full, that its objective was "balance". Clear mode hid it, since a pack
    with a `goalDescriptions` override never reaches the fallback and anonymous
    mode skips those overrides by design.

    In anonymous mode the owners come out as their aliases and the layer is
    never named: `territory` is the pack's own vocabulary, and aliasing covers
    entity kinds, not layer ids.

    Progress is included for the same reason `sequence_match` includes it — a
    goal you cannot tell you are close to meeting is a worse goal, not a harder
    one — and is counted by the same function the win condition uses.
    """
    owners = list(config.get("owners") or [])
    if kind_to_label is not None:
        names = [kind_to_label.get(owner, owner) for owner in owners]
    else:
        names = [_resolve_entity_name(game_def, owner, None) for owner in owners]

    listed = _list_names(names)
    require_equal = config.get("requireEqual", True)
    require_complete = config.get("requireComplete", True)
    if require_complete and require_equal:
        head = f"Claim every claimable cell, and give {listed} an equal number each"
    elif require_equal:
        head = f"Give {listed} an equal number of cells each"
    elif require_complete:
        head = f"Claim every claimable cell for {listed}"
    else:
        head = f"Claim cells for {listed}"

    if not owners:
        return head
    progress = _balance_progress(config, state, names)
    if config.get("requireConnected", False):
        sources = config.get("connectionSources") or {}
        listed_sources = ", ".join(
            f"{name} {_format_source(sources.get(owner))}"
            for name, owner in zip(names, owners)
        )
        head = (f"{head}, and each owner's cells must connect orthogonally to its "
                f"source cell [{listed_sources}]")
    return f"{head} ({progress})"


def _format_source(raw) -> str:
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return f"({int(raw[0])},{int(raw[1])})"
    return "-"


def _balance_progress(config: dict, state, names: list[str]) -> str:
    """The counts clause of a balance goal: cells per owner (connected/owned
    per owner when `requireConnected`), then `N of M claimed`. Counted by the
    same functions the win condition uses."""
    owners = list(config.get("owners") or [])
    counts, claimable = balance_counts(config, state)
    if config.get("requireConnected", False):
        connected = balance_connected_counts(config, state)
        cells = [
            f"{name} {connected.get(owner, 0)}/{counts.get(owner, 0)}"
            for name, owner in zip(names, owners)
        ]
        if cells:
            cells[0] += " connected"
        tally = ", ".join(cells)
    else:
        tally = ", ".join(f"{name} {counts.get(owner, 0)}"
                          for name, owner in zip(names, owners))
    owned = sum(counts.values())
    if claimable:
        return f"{tally} — {owned} of {claimable} claimed"
    return tally


def _sequence_progress(goal_id: str, config: dict, state) -> str:
    sequence = config.get("sequence") or []
    matched = state.sequence_indices.get(goal_id, 0)
    return f"{matched}/{len(sequence)} done"


def _goal_progress(goal_type: str, goal_id: str, config: dict, state, game_def) -> str | None:
    """Live progress appended to a `goalDescriptions` override, or None for
    goal types that carry no progress clause."""
    if goal_type == "balance":
        owners = list(config.get("owners") or [])
        if not owners:
            return None
        names = [_resolve_entity_name(game_def, owner, None) for owner in owners]
        return _balance_progress(config, state, names)
    if goal_type == "sequence_match":
        return _sequence_progress(goal_id, config, state)
    return None


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


def _target_cell_kind(cell) -> str | None:
    """Kind named by one `targetLayers` cell, or None for an unset one.

    A cell is either a bare kind or the entry form the spec's own example uses,
    `{"kind": "...", "<param>": ...}`. Indexing the second one for a fallback
    symbol raised `KeyError: 0` and took the whole observation down with it.
    """
    if isinstance(cell, str):
        return cell
    if isinstance(cell, dict):
        kind = cell.get("kind")
        return kind if isinstance(kind, str) else None
    return None


def _target_layer_order(game_def, target_layers: dict) -> list[str]:
    """Target layer ids top-to-bottom, using the board renderer's ordering
    (layers in game.json order stand in for board order)."""
    declared = [layer["id"] for layer in getattr(game_def, "layers", [])]
    in_board_order = [lid for lid in declared if lid in target_layers]
    in_board_order += [lid for lid in target_layers if lid not in in_board_order]
    return order_layer_ids(in_board_order)


def _kind_name(game_def, kind_id: str) -> str:
    kind_def = game_def.entity_kinds.get(kind_id)
    return (kind_def.get("uiName") if kind_def else None) or kind_id.replace("_", " ")


def _render_target_grid(
    game_def, config: dict, kind_to_label: dict[str, str] | None = None
) -> str | None:
    """The target pattern of a `board_match` goal, plus the lines that make it
    readable: which cells are free, which are required, and what every symbol
    in it means — including kinds that are not on the current board.

    `exact_non_null` (the default) leaves a null target cell unconstrained, so
    a cell null in every target layer renders `?`; `exact` requires it to be
    empty, so it keeps `.`. Where several target layers constrain one cell the
    grid shows the topmost (board-renderer order) and `Also required:` lists
    the rest.
    """
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

    exact = config.get("matchMode", "exact_non_null") == "exact"
    null_symbol = "." if exact else "?"
    anon = kind_to_label is not None

    def symbol_for(kind_id: str) -> str:
        # Anonymous mode: the kind's alias; kinds without one (`.`/space
        # symbols) keep their own symbol, exactly as on the board.
        if anon and kind_id in kind_to_label:
            return kind_to_label[kind_id]
        kind_def = game_def.entity_kinds.get(kind_id)
        return (kind_def.get("symbol") if kind_def else None) or kind_id[0]

    layer_order = _target_layer_order(game_def, target_layers)
    grid = [[null_symbol for _ in range(width)] for _ in range(height)]
    null_used = False
    grid_kinds: list[tuple[str, str]] = []  # (symbol, kind) in first-seen order
    also: list[str] = []
    for y in range(height):
        for x in range(width):
            kinds_here: list[str] = []
            for layer_id in layer_order:
                rows = target_layers.get(layer_id) or []
                if y >= len(rows) or not isinstance(rows[y], list) or x >= len(rows[y]):
                    continue
                kind_id = _target_cell_kind(rows[y][x])
                if kind_id is not None:
                    kinds_here.append(kind_id)
            if not kinds_here:
                null_used = True
                continue
            top = kinds_here[0]
            sym = symbol_for(top)
            grid[y][x] = sym
            if (sym, top) not in grid_kinds:
                grid_kinds.append((sym, top))
            for other in kinds_here[1:]:
                if anon:
                    also.append(f"({x},{y}) {symbol_for(other)}")
                else:
                    also.append(f"({x},{y}) {symbol_for(other)}={_kind_name(game_def, other)}")

    legend: list[str] = []
    if null_used:
        legend.append(".=must be empty" if exact else "?=any (unconstrained)")
    for sym, kind_id in grid_kinds:
        entry = sym if anon else f"{sym}={_kind_name(game_def, kind_id)}"
        if entry not in legend:
            legend.append(entry)

    lines = ["".join(row) for row in grid]
    lines.append("Target legend: " + ", ".join(legend))
    if also:
        lines.append("Also required: " + ", ".join(also))
    return "\n".join(lines)


def _describe_sum_constraint(config: dict) -> str:
    scope = config.get("scope", "board")
    target = config.get("target")
    comparison = config.get("comparison", "eq")
    index = config.get("index")

    scope_label = {
        "all_rows": "every row",
        "all_cols": "every column",
        "row": f"row {index if index is not None else '?'}",
        "col": f"column {index if index is not None else '?'}",
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
        "row": f"row {index if index is not None else '?'}",
        "col": f"column {index if index is not None else '?'}",
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


def describe_loss(level_def: dict, lose_reason: str | None, *, anonymize: bool = False) -> str:
    """Player-facing reason for an engine loss.

    `lose_reason` is the engine's reason code (`max_actions`,
    `variable_threshold:<variable>`, `premature_success:<goalId>`,
    `balance_budget_exhausted`, `balance_unreachable`). It is matched to the
    first lose condition of the same type (and the same variable / trigger goal
    where the code carries one). Named mode prefers that condition's optional
    `description`; otherwise, and always in anonymous mode, a generic sentence
    is built from its type, with variable and goal names replaced by `#<i>`
    (the condition's 1-based index) in anonymous mode.
    """
    code = lose_reason or ""
    ctype, _, key = code.partition(":")
    conditions = level_def.get("loseConditions") or []
    index = 0
    cond: dict | None = None
    for i, candidate in enumerate(conditions, start=1):
        if candidate.get("type") != ctype:
            continue
        cfg = candidate.get("config") or {}
        if ctype == "variable_threshold" and key and cfg.get("variable") != key:
            continue
        if ctype == "premature_success" and key and cfg.get("triggerGoalId") != key:
            continue
        index, cond = i, candidate
        break

    if cond is not None and not anonymize:
        description = cond.get("description")
        if isinstance(description, str) and description:
            return description

    cfg = (cond or {}).get("config") or {}
    if ctype == "max_actions":
        return f"move limit of {cfg.get('limit', '?')} reached"
    if ctype == "variable_threshold":
        name = f"#{index}" if anonymize else (cfg.get("variable") or key)
        return f'loss condition "{name}" reached'
    if ctype == "balance_budget_exhausted":
        return "a piece's remaining moves can no longer complete its share"
    if ctype == "balance_unreachable":
        return "the balance goal became unreachable"
    if ctype == "premature_success":
        name = f"#{index}" if anonymize else (cfg.get("triggerGoalId") or key)
        return f'goal "{name}" was met before the other required goals'
    if not ctype:
        return "the level was lost"
    name = f"#{index}" if anonymize else ctype
    return f'loss condition "{name}" reached'
