"""Text renderer — Python port of text_renderer.dart.

Renders a GameState as a compact Unicode grid string.
"""
from __future__ import annotations
from ._models import GameState, Pos

_AVATAR_SYMBOL = "@"
_LAYER_ORDER = ["actors", "markers", "objects", "ground"]


def render(
    state: GameState,
    game_def,
    *,
    include_legend: bool = True,
    kind_symbol_overrides: dict[str, str] | None = None,
) -> str:
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
            for layer_id in _LAYER_ORDER:
                entity = board.get_entity(layer_id, pos)
                if entity is None:
                    continue
                kind_def = game_def.entity_kinds.get(entity.kind)
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
        legend = _build_legend(state, game_def, grid_avatar_pos is not None, kind_symbol_overrides)
        parts.append(f"Each character is one cell, each line is one row. Legend: {legend}")

    numbers_block = _build_numbers_block(state, game_def)
    if numbers_block:
        parts.append(numbers_block)

    overlay_block = _build_overlay_block(state, game_def, kind_symbol_overrides)
    if overlay_block:
        parts.append(overlay_block)

    stacked_block = _build_stacked_block(state, game_def, grid_avatar_pos, kind_symbol_overrides)
    if stacked_block:
        parts.append(stacked_block)

    mco_block = _build_mco_block(state, game_def, kind_symbol_overrides)
    if mco_block:
        parts.append(mco_block)

    return "\n\n".join(parts)


def _get_symbol(entity, kind_def: dict | None, kind_symbol_overrides: dict | None) -> str:
    if kind_def is None:
        return entity.kind[0].upper()
    if kind_def.get("symbolParam") is not None:
        param_val = entity.params.get(kind_def["symbolParam"])
        return "N" if param_val is not None else kind_def["symbol"]
    if kind_symbol_overrides and entity.kind in kind_symbol_overrides:
        return kind_symbol_overrides[entity.kind]
    return kind_def["symbol"]


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


def _build_legend(state: GameState, game_def, has_avatar: bool, kind_symbol_overrides) -> str:
    seen: dict[str, str] = {}
    if has_avatar:
        seen[_AVATAR_SYMBOL] = "avatar (you)"

    for layer in state.board.layers.values():
        for _pos, entity in layer.entries():
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
                desc = kind_def.get("description")
                name = kind_def.get("uiName") or entity.kind.replace("_", " ")
                label = f"{name} ({desc})" if desc else name
            if sym in seen or _is_legend_redundant(sym, label):
                continue
            seen[sym] = label

    if state.board.multi_cell_objects:
        seen["║/═"] = "pipe body"
        seen["▲/▼/◄/►"] = "pipe exit (arrow = exit direction)"

    return "  ".join(f"{k}={v}" for k, v in seen.items())


def _build_overlay_block(state: GameState, game_def, kind_symbol_overrides) -> str:
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
            sym = "."
            for layer_id in _LAYER_ORDER:
                entity = state.board.get_entity(layer_id, Pos(x, y))
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
    state: GameState, game_def, avatar_pos: Pos | None, kind_symbol_overrides
) -> str:
    entries_list: list[str] = []
    for y in range(state.board.height):
        for x in range(state.board.width):
            pos = Pos(x, y)
            symbols: list[str] = []
            for layer_id in _LAYER_ORDER:
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
                    label = kind_def.get("uiName") or entity.kind.replace("_", " ")

                original_sym = kind_def["symbol"] if kind_def else sym
                if sym in (".", " ") or original_sym in (".", " "):
                    continue
                symbols.append(f"{sym}({label})")

            if avatar_pos == pos:
                symbols.insert(0, "@(avatar)")

            if len(symbols) >= 2:
                entries_list.append(f"  ({x},{y}): {' + '.join(symbols)}")

    if not entries_list:
        return ""
    return "Stacked cells (grid shows only top symbol):\n" + "\n".join(entries_list)


def _build_numbers_block(state: GameState, game_def) -> str:
    entries_list: list[str] = []
    for y in range(state.board.height):
        for x in range(state.board.width):
            pos = Pos(x, y)
            for layer_id in _LAYER_ORDER:
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


def _build_mco_block(state: GameState, game_def, kind_symbol_overrides) -> str:
    if not state.board.multi_cell_objects:
        return ""

    parts: list[str] = ["Multi-cell objects:"]
    for mco in state.board.multi_cell_objects:
        kind_def = game_def.entity_kinds.get(mco.kind)
        if kind_symbol_overrides:
            label = "?"
        else:
            label = (kind_def.get("uiName") if kind_def else None) or mco.kind.replace("_", " ")
        parts.append(f"  {mco.id} [{label}]")

        exit_list = mco.params.get("exitPosition")
        exit_pos = Pos(int(exit_list[0]), int(exit_list[1])) if exit_list else None
        exit_dir = mco.params.get("exitDirection")
        exit_tag = f"[exit→{exit_dir}]" if exit_dir else "[exit]"

        cell_strs = []
        for p in mco.cells:
            tag = exit_tag if p == exit_pos else ""
            cell_strs.append(f"({p.x},{p.y}){tag}")
        parts.append(f"    cells: {' '.join(cell_strs)}")

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
