"""Text renderer — Python port of text_renderer.dart.

Renders a GameState as a compact Unicode grid string.
"""
from __future__ import annotations
from ._models import Board, GameState, Pos

_AVATAR_SYMBOL = "@"
_LAYER_ORDER = ["actors", "markers", "objects", "territory", "ground"]
_VISIBLE_SPACE = "·"


def render(
    state: GameState,
    game_def,
    *,
    include_legend: bool = True,
    kind_symbol_overrides: dict[str, str] | None = None,
    level_def: dict | None = None,
) -> str:
    effective_game = (
        game_def.with_system_overrides(level_def.get("systemOverrides"))
        if level_def is not None
        else game_def
    )
    board = state.board
    w, h = board.width, board.height

    overlay = state.overlay
    grid_avatar_pos: Pos | None = None
    if overlay is None and state.avatar.enabled and state.avatar.position is not None:
        grid_avatar_pos = state.avatar.position

    # Build position→symbol map for multi-cell objects.
    mco_symbols: dict[Pos, str] = {}
    for mco in board.multi_cell_objects:
        exit_list = mco.params.get("exitPosition")
        exit_pos = Pos(int(exit_list[0]), int(exit_list[1])) if exit_list else None
        exit_dir = mco.params.get("exitDirection")
        cell_set = set(mco.cells)
        for cell in mco.cells:
            if cell == exit_pos:
                arrow = {"up": "▲", "left": "◄", "right": "►"}.get(exit_dir or "", "▼")
                mco_symbols[cell] = arrow
                continue
            h_conn = (
                Pos(cell.x - 1, cell.y) in cell_set
                or Pos(cell.x + 1, cell.y) in cell_set
            )
            v_conn = (
                Pos(cell.x, cell.y - 1) in cell_set
                or Pos(cell.x, cell.y + 1) in cell_set
            )
            mco_symbols[cell] = "═" if (h_conn and not v_conn) else "║" if (not h_conn and v_conn) else "╬"

    concealed_positions = _observation_concealed_positions(state, effective_game)

    lines = []
    for y in range(h):
        row = []
        for x in range(w):
            pos = Pos(x, y)
            if grid_avatar_pos == pos:
                row.append(_AVATAR_SYMBOL)
                continue
            object_symbol: str | None = None
            ground_symbol: str | None = None
            mco_symbol = mco_symbols.get(pos)
            if pos in concealed_positions and mco_symbol is not None:
                row.append(mco_symbol)
                continue
            for layer_id in _ordered_layers(state):
                entity = board.get_entity(layer_id, pos)
                if entity is None:
                    continue
                kind_def = effective_game.entity_kinds.get(entity.kind)
                sym = _get_symbol(entity, kind_def, kind_symbol_overrides)
                if layer_id == "ground":
                    ground_symbol = sym
                else:
                    object_symbol = sym
                    break
            row.append(object_symbol or mco_symbol or ground_symbol or ".")
        lines.append("".join(row))

    grid_str = "\n".join(lines)
    parts = [grid_str]

    if include_legend:
        legend = _build_legend(
            state,
            effective_game,
            grid_avatar_pos is not None,
            kind_symbol_overrides,
            concealed_positions,
        )
        parts.append(f"Each character is one cell, each line is one row. Legend: {legend}")

    numbers_block = _build_numbers_block(
        state, effective_game, concealed_positions
    )
    if numbers_block:
        parts.append(numbers_block)

    overlay_block = _build_overlay_block(
        state,
        effective_game,
        kind_symbol_overrides,
        mco_symbols,
        concealed_positions,
    )
    if overlay_block:
        parts.append(overlay_block)

    stacked_block = _build_stacked_block(
        state,
        effective_game,
        grid_avatar_pos,
        kind_symbol_overrides,
        mco_symbols,
        concealed_positions,
    )
    if stacked_block:
        parts.append(stacked_block)

    entity_state_block = _build_entity_state_block(
        state, effective_game, kind_symbol_overrides, concealed_positions
    )
    if entity_state_block:
        parts.append(entity_state_block)

    mco_block = _build_mco_block(state, effective_game, kind_symbol_overrides)
    if mco_block:
        parts.append(mco_block)

    target_status_block = _build_elastic_target_status_block(
        state,
        effective_game,
        level_def,
        kind_symbol_overrides,
    )
    if target_status_block:
        parts.append(target_status_block)

    return "\n\n".join(parts)


def _get_symbol(entity, kind_def: dict | None, kind_symbol_overrides: dict | None) -> str:
    if kind_def is None:
        return entity.kind[0].upper()
    if kind_def.get("symbolParam") is not None:
        param_val = entity.params.get(kind_def["symbolParam"])
        symbol = "N" if param_val is not None else kind_def["symbol"]
        return _VISIBLE_SPACE if symbol.isspace() else symbol
    if kind_symbol_overrides and entity.kind in kind_symbol_overrides:
        return kind_symbol_overrides[entity.kind]
    symbol = kind_def["symbol"]
    return _VISIBLE_SPACE if symbol.isspace() else symbol


def _ordered_layers(state: GameState) -> list[str]:
    known = [
        layer
        for layer in _LAYER_ORDER
        if layer != "ground" and layer in state.board.layers
    ]
    remaining = [
        layer for layer in state.board.layers
        if layer not in _LAYER_ORDER and layer != "ground"
    ]
    return [
        *known,
        *remaining,
        *(["ground"] if "ground" in state.board.layers else []),
    ]


def _observation_concealed_positions(state: GameState, game_def) -> set[Pos]:
    """Cells whose board-layer contents are hidden by an authored piece.

    The contract is opt-in through the multi-cell kind's
    ``observation_occluder`` tag. This keeps games such as Bellows free to
    expose target overlap while sliding-block packs can match their visual
    presentation and conceal keys, doors, or terrain below an opaque piece.
    """
    return {
        cell
        for mco in state.board.multi_cell_objects
        if game_def.has_tag(mco.kind, "observation_occluder")
        for cell in mco.cells
    }


def _is_legend_redundant(sym: str, label: str) -> bool:
    """True when the legend entry adds no information beyond the symbol itself.

    Currently catches single-digit symbols (0-9) whose only label is the same
    digit or the auto-derived "num <digit>" — e.g. "8=num 8" in diagonal_swipes
    where each digit tile is its own kind. The model can already interpret a
    digit as a number; the description provides context if needed.
    """
    s = sym.strip()
    l = label.strip().lower()
    if len(s) == 1 and s.isdigit() and l in (s, f"num {s}"):
        return True
    return False


def _build_legend(
    state: GameState,
    game_def,
    has_avatar: bool,
    kind_symbol_overrides,
    concealed_positions: set[Pos],
) -> str:
    seen: dict[str, str] = {}
    if has_avatar:
        seen[_AVATAR_SYMBOL] = "avatar (you)"

    for layer in state.board.layers.values():
        for pos, entity in layer.entries():
            if pos in concealed_positions:
                continue
            kind_def = game_def.entity_kinds.get(entity.kind)
            if kind_def is None:
                continue
            if kind_def.get("symbolParam") is not None:
                sym = "N"
                if kind_symbol_overrides is not None:
                    label = '? (exact value in "Number values")'
                else:
                    name = kind_def.get("uiName") or entity.kind.replace("_", " ")
                    desc = kind_def.get("description")
                    extra = f"; {desc}" if desc else ""
                    label = f'{name} (exact value in "Number values"{extra})'
            elif kind_symbol_overrides and entity.kind in kind_symbol_overrides:
                sym = kind_symbol_overrides[entity.kind]
                label = "?"
            else:
                sym = kind_def["symbol"]
                if sym.isspace():
                    sym = _VISIBLE_SPACE
                desc = kind_def.get("description")
                name = kind_def.get("uiName") or entity.kind.replace("_", " ")
                label = f"{name} ({desc})" if desc else name
            if sym in seen or _is_legend_redundant(sym, label):
                continue
            seen[sym] = label

    if state.board.multi_cell_objects:
        labels: list[str] = []
        for mco in state.board.multi_cell_objects:
            if kind_symbol_overrides is not None:
                label = "?"
            else:
                kind_def = game_def.entity_kinds.get(mco.kind)
                label = (
                    (kind_def.get("uiName") if kind_def else None)
                    or mco.kind.replace("_", " ")
                )
            if label not in labels:
                labels.append(label)
        body_label = (
            f"{labels[0]} body"
            if len(labels) == 1
            else "multi-cell object body"
        )
        seen["║/═/╬"] = body_label
        if any(
            mco.params.get("exitPosition")
            for mco in state.board.multi_cell_objects
        ):
            seen["▲/▼/◄/►"] = (
                "multi-cell object exit (arrow = exit direction)"
            )

    return "  ".join(f"{k}={v}" for k, v in seen.items())


def _build_overlay_block(
    state: GameState,
    game_def,
    kind_symbol_overrides,
    mco_symbols: dict[Pos, str],
    concealed_positions: set[Pos],
) -> str:
    """Show the overlay region as a focused mini-view of its cells.

    Without this the model only sees coordinates ("Overlay region: (0,0)–(1,1)")
    and has to mentally re-extract those cells from the full grid each turn.
    Rendering the actual contents alongside the bounds makes it explicit which
    cells the selection-based actions operate on.
    """
    overlay = state.overlay
    if overlay is None:
        return ""
    x1, y1 = overlay.x, overlay.y
    x2 = x1 + overlay.width - 1
    y2 = y1 + overlay.height - 1

    rows: list[str] = []
    for dy in range(overlay.height):
        chars = []
        for dx in range(overlay.width):
            x, y = x1 + dx, y1 + dy
            pos = Pos(x, y)
            if pos in concealed_positions and pos in mco_symbols:
                chars.append(mco_symbols[pos])
                continue
            sym = "."
            for layer_id in _ordered_layers(state):
                entity = state.board.get_entity(layer_id, pos)
                if entity is None:
                    continue
                kind_def = game_def.entity_kinds.get(entity.kind)
                if kind_def is None:
                    continue
                sym = _get_symbol(entity, kind_def, kind_symbol_overrides)
                break
            chars.append(sym)
        rows.append("".join(chars))
    contents = "\n".join(rows)

    return (
        f"Overlay region: ({x1},{y1})–({x2},{y2}). "
        f"These are the {overlay.width}×{overlay.height} cells your "
        f"selection-based actions operate on:\n{contents}"
    )


def _build_stacked_block(
    state: GameState,
    game_def,
    avatar_pos: Pos | None,
    kind_symbol_overrides,
    mco_symbols: dict[Pos, str],
    concealed_positions: set[Pos],
) -> str:
    entries_list: list[str] = []
    for y in range(state.board.height):
        for x in range(state.board.width):
            pos = Pos(x, y)
            symbols: list[str] = []
            if pos not in concealed_positions:
                for layer_id in _ordered_layers(state):
                    entity = state.board.get_entity(layer_id, pos)
                    if entity is None:
                        continue
                    kind_def = game_def.entity_kinds.get(entity.kind)
                    if kind_def is None:
                        sym = entity.kind[0].upper()
                        label = "?" if kind_symbol_overrides else entity.kind.replace("_", " ")
                    elif kind_def.get("symbolParam") is not None:
                        param_val = entity.params.get(kind_def["symbolParam"])
                        sym = "N" if param_val is not None else kind_def["symbol"]
                        label = "?" if kind_symbol_overrides else (
                            kind_def.get("uiName") or entity.kind.replace("_", " ")
                        )
                    elif kind_symbol_overrides and entity.kind in kind_symbol_overrides:
                        sym = kind_symbol_overrides[entity.kind]
                        label = "?"
                    else:
                        sym = kind_def["symbol"]
                        if sym.isspace():
                            sym = _VISIBLE_SPACE
                        label = kind_def.get("uiName") or entity.kind.replace("_", " ")

                    original_sym = kind_def["symbol"] if kind_def else sym
                    if sym == "." or original_sym == ".":
                        continue
                    symbols.append(f"{sym}({label})")

            if avatar_pos == pos:
                symbols.insert(0, "@(avatar)")

            mco_symbol = mco_symbols.get(pos)
            if mco_symbol is not None:
                mco = next(
                    (
                        item
                        for item in state.board.multi_cell_objects
                        if pos in item.cells
                    ),
                    None,
                )
                if kind_symbol_overrides is not None:
                    label = "?"
                else:
                    kind_def = (
                        game_def.entity_kinds.get(mco.kind)
                        if mco is not None
                        else None
                    )
                    label = (
                        (kind_def.get("uiName") if kind_def else None)
                        or (
                            mco.kind.replace("_", " ")
                            if mco is not None
                            else "multi-cell object"
                        )
                    )
                symbols.append(f"{mco_symbol}({label})")

            if len(symbols) >= 2:
                entries_list.append(f"  ({x},{y}): {' + '.join(symbols)}")

    if not entries_list:
        return ""
    return "Stacked cells (grid shows only top symbol):\n" + "\n".join(entries_list)


def _initial_target_cells(
    level_def: dict,
    game_def,
    marker_layer: str,
    marker_kind: str,
) -> list[Pos]:
    board_json = level_def.get("board")
    if not isinstance(board_json, dict):
        return []
    initial_board = Board.from_json(board_json, game_def.layers)
    layer = initial_board.layers.get(marker_layer)
    if layer is None:
        return []
    cells = [
        position
        for position, entity in layer.entries()
        if entity.kind == marker_kind
    ]
    return sorted(cells, key=lambda cell: (cell.y, cell.x))


def _build_elastic_target_status_block(
    state: GameState,
    game_def,
    level_def: dict | None,
    kind_symbol_overrides: dict[str, str] | None,
) -> str:
    if level_def is None or kind_symbol_overrides is not None:
        return ""
    system = game_def.get_system_by_type("elastic_block")
    if system is None or not system.get("enabled", True):
        return ""
    config = system.get("config", {})
    targets = config.get("targets") or []
    if not targets:
        return ""

    object_kind = str(config.get("objectKind", "elastic_block"))
    object_def = game_def.entity_kinds.get(object_kind, {})
    object_name = object_def.get("uiName") or object_kind.replace("_", " ")
    block = next(
        (
            mco
            for mco in state.board.multi_cell_objects
            if mco.kind == object_kind
        ),
        None,
    )
    block_cells = set(block.cells) if block is not None else set()
    completed_key = str(
        config.get("completedTargetIdsVariable", "completedTargetIds")
    )
    consumed_key = str(
        config.get("consumedTargetIdsVariable", "consumedTargetIds")
    )
    completed = {
        str(value) for value in state.variables.get(completed_key, [])
    }
    consumed = {
        str(value) for value in state.variables.get(consumed_key, [])
    }
    default_layer = str(config.get("targetLayer", "markers"))

    lines = [f"Target status (exact {object_name} footprint match required):"]
    for raw in targets:
        if not isinstance(raw, dict):
            continue
        marker_kind = str(raw.get("markerKind", ""))
        target_id = str(raw.get("id", marker_kind))
        if not marker_kind or not target_id:
            continue
        marker_layer = str(raw.get("markerLayer", default_layer))
        cells = _initial_target_cells(
            level_def,
            game_def,
            marker_layer,
            marker_kind,
        )
        if not cells:
            continue
        marker_def = game_def.entity_kinds.get(marker_kind, {})
        target_name = marker_def.get("uiName") or marker_kind.replace("_", " ")
        symbol = marker_def.get("symbol")
        display_name = f"{target_name} [{symbol}]" if symbol else target_name
        geometry = " ".join(f"({cell.x},{cell.y})" for cell in cells)
        overlap = len(block_cells.intersection(cells))
        mode = str(raw.get("onLeave", "none"))

        if target_id in consumed:
            if mode == "wall":
                wall_kind = str(raw.get("wallKind", "wall"))
                wall_def = game_def.entity_kinds.get(wall_kind, {})
                wall_name = (
                    wall_def.get("uiName") or wall_kind.replace("_", " ")
                )
                status = (
                    f"completed and converted to {wall_name} after full vacancy"
                )
            elif mode == "void":
                status = "completed and converted to void after full vacancy"
            else:
                status = "completed and removed after full vacancy"
        elif target_id in completed:
            suffix = ""
            if mode == "wall":
                suffix = (
                    f"; becomes a wall only after the {object_name} fully vacates it"
                )
            elif mode == "void":
                suffix = (
                    f"; becomes void only after the {object_name} fully vacates it"
                )
            status = f"completed, still occupied by {object_name}{suffix}"
        else:
            status = f"unfinished ({overlap}/{len(cells)} cells covered)"
        lines.append(f"  {display_name}: cells {geometry}; {status}")

    return "\n".join(lines) if len(lines) > 1 else ""


def _build_numbers_block(
    state: GameState, game_def, concealed_positions: set[Pos]
) -> str:
    entries_list: list[str] = []
    for y in range(state.board.height):
        for x in range(state.board.width):
            pos = Pos(x, y)
            if pos in concealed_positions:
                continue
            for layer_id in _ordered_layers(state):
                entity = state.board.get_entity(layer_id, pos)
                if entity is None:
                    continue
                kind_def = game_def.entity_kinds.get(entity.kind)
                if kind_def is None or kind_def.get("symbolParam") is None:
                    continue
                param_val = entity.params.get(kind_def["symbolParam"])
                if param_val is None:
                    break
                entries_list.append(f"({x},{y})={param_val}")
                break
    if not entries_list:
        return ""
    return "Number values: " + "  ".join(entries_list)


def _build_entity_state_block(
    state: GameState,
    game_def,
    kind_symbol_overrides: dict[str, str] | None,
    concealed_positions: set[Pos],
) -> str:
    """Expose per-entity state that cannot be encoded in one grid symbol."""
    entries: list[str] = []
    for layer_id in _ordered_layers(state):
        layer = state.board.layers.get(layer_id)
        if layer is None:
            continue
        for pos, entity in layer.entries():
            if pos in concealed_positions:
                continue
            if not entity.params:
                continue
            kind_def = game_def.entity_kinds.get(entity.kind, {})
            symbol_param = kind_def.get("symbolParam")
            details = {
                key: value
                for key, value in entity.params.items()
                if key != symbol_param
            }
            if not details:
                continue
            if kind_symbol_overrides is not None:
                name = kind_symbol_overrides.get(entity.kind, "?")
            else:
                name = kind_def.get("uiName") or entity.kind.replace("_", " ")
            rendered = ", ".join(
                f"{key}={value}" for key, value in sorted(details.items())
            )
            entries.append(f"  ({pos.x},{pos.y}) {name}: {rendered}")

    avatar = state.avatar
    if avatar.enabled and avatar.position is not None:
        entries.append(
            f"  ({avatar.position.x},{avatar.position.y}) avatar: "
            f"facing={avatar.facing}"
        )

    if not entries:
        return ""
    return "Entity state:\n" + "\n".join(entries)


def _build_mco_block(state: GameState, game_def, kind_symbol_overrides) -> str:
    if not state.board.multi_cell_objects:
        return ""

    parts: list[str] = ["Multi-cell objects:"]
    public_piece_index = 0
    for mco in state.board.multi_cell_objects:
        kind_def = game_def.entity_kinds.get(mco.kind)
        if kind_symbol_overrides:
            label = "?"
        else:
            label = (kind_def.get("uiName") if kind_def else None) or mco.kind.replace("_", " ")
        if game_def.has_tag(mco.kind, "public_piece"):
            public_piece_index += 1
            piece_name = f"Piece {public_piece_index}"
        else:
            piece_name = mco.id
        parts.append(f"  {piece_name} [{label}]")

        axis = mco.params.get("axis")
        if axis is not None:
            parts.append(f"    axis: {axis}")

        exit_list = mco.params.get("exitPosition")
        exit_pos = Pos(int(exit_list[0]), int(exit_list[1])) if exit_list else None
        exit_dir = mco.params.get("exitDirection")
        exit_tag = f"[exit→{exit_dir}]" if exit_dir else "[exit]"

        cell_strs = []
        for p in mco.cells:
            tag = exit_tag if p == exit_pos else ""
            cell_strs.append(f"({p.x},{p.y}){tag}")
        footprint_label = (
            "footprint"
            if game_def.has_tag(mco.kind, "public_piece")
            else "cells"
        )
        parts.append(f"    {footprint_label}: {' '.join(cell_strs)}")

        spawn_pos: Pos | None = None
        if exit_pos and exit_dir:
            dx, dy = {"right": (1, 0), "left": (-1, 0), "down": (0, 1), "up": (0, -1)}.get(
                exit_dir, (0, 0)
            )
            spawn_pos = Pos(exit_pos.x + dx, exit_pos.y + dy)

        queue = mco.params.get("queue")
        if queue is not None:
            current_index = mco.params.get("currentIndex", 0)
            remaining = queue[current_index:]
            spawn_str = f" (next spawns at ({spawn_pos.x},{spawn_pos.y}))" if spawn_pos else ""
            if remaining:
                queue_str = " → ".join(str(v) for v in remaining)
                parts.append(f"    queue{spawn_str}: {queue_str}")
            else:
                parts.append(f"    queue{spawn_str}: (empty)")

    return "\n".join(parts)
