"""Text renderer — Python port of text_renderer.dart.

Renders a GameState as a compact Unicode grid string.
"""
from __future__ import annotations
from ._models import Board, GameState, Pos
from ._systems import observation_systems

_AVATAR_SYMBOL = "@"
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
    mco_owners: dict[Pos, object] = {}
    for mco in board.multi_cell_objects:
        exit_list = mco.params.get("exitPosition")
        exit_pos = Pos(int(exit_list[0]), int(exit_list[1])) if exit_list else None
        exit_dir = mco.params.get("exitDirection")
        cell_set = set(mco.cells)
        for cell in mco.cells:
            mco_owners[cell] = mco
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
    layer_order = _ordered_layers(state, effective_game)
    systems = observation_systems(
        game_def, level_def.get("systemOverrides") if level_def is not None else None
    )

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
            for layer_id in layer_order:
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
        state, effective_game, concealed_positions, layer_order
    )
    if numbers_block:
        parts.append(numbers_block)

    overlay_block = _build_overlay_block(
        state,
        effective_game,
        kind_symbol_overrides,
        mco_symbols,
        concealed_positions,
        layer_order,
    )
    if overlay_block:
        parts.append(overlay_block)

    stacked_block = _build_stacked_block(
        state,
        effective_game,
        grid_avatar_pos,
        kind_symbol_overrides,
        mco_symbols,
        mco_owners,
        concealed_positions,
        layer_order,
    )
    if stacked_block:
        parts.append(stacked_block)

    entity_state_block = _build_entity_state_block(
        state,
        effective_game,
        kind_symbol_overrides,
        concealed_positions,
        layer_order,
    )
    if entity_state_block:
        parts.append(entity_state_block)

    mco_block = _build_mco_block(state, effective_game, kind_symbol_overrides, systems)
    if mco_block:
        parts.append(mco_block)

    # System-maintained status blocks (named mode only: their text names
    # pack kinds). One block per system, in declaration order.
    if level_def is not None and kind_symbol_overrides is None:
        initial_board = _lazy_initial_board(level_def, effective_game)
        for system in systems:
            lines = system.observation_status_lines(state, effective_game, initial_board)
            if lines:
                parts.append("\n".join(lines))

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
    symbol = kind_def.get("observationSymbol") or kind_def["symbol"]
    return _VISIBLE_SPACE if symbol.isspace() else symbol


def _ordered_layers(state: GameState, game_def) -> list[str]:
    """Return board layers from visually topmost to bottommost.

    The DSL declares layers bottom-to-top. Deriving observation priority from
    that declaration keeps the text grid and stack aligned with the Flutter
    board instead of imposing game-specific layer names.
    """
    declared = [
        layer["id"]
        for layer in game_def.layers
        if layer["id"] in state.board.layers
    ]
    declared_set = set(declared)
    remaining = [
        layer for layer in state.board.layers if layer not in declared_set
    ]
    return list(reversed([*declared, *remaining]))


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

    # Board layer order (not grid priority): a legend entry's text never
    # depends on which layer is scanned first, since shared observation
    # symbols resolve to one board-independent public identity.
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
                sym = kind_def.get("observationSymbol") or kind_def["symbol"]
                if sym.isspace():
                    sym = _VISIBLE_SPACE
                desc = game_def.observation_description(entity.kind)
                name = game_def.observation_name(entity.kind)
                label = f"{name} ({desc})" if desc else name
            if sym in seen or _is_legend_redundant(sym, label):
                continue
            seen[sym] = label

    if state.board.multi_cell_objects:
        # One kind on the board: name it. Several kinds, or anonymous mode:
        # the neutral "multi-cell object".
        labels: list[str] = []
        for mco in state.board.multi_cell_objects:
            label = game_def.observation_name(mco.kind)
            if label not in labels:
                labels.append(label)
        noun = (
            labels[0]
            if len(labels) == 1 and kind_symbol_overrides is None
            else "multi-cell object"
        )
        seen["║/═/╬"] = f"{noun} body"
        if any(
            mco.params.get("exitPosition")
            for mco in state.board.multi_cell_objects
        ):
            seen["▲/▼/◄/►"] = f"{noun} exit (arrow = exit direction)"

    return "  ".join(f"{k}={v}" for k, v in seen.items())


def _build_overlay_block(
    state: GameState,
    game_def,
    kind_symbol_overrides,
    mco_symbols: dict[Pos, str],
    concealed_positions: set[Pos],
    layer_order: list[str],
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
            for layer_id in layer_order:
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
    mco_owners: dict[Pos, object],
    concealed_positions: set[Pos],
    layer_order: list[str],
) -> str:
    """List every visible entity of cells where the grid hides something.

    Entries run top to bottom in grid priority: avatar, non-ground layers
    (declared order reversed), a multi-cell object, then ground. Ground under
    a multi-cell object is its background: it never creates a line on its
    own (a pipe over void is not a stack), but is listed last when the cell
    has a line anyway. Under an ``observation_occluder`` object nothing below
    is listed. Named mode
    prefixes each entry with its layer id; anonymous mode omits it, since
    layer ids are pack vocabulary.
    """
    anonymous = kind_symbol_overrides is not None

    def tagged(layer: str, text: str) -> str:
        return text if anonymous else f"[{layer}] {text}"

    entries_list: list[str] = []
    for y in range(state.board.height):
        for x in range(state.board.width):
            pos = Pos(x, y)
            symbols: list[str] = []
            ground: list[str] = []
            if pos not in concealed_positions:
                for layer_id in layer_order:
                    entity = state.board.get_entity(layer_id, pos)
                    if entity is None:
                        continue
                    kind_def = game_def.entity_kinds.get(entity.kind)
                    if kind_def is None:
                        sym = entity.kind[0].upper()
                        label = "?" if anonymous else entity.kind.replace("_", " ")
                    elif kind_def.get("symbolParam") is not None:
                        param_val = entity.params.get(kind_def["symbolParam"])
                        sym = "N" if param_val is not None else kind_def["symbol"]
                        label = "?" if anonymous else (
                            kind_def.get("uiName") or entity.kind.replace("_", " ")
                        )
                    elif anonymous and entity.kind in kind_symbol_overrides:
                        sym = kind_symbol_overrides[entity.kind]
                        label = "?"
                    else:
                        sym = kind_def.get("observationSymbol") or kind_def["symbol"]
                        if sym.isspace():
                            sym = _VISIBLE_SPACE
                        label = "?" if anonymous else game_def.observation_name(entity.kind)

                    original_sym = game_def.public_symbol(entity.kind) if kind_def else sym
                    if sym == "." or original_sym == ".":
                        continue
                    entry = tagged(layer_id, f"{sym}({label})")
                    (ground if layer_id == "ground" else symbols).append(entry)

            if avatar_pos == pos:
                symbols.insert(0, tagged("avatar", "@(avatar)"))

            mco_symbol = mco_symbols.get(pos)
            if mco_symbol is not None:
                mco = mco_owners[pos]
                label = "?" if anonymous else game_def.observation_name(mco.kind)
                symbols.append(tagged("multi-cell", f"{mco_symbol}({label})"))
                if len(symbols) >= 2:
                    symbols.extend(ground)
            else:
                symbols.extend(ground)

            if len(symbols) >= 2:
                entries_list.append(f"  ({x},{y}): {' + '.join(symbols)}")

    if not entries_list:
        return ""
    return "Stacked cells (grid shows only top symbol):\n" + "\n".join(entries_list)


def _lazy_initial_board(level_def: dict, game_def):
    """Zero-argument callable returning the level's authored board, built
    at most once per render and only if a system asks for it."""
    cache: list = []

    def initial_board():
        if not cache:
            board_json = level_def.get("board")
            cache.append(
                Board.from_json(board_json, game_def.layers)
                if isinstance(board_json, dict)
                else Board(0, 0, {}, [])
            )
        return cache[0]

    return initial_board


def _build_numbers_block(
    state: GameState,
    game_def,
    concealed_positions: set[Pos],
    layer_order: list[str],
) -> str:
    entries_list: list[str] = []
    for y in range(state.board.height):
        for x in range(state.board.width):
            pos = Pos(x, y)
            if pos in concealed_positions:
                continue
            for layer_id in layer_order:
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
    layer_order: list[str],
) -> str:
    """Expose per-entity state that cannot be encoded in one grid symbol."""
    entries: list[str] = []
    for layer_id in layer_order:
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
                name = game_def.observation_name(entity.kind)
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


def _build_mco_block(state: GameState, game_def, kind_symbol_overrides, systems) -> str:
    if not state.board.multi_cell_objects:
        return ""

    parts: list[str] = ["Multi-cell objects:"]
    public_piece_index = 0
    for mco in state.board.multi_cell_objects:
        if kind_symbol_overrides is not None:
            label = "?"
        else:
            label = game_def.observation_name(mco.kind)
        if game_def.has_tag(mco.kind, "public_piece"):
            public_piece_index += 1
            piece_name = f"Piece {public_piece_index}"
        else:
            piece_name = mco.id
        parts.append(f"  {piece_name} [{label}]")

        # Public details owned by the systems that act on this object, in
        # system declaration order; a line repeated by two systems prints once.
        detail_lines: list[str] = []
        for system in systems:
            for line in system.observation_object_lines(mco, state, game_def):
                if line not in detail_lines:
                    detail_lines.append(line)
        parts.extend(f"    {line}" for line in detail_lines)

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
