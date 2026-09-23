"""
Board image renderer for vision-mode benchmarks.

Renders a GameState as a PNG image using the same sprite assets the Flutter
app uses, with a procedural fallback for entity kinds that don't have a PNG
sprite (color cells, numbers, carrot). Adds coordinate axes (column numbers
along the top, row numbers down the left) so the model can refer to cells
precisely.

Usage:

    from board_image import render_board_png
    png_bytes = render_board_png(game_def, state, pack_dir)

Sprite resolution mirrors Flutter's pack_service.dart: pack-local
`assets/sprites/<name>` first, then `gridponder-base/sprites/tiles/<name>`,
then a procedural fallback. The base directory is auto-detected from the
pack_dir (../gridponder-base/sprites/tiles).
"""
from __future__ import annotations

import io
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFont

# Import the engine's Pos so board.get_entity uses the same type.
import sys
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from engines.python._models import Pos as _Pos
from engines.python.text_renderer import (
    observation_concealed_positions,
    order_layer_ids,
)


CELL_PX = 64
AXIS_PX = 24       # left/top margin for column/row numbers
PADDING = 4        # outer padding

# Procedural color tile palette (matches the visible game palette).
_COLOR_HEX = {
    "red":     "#dc2626",
    "blue":    "#2563eb",
    "green":   "#16a34a",
    "yellow":  "#eab308",
    "orange":  "#f97316",
    "purple":  "#9333ea",
    "teal":    "#0d9488",
    "lime":    "#84cc16",
    "pink":    "#ec4899",
    "cyan":    "#06b6d4",
    "flooded": "#475569",
}

_VOID_FILL = (24, 24, 27)        # near-black for void cells
_EMPTY_FILL = (240, 248, 232)    # very-light green ground
_BG_FILL = (250, 250, 250)       # outer canvas background
_AXIS_TEXT = (90, 90, 90)
_GRID_LINE = (210, 210, 210)


def render_board_png(
    game_def: Any, state: Any, pack_dir: str | Path, level_def: dict | None = None,
) -> bytes:
    """Render the board to a PNG byte string. State + game_def come from the
    Python engine; pack_dir is the pack root (so sprites can be located).
    level_def (optional) applies the level's systemOverrides when deciding
    whether a selected piece is highlighted."""
    return render_board_image(game_def, state, pack_dir, level_def)[0]


def render_board_image(
    game_def: Any, state: Any, pack_dir: str | Path, level_def: dict | None = None,
) -> tuple[bytes, list[str]]:
    """Render the board and say which non-sprite marks the image carries.

    Returns (png_bytes, marks). `marks` lists, in a fixed order, the image
    conventions actually drawn on this board — "selected", "overlay",
    "hidden" — so the prompt can explain exactly the marks the model sees.
    """
    pack_dir = Path(pack_dir)
    base_dir = pack_dir.parent / "gridponder-base" / "sprites" / "tiles"
    theme = _load_theme(pack_dir)
    # Cells under an observation_occluder piece: the text grid shows only the
    # piece there, so the image draws nothing below it either.
    concealed_positions = observation_concealed_positions(state, game_def)
    ctx = _Ctx(game_def, state, pack_dir, base_dir, theme, concealed_positions)

    width_cells = state.board.width
    height_cells = state.board.height
    img_w = AXIS_PX + width_cells * CELL_PX + 2 * PADDING
    img_h = AXIS_PX + height_cells * CELL_PX + 2 * PADDING

    canvas = Image.new("RGB", (img_w, img_h), _BG_FILL)
    draw = ImageDraw.Draw(canvas)

    font_axis = _font(int(AXIS_PX * 0.6))

    # Coordinate axes
    for x in range(width_cells):
        cx = AXIS_PX + PADDING + x * CELL_PX + CELL_PX // 2
        draw.text((cx, PADDING + AXIS_PX // 2), str(x), fill=_AXIS_TEXT, font=font_axis, anchor="mm")
    for y in range(height_cells):
        cy = AXIS_PX + PADDING + y * CELL_PX + CELL_PX // 2
        draw.text((PADDING + AXIS_PX // 2, cy), str(y), fill=_AXIS_TEXT, font=font_axis, anchor="mm")

    marks: list[str] = []
    any_hidden = False
    for y in range(height_cells):
        for x in range(width_cells):
            x0, y0 = _cell_origin(x, y)
            tile, hidden = _cell_tile(ctx, x, y)
            canvas.paste(tile, (x0, y0), tile)
            any_hidden = any_hidden or hidden
            draw.rectangle((x0, y0, x0 + CELL_PX, y0 + CELL_PX), outline=_GRID_LINE, width=1)

    # Region outlines: stroke the perimeter of every contiguous group of
    # cells whose kind has `outline` set in game.json.
    _draw_region_outlines(draw, game_def, state, concealed_positions)

    # The piece the player has selected (individual_actors), as the app's
    # selection ring does.
    selected = _selected_actor_position(game_def, state, level_def)
    if selected is not None:
        sx, sy = _cell_origin(*selected)
        draw.rounded_rectangle(
            (sx + 2, sy + 2, sx + CELL_PX - 2, sy + CELL_PX - 2),
            radius=CELL_PX // 6, outline=_SELECT_RING, width=4,
        )
        marks.append("selected")

    # The overlay cursor (the region selection-based actions operate on).
    overlay = getattr(state, "overlay", None)
    if overlay is not None:
        ox, oy = _cell_origin(overlay.x, overlay.y)
        draw.rounded_rectangle(
            (ox + 1, oy + 1, ox + overlay.width * CELL_PX - 1, oy + overlay.height * CELL_PX - 1),
            radius=4, outline=_OVERLAY_FRAME, width=4,
        )
        marks.append("overlay")

    if any_hidden:
        marks.append("hidden")

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue(), marks


# ── Internal helpers ─────────────────────────────────────────────────────

_SELECT_RING = (255, 212, 90)     # matches the app's selected-actor ring
_OVERLAY_FRAME = (255, 179, 0)    # amber, as the app's overlay cursor
_INSET_PX = 24                    # hidden-item inset size
_HIDDEN_COVER = 0.6               # fraction of an item covered to call it hidden


class _Ctx:
    __slots__ = ("game_def", "state", "pack_dir", "base_dir", "theme", "palette", "raw_kinds",
                 "concealed")

    def __init__(self, game_def, state, pack_dir, base_dir, theme, concealed=frozenset()):
        self.game_def = game_def
        self.concealed = concealed
        self.state = state
        self.pack_dir = pack_dir
        self.base_dir = base_dir
        self.theme = theme
        palette = theme.get("palette") if isinstance(theme, dict) else None
        self.palette = palette if isinstance(palette, dict) else {}
        self.raw_kinds = _load_raw_kinds(pack_dir)


def _cell_origin(x: int, y: int) -> tuple[int, int]:
    return AXIS_PX + PADDING + x * CELL_PX, AXIS_PX + PADDING + y * CELL_PX


def _layer_order(game_def, state) -> list[str]:
    """The board's layers bottom to top (ground first), in the same declared
    order the text grid picks a cell's top item (`order_layer_ids`), so a
    text+image prompt shows the same item on top in both renderings."""
    top_to_bottom = order_layer_ids(list(state.board.layers), game_def)
    return ["ground", *[layer for layer in reversed(top_to_bottom) if layer != "ground"]]


def _layer_default(game_def, layer_id: str):
    for layer in game_def.layers:
        if layer["id"] == layer_id:
            return layer.get("defaultKind", layer.get("default"))
    return None


def _cell_tile(ctx: _Ctx, x: int, y: int) -> tuple[Image.Image, bool]:
    """Composite one cell bottom to top. Returns (tile, drew_hidden_inset).

    Layers are drawn in the text grid's order (see `_layer_order`); multi-cell
    objects sit just above the ground, as the text grid ranks them. An item
    whose visible pixels end up mostly covered by the items above it (e.g. a
    marker under an opaque piece, a special floor under a territory fill) gets
    a small inset in the cell's lower-left corner, since the text grid lists
    it under "Stacked cells" and the image would otherwise drop it.
    """
    game_def, state = ctx.game_def, ctx.state
    pos = _Pos(x, y)
    tile = Image.new("RGBA", (CELL_PX, CELL_PX), (0, 0, 0, 0))

    # (tile, may_be_hidden) bottom to top
    stack: list[tuple[Image.Image, bool]] = []

    if pos in ctx.concealed:
        # Under an observation_occluder piece nothing below is drawn — not
        # even as a hidden-item inset — so a partly transparent piece sprite
        # cannot reveal what the text grid conceals.
        stack.append((_solid(_EMPTY_FILL), False))
        for mco in state.board.multi_cell_objects:
            if pos in mco.cells and game_def.has_tag(mco.kind, "observation_occluder"):
                kind_def = game_def.entity_kinds.get(mco.kind, {})
                stack.append((_entity_tile(ctx, mco.kind, kind_def, mco.params, None), False))
        _stack_avatar(ctx, stack, x, y)
        for item, _ in stack:
            tile.alpha_composite(item)
        return tile, False

    ground = state.board.get_entity("ground", pos)
    if ground is None:
        stack.append((_solid(_EMPTY_FILL), False))
    else:
        kind_def = game_def.entity_kinds.get(ground.kind, {})
        bg = _parse_hex(ctx.theme.get("backgroundColor")) if isinstance(ctx.theme, dict) else None
        ground_tile = _entity_tile(ctx, ground.kind, kind_def, ground.params, "ground", is_ground=True)
        if bg is not None and _has_transparency(ground_tile):
            under = _solid(bg)
            under.alpha_composite(ground_tile)
            ground_tile = under
        stack.append((ground_tile, ground.kind != _layer_default(game_def, "ground")))

    for mco in state.board.multi_cell_objects:
        if not any(cell.x == x and cell.y == y for cell in mco.cells):
            continue
        kind_def = game_def.entity_kinds.get(mco.kind, {})
        stack.append((_entity_tile(ctx, mco.kind, kind_def, mco.params, None), False))

    for layer in _layer_order(game_def, state)[1:]:
        ent = state.board.get_entity(layer, pos)
        if ent is not None:
            stack.append((_layer_tile(ctx, layer, ent), ent.kind != _layer_default(game_def, layer)))

    _stack_avatar(ctx, stack, x, y)

    for item, _ in stack:
        tile.alpha_composite(item)

    hidden = [i for i, (item, may_hide) in enumerate(stack)
              if may_hide and _covered_fraction(item, [t for t, _ in stack[i + 1:]]) >= _HIDDEN_COVER]
    if hidden:
        d = ImageDraw.Draw(tile)
        for n, i in enumerate(hidden[:2]):
            ix0 = 3 + n * (_INSET_PX + 4)
            iy0 = CELL_PX - _INSET_PX - 3
            # The hidden item over what lies beneath it, as it would look
            # with everything above it lifted off, zoomed to the item.
            inset = _solid((255, 255, 255))
            for below, _ in stack[:i + 1]:
                inset.alpha_composite(below)
            inset = inset.crop(_square_bbox(stack[i][0]))
            inset = inset.resize((_INSET_PX, _INSET_PX), Image.LANCZOS)
            tile.paste(inset, (ix0, iy0))
            d.rectangle((ix0 - 2, iy0 - 2, ix0 + _INSET_PX + 1, iy0 + _INSET_PX + 1),
                        outline=(255, 255, 255), width=2)
            d.rectangle((ix0 - 3, iy0 - 3, ix0 + _INSET_PX + 2, iy0 + _INSET_PX + 2),
                        outline=(20, 20, 20), width=1)
    return tile, bool(hidden)


def _stack_avatar(ctx: _Ctx, stack: list, x: int, y: int) -> None:
    avatar = getattr(ctx.state, "avatar", None)
    if (avatar is not None and getattr(avatar, "enabled", False)
            and avatar.position is not None
            and avatar.position.x == x and avatar.position.y == y):
        stack.append((_avatar_tile(ctx, avatar.facing), False))


def _covered_fraction(item: Image.Image, above: list[Image.Image]) -> float:
    """Fraction of `item`'s visible pixels hidden under opaque pixels above."""
    if not above:
        return 0.0
    visible = item.getchannel("A").point(lambda a: 255 if a > 32 else 0)
    total = visible.histogram()[255]
    if total == 0:
        return 0.0
    cover = Image.new("L", item.size, 0)
    for other in above:
        cover = ImageChops.lighter(cover, other.getchannel("A").point(lambda a: 255 if a > 160 else 0))
    both = ImageChops.multiply(visible, cover)
    return both.histogram()[255] / total


def _square_bbox(item: Image.Image) -> tuple[int, int, int, int]:
    """Smallest square (padded a little) around an item's visible pixels."""
    bbox = item.getchannel("A").point(lambda a: 255 if a > 32 else 0).getbbox()
    if bbox is None:
        return (0, 0, CELL_PX, CELL_PX)
    x0, y0, x1, y1 = bbox
    side = min(CELL_PX, max(x1 - x0, y1 - y0) + 6)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    left = max(0, min(CELL_PX - side, cx - side // 2))
    top = max(0, min(CELL_PX - side, cy - side // 2))
    return (left, top, left + side, top + side)


def _has_transparency(img: Image.Image) -> bool:
    return img.getchannel("A").getextrema()[0] < 255


def _solid(rgb) -> Image.Image:
    return Image.new("RGBA", (CELL_PX, CELL_PX), (*rgb, 255))


def _layer_tile(ctx: _Ctx, layer_id: str, ent) -> Image.Image:
    kind_def = ctx.game_def.entity_kinds.get(ent.kind, {})
    item = _entity_tile(ctx, ent.kind, kind_def, ent.params, layer_id)
    raw = ctx.raw_kinds.get(ent.kind) or {}
    display = kind_def.get("display") or {}
    if raw.get("groundBeneath") is True or display.get("groundBeneath") is True:
        default_kind = _layer_default(ctx.game_def, layer_id)
        if default_kind and default_kind != ent.kind:
            under = _entity_tile(ctx, default_kind, ctx.game_def.entity_kinds.get(default_kind, {}), {}, layer_id)
            under.alpha_composite(item)
            item = under
    return item


def _entity_tile(ctx: _Ctx, kind, kind_def, params, layer_id, *, is_ground: bool = False) -> Image.Image:
    """One entity as a transparent CELL_PX tile: its sprite (plus a display
    overlay when `display.overlay` is true), else its `display` block, else a
    labelled badge (or a plain floor fill for ground)."""
    tile = Image.new("RGBA", (CELL_PX, CELL_PX), (0, 0, 0, 0))
    params = params or {}
    display = (kind_def or {}).get("display")
    sprite = _sprite_image(ctx, kind_def or {}, params)
    draw = ImageDraw.Draw(tile)
    cx, cy = CELL_PX // 2, CELL_PX // 2
    if sprite is not None:
        tile.alpha_composite(sprite)
        if display and display.get("overlay") is True:
            _draw_from_display(draw, display, kind, params, 0, 0, cx, cy, ctx)
        return tile
    if display and _draw_from_display(draw, display, kind, params, 0, 0, cx, cy, ctx):
        return tile
    if is_ground:
        _procedural_ground(draw, kind, 0, 0)
        return tile
    _procedural_object(tile, draw, kind, kind_def, params, 0, 0, ctx)
    return tile


def _sprite_image(ctx: _Ctx, kind_def: dict, params: dict) -> Image.Image | None:
    """Resolve a kind's sprite as the app does: a direction-aware idle frame
    from `motion.sprites.idle[<facing>]` when the entity has a facing, else
    the `sprite` path with `{param}` placeholders filled from the entity."""
    sprite_path = kind_def.get("sprite")
    if not sprite_path:
        return None
    facing = params.get("facing")
    motion = kind_def.get("motion") or {}
    idle = (motion.get("sprites") or {}).get("idle") if isinstance(motion, dict) else None
    candidates = []
    if isinstance(facing, str) and isinstance(idle, dict) and isinstance(idle.get(facing), str):
        candidates.append(idle[facing])
    resolved = sprite_path
    ok = True
    if "{" in resolved and "}" in resolved:
        for key in re.findall(r"\{(\w+)\}", resolved):
            val = params.get(key)
            if val is None:
                ok = False
                break
            resolved = resolved.replace("{" + key + "}", str(val))
    if ok:
        candidates.append(resolved)
    for path in candidates:
        img = _load_sprite(ctx.pack_dir, ctx.base_dir, path)
        if img is not None:
            if img.size != (CELL_PX, CELL_PX):
                img = img.resize((CELL_PX, CELL_PX), Image.LANCZOS)
            return img
    return None


def _avatar_tile(ctx: _Ctx, facing) -> Image.Image:
    tile = Image.new("RGBA", (CELL_PX, CELL_PX), (0, 0, 0, 0))
    img = _load_sprite(
        ctx.pack_dir, ctx.base_dir,
        _avatar_sprite(ctx.theme, facing) or "rabbit_idle_facing_player.png",
    )
    if img is not None:
        if img.size != (CELL_PX, CELL_PX):
            img = img.resize((CELL_PX, CELL_PX), Image.LANCZOS)
        tile.alpha_composite(img)
        return tile
    # Fallback: blue circle with @
    draw = ImageDraw.Draw(tile)
    cx, cy = CELL_PX // 2, CELL_PX // 2
    draw.ellipse((6, 6, CELL_PX - 6, CELL_PX - 6), fill="#3b82f6", outline="white", width=2)
    draw.text((cx, cy), "@", fill="white", font=_font(int(CELL_PX * 0.6)), anchor="mm")
    return tile


def _selected_actor_position(game_def, state, level_def) -> tuple[int, int] | None:
    """Cell of the piece the `individual_actors` selection variables point at,
    when that cell still holds the selected kind (as the Selected: status line
    decides). None when the system is off or nothing valid is selected."""
    effective = game_def
    if level_def is not None and hasattr(game_def, "with_system_overrides"):
        effective = game_def.with_system_overrides(level_def.get("systemOverrides"))
    config = None
    for system in getattr(effective, "systems", []) or []:
        if system.get("type") == "individual_actors" and system.get("enabled", True):
            config = system.get("config") or {}
            break
    if config is None:
        return None
    variables = getattr(state, "variables", {}) or {}
    kind = variables.get(config.get("selectedVariable", "selectedActorKind"))
    raw = variables.get(config.get("selectedPositionVariable", "selectedActorPosition"))
    if not kind or not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None
    x, y = int(raw[0]), int(raw[1])
    if not (0 <= x < state.board.width and 0 <= y < state.board.height):
        return None
    ent = state.board.get_entity(config.get("actorLayer", "actors"), _Pos(x, y))
    if ent is None or ent.kind != kind:
        return None
    return x, y


@lru_cache(maxsize=64)
def _load_raw_kinds(pack_dir: Path) -> dict:
    """Raw entityKinds from game.json, for render-only keys the engine's
    parsed kind drops (e.g. top-level `groundBeneath`)."""
    try:
        import json

        data = json.loads((pack_dir / "game.json").read_text())
        kinds = data.get("entityKinds")
        return kinds if isinstance(kinds, dict) else {}
    except (OSError, ValueError):
        return {}


def _draw_region_outlines(draw, game_def, state, concealed_positions):
    """Stroke the outer perimeter of every contiguous region of cells whose
    kind has `outline` set. For each cell in such a region we draw a line on
    each side whose neighbour is NOT in the region; stitched together this
    traces the boundary exactly once. Layer comes from the kind def."""
    for kind_id, kind_def in game_def.entity_kinds.items():
        outline = kind_def.get("outline")
        if not outline:
            continue
        color = _parse_hex(outline.get("color")) or (34, 34, 34)
        width = int(outline.get("width", 2))
        layer_id = kind_def.get("layer", "objects")
        layer = state.board.layers.get(layer_id)
        if layer is None:
            continue

        def in_set(x, y):
            if x < 0 or y < 0:
                return False
            if _Pos(x, y) in concealed_positions:
                return False
            e = layer.get(_Pos(x, y))
            return e is not None and e.kind == kind_id

        for pos, ent in layer.entries():
            if ent.kind != kind_id or pos in concealed_positions:
                continue
            x0, y0 = _cell_origin(pos.x, pos.y)
            x1 = x0 + CELL_PX
            y1 = y0 + CELL_PX
            if not in_set(pos.x, pos.y - 1):
                draw.line([(x0, y0), (x1, y0)], fill=color, width=width)
            if not in_set(pos.x + 1, pos.y):
                draw.line([(x1, y0), (x1, y1)], fill=color, width=width)
            if not in_set(pos.x, pos.y + 1):
                draw.line([(x0, y1), (x1, y1)], fill=color, width=width)
            if not in_set(pos.x - 1, pos.y):
                draw.line([(x0, y0), (x0, y1)], fill=color, width=width)


def _parse_hex(hex_str):
    if not hex_str:
        return None
    s = hex_str.strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def _procedural_ground(draw, kind, x0, y0):
    if kind == "void":
        draw.rectangle((x0, y0, x0 + CELL_PX, y0 + CELL_PX), fill=_VOID_FILL)
    else:
        draw.rectangle((x0, y0, x0 + CELL_PX, y0 + CELL_PX), fill=_EMPTY_FILL)


def _procedural_object(canvas, draw, kind, kind_def, params, x0, y0, ctx=None):
    """Procedural fallback for objects/markers without a sprite.

    Pack-visible vocabulary: every game-specific rendering choice goes
    through the kind def's `display` block. The only fallback below is a
    labelled badge for entities that didn't declare one.
    """
    cx, cy = x0 + CELL_PX // 2, y0 + CELL_PX // 2

    display = (kind_def or {}).get("display")
    if display and _draw_from_display(draw, display, kind, params, x0, y0, cx, cy, ctx):
        return

    # Generic fallback: labelled badge (first letter of kind). Kinds sharing
    # an observationSymbol are badged by their group's public kind, so the
    # image never tells them apart where the text cannot.
    public = kind
    if ctx is not None and kind and hasattr(ctx.game_def, "observation_kind"):
        public = ctx.game_def.observation_kind(kind)
    label = public[:1].upper() if public else "?"
    font = _font(int(CELL_PX * 0.45))
    draw.ellipse((x0 + 8, y0 + 8, x0 + CELL_PX - 8, y0 + CELL_PX - 8), fill="#94a3b8", outline=(50, 50, 50))
    draw.text((cx, cy), label, fill="white", font=font, anchor="mm")


def _draw_from_display(draw, display, kind, params, x0, y0, cx, cy, ctx=None) -> bool:
    """Render the entity using its kind's `display` block. Returns True on
    success, False when the type is unrecognised (caller falls back).
    Colour names resolve through the pack's theme.json `palette` first, as
    the app's cellNamedColor does."""
    type_ = display.get("type")
    color = _resolve_display_color(display.get("color"), kind, params, ctx)
    if type_ == "none":
        return True
    if type_ == "tile":
        fill = color or "#94a3b8"
        draw.rectangle((x0 + 4, y0 + 4, x0 + CELL_PX - 4, y0 + CELL_PX - 4),
                       fill=fill, outline=(50, 50, 50), width=1)
        return True
    if type_ == "fill":
        draw.rectangle((x0, y0, x0 + CELL_PX, y0 + CELL_PX),
                       fill=color or "#94a3b8")
        return True
    if type_ == "circle":
        c = color or "#16a34a"
        m = CELL_PX // 4
        draw.ellipse((x0 + m, y0 + m, x0 + CELL_PX - m, y0 + CELL_PX - m),
                     fill=c, outline=(50, 50, 50))
        return True
    if type_ == "ring":
        c = color or "#16a34a"
        m = CELL_PX // 8
        draw.ellipse((x0 + m, y0 + m, x0 + CELL_PX - m, y0 + CELL_PX - m),
                     fill=(20, 20, 20), outline=c, width=max(2, CELL_PX // 10))
        return True
    if type_ == "filled_circle":
        c = color or "#16a34a"
        if display.get("overlay") is not True:
            bg = _resolve_display_color(display.get("bgColor"), kind, params, ctx)
            if bg:
                draw.rectangle((x0, y0, x0 + CELL_PX, y0 + CELL_PX), fill=bg)
        m = int(CELL_PX * 0.24)
        draw.ellipse((x0 + m, y0 + m, x0 + CELL_PX - m, y0 + CELL_PX - m), fill=c)
        return True
    if type_ == "circle_label":
        c = color or "#16a34a"
        text = _resolve_display_string(display.get("label"), kind, params, ctx) or ""
        if display.get("overlay") is True:
            r = int(CELL_PX * 0.23)
            bx, by = x0 + CELL_PX - r - 3, y0 + CELL_PX - r - 3
            draw.ellipse((bx - r, by - r, bx + r, by + r), fill=(20, 20, 20), outline=c, width=2)
            if text:
                draw.text((bx, by), text, fill="white", font=_font(int(CELL_PX * 0.26)), anchor="mm")
            return True
        m = int(CELL_PX * 0.14)
        draw.ellipse((x0 + m, y0 + m, x0 + CELL_PX - m, y0 + CELL_PX - m), fill=c)
        if text:
            draw.text((cx, cy), text, fill="white", font=_font(int(CELL_PX * 0.36)), anchor="mm")
        return True
    if type_ == "label":
        text = _resolve_display_string(display.get("label"), kind, params, ctx) or "?"
        fill = color or "#fef3c7"
        draw.rectangle((x0 + 4, y0 + 4, x0 + CELL_PX - 4, y0 + CELL_PX - 4),
                       fill=fill, outline=(60, 30, 0), width=1)
        font = _font(int(CELL_PX * 0.55))
        # White text on saturated colours, dark text on the default cream.
        text_fill = "white" if color else (60, 30, 0)
        draw.text((cx, cy), text, fill=text_fill, font=font, anchor="mm")
        return True
    if type_ == "emoji":
        glyph = display.get("value", "?")
        font = _font(int(CELL_PX * 0.6))
        draw.text((cx, cy), glyph, font=font, anchor="mm", fill=(30, 30, 30))
        return True
    if type_ == "emoji_label":
        glyph = display.get("emoji", "")
        text = _resolve_display_string(display.get("label"), kind, params, ctx) or ""
        draw.text((cx, cy - CELL_PX // 8), glyph, font=_font(int(CELL_PX * 0.45)), anchor="mm", fill=(30, 30, 30))
        if text:
            draw.text((cx, cy + CELL_PX // 4), text, font=_font(int(CELL_PX * 0.23)), anchor="mm",
                      fill="white", stroke_width=2, stroke_fill=(20, 20, 20))
        return True
    if type_ == "icon":
        # Material icons aren't available to PIL; fall back to a labelled
        # badge using the icon name's first letter (uppercase).
        name = display.get("value", "?")
        label = name[:1].upper()
        font = _font(int(CELL_PX * 0.45))
        draw.ellipse((x0 + 8, y0 + 8, x0 + CELL_PX - 8, y0 + CELL_PX - 8),
                     fill=color or "#94a3b8", outline=(50, 50, 50))
        draw.text((cx, cy), label, fill="white", font=font, anchor="mm")
        return True
    return False


def _named_color(name: str, ctx=None) -> str:
    """Palette name → hex: the pack theme's `palette` first, then the built-in
    names, then neutral grey."""
    palette = ctx.palette if ctx is not None else {}
    value = palette.get(name)
    if isinstance(value, str) and _parse_hex(value) is not None:
        return "#" + value.strip().lstrip("#")
    return _COLOR_HEX.get(name, "#94a3b8")


def _resolve_display_color(spec, kind, params, ctx=None):
    """Resolves a `display.color` spec to a hex string. Tokens:
       - `@param:<key>`        — read colour name from instance param
       - `@hue:<source>`       — derive HSL colour from a numeric string
                                 (`<source>` is itself a string spec)
       - bare string           — palette lookup (theme palette first)
    Returns None when the spec can't resolve."""
    if not isinstance(spec, str):
        return None
    if spec.startswith("@hue:"):
        source = _resolve_display_string(spec[len("@hue:"):], kind, params, ctx)
        try:
            n = int(source) if source is not None else None
        except (TypeError, ValueError):
            n = None
        return _hue_color(n) if n is not None else None
    if spec.startswith("@param:"):
        v = params.get(spec[len("@param:"):])
        if not isinstance(v, str):
            return None
        return _named_color(v, ctx)
    return _named_color(spec, ctx)


def _resolve_display_string(spec, kind, params, ctx=None):
    """Resolves a string spec inside `display` (label text, source of @hue, …).
    Tokens: `@param:<key>`, `@kind_suffix:<prefix>`, `@variable:<key>`,
    otherwise literal."""
    if not isinstance(spec, str):
        return None
    if spec.startswith("@param:"):
        v = params.get(spec[len("@param:"):])
        return None if v is None else str(v)
    if spec.startswith("@kind_suffix:"):
        prefix = spec[len("@kind_suffix:"):]
        return kind[len(prefix):] if kind.startswith(prefix) else None
    if spec.startswith("@variable:"):
        variables = getattr(ctx.state, "variables", {}) if ctx is not None else {}
        v = variables.get(spec[len("@variable:"):])
        return None if v is None else str(v)
    return spec


def _hue_color(value: int) -> str:
    """Mirrors Dart's _numberColor: HSL hue = (value*37) mod 360,
    saturation 0.6, lightness 0.45. Returns a #RRGGBB string."""
    import colorsys
    h = ((value * 37) % 360) / 360.0
    r, g, b = colorsys.hls_to_rgb(h, 0.45, 0.6)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


@lru_cache(maxsize=256)
def _load_sprite(pack_dir: Path, base_dir: Path, fname: str) -> Image.Image | None:
    relative = Path(fname)
    candidates = (
        pack_dir / relative,
        pack_dir / "assets" / "sprites" / relative.name,
        base_dir / relative.name,
    )
    for candidate in candidates:
        if candidate.exists():
            try:
                img = Image.open(candidate)
                img.load()
                return img.convert("RGBA")
            except (OSError, ValueError):
                pass
    return None


@lru_cache(maxsize=64)
def _load_theme(pack_dir: Path) -> dict:
    try:
        import json

        return json.loads((pack_dir / "theme.json").read_text())
    except (OSError, ValueError):
        return {}


def _avatar_sprite(theme: dict, facing: str) -> str | None:
    avatar = theme.get("avatar") or {}
    idle = (avatar.get("sprites") or {}).get("idle") or {}
    value = idle.get(facing)
    if isinstance(value, str):
        return value
    sprite = avatar.get("sprite")
    return sprite if isinstance(sprite, str) else None


@lru_cache(maxsize=8)
def _font(size: int) -> ImageFont.ImageFont:
    """Best-effort sans font; fall back to PIL default if no system font found."""
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default()
