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
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

# Import the engine's Pos so board.get_entity uses the same type.
import sys
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from engines.python._models import Pos as _Pos


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


def render_board_png(game_def: Any, state: Any, pack_dir: str | Path) -> bytes:
    """Render the board to a PNG byte string. State + game_def come from the
    Python engine; pack_dir is the pack root (so sprites can be located)."""
    pack_dir = Path(pack_dir)
    base_dir = pack_dir.parent / "gridponder-base" / "sprites" / "tiles"

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

    # Cells: ground first, then objects/markers/clone on top
    for y in range(height_cells):
        for x in range(width_cells):
            x0 = AXIS_PX + PADDING + x * CELL_PX
            y0 = AXIS_PX + PADDING + y * CELL_PX
            x1, y1 = x0 + CELL_PX, y0 + CELL_PX
            _paint_cell(canvas, draw, game_def, state, x, y, x0, y0, pack_dir, base_dir)
            draw.rectangle((x0, y0, x1, y1), outline=_GRID_LINE, width=1)

    # Region outlines: stroke the perimeter of every contiguous group of
    # cells whose kind has `outline` set in game.json.
    _draw_region_outlines(draw, game_def, state)

    # Avatar overlay (drawn last so always visible).
    avatar = getattr(state, "avatar", None)
    if avatar is not None and getattr(avatar, "enabled", False) and avatar.position is not None:
        ax, ay = avatar.position.x, avatar.position.y
        x0 = AXIS_PX + PADDING + ax * CELL_PX
        y0 = AXIS_PX + PADDING + ay * CELL_PX
        _draw_avatar(canvas, draw, x0, y0, pack_dir, base_dir)

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()


# ── Internal helpers ─────────────────────────────────────────────────────

def _draw_region_outlines(draw, game_def, state):
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
            e = layer.get(_Pos(x, y))
            return e is not None and e.kind == kind_id

        for pos, ent in layer.entries():
            if ent.kind != kind_id:
                continue
            x0 = AXIS_PX + PADDING + pos.x * CELL_PX
            y0 = AXIS_PX + PADDING + pos.y * CELL_PX
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


def _paint_cell(canvas, draw, game_def, state, x, y, x0, y0, pack_dir, base_dir):
    """Paint a single cell: ground → objects → markers → clone (top to bottom)."""
    # Ground
    ground = state.board.get_entity("ground", _Pos(x, y))
    if ground is None:
        # Default empty
        draw.rectangle((x0, y0, x0 + CELL_PX, y0 + CELL_PX), fill=_EMPTY_FILL)
    else:
        kind_def = game_def.entity_kinds.get(ground.kind, {})
        if not _paste_sprite(canvas, ground.kind, kind_def, ground.params, x0, y0, pack_dir, base_dir):
            _procedural_ground(draw, ground.kind, x0, y0)

    # Object / marker / clone layers on top
    for layer in ("objects", "markers", "clone"):
        ent = state.board.get_entity(layer, _Pos(x, y))
        if ent is None:
            continue
        kind_def = game_def.entity_kinds.get(ent.kind, {})
        if not _paste_sprite(canvas, ent.kind, kind_def, ent.params, x0, y0, pack_dir, base_dir):
            _procedural_object(canvas, draw, ent.kind, kind_def, ent.params, x0, y0)


def _paste_sprite(canvas, kind, kind_def, params, x0, y0, pack_dir, base_dir) -> bool:
    """Try to paste a PNG sprite. Returns True on success."""
    sprite_path = kind_def.get("sprite")
    if not sprite_path:
        return False
    fname = os.path.basename(sprite_path)
    # Templated sprites (e.g. box_{sides}.png on box_fragment).
    if "{" in fname and "}" in fname:
        for key in re.findall(r"\{(\w+)\}", fname):
            val = params.get(key)
            if val is None:
                return False
            fname = fname.replace("{" + key + "}", str(val))
    img = _load_sprite(pack_dir, base_dir, fname)
    if img is None:
        return False
    if img.size != (CELL_PX, CELL_PX):
        img = img.resize((CELL_PX, CELL_PX), Image.LANCZOS)
    if img.mode == "RGBA":
        canvas.paste(img, (x0, y0), img)
    else:
        canvas.paste(img, (x0, y0))
    return True


def _procedural_ground(draw, kind, x0, y0):
    if kind == "void":
        draw.rectangle((x0, y0, x0 + CELL_PX, y0 + CELL_PX), fill=_VOID_FILL)
    else:
        draw.rectangle((x0, y0, x0 + CELL_PX, y0 + CELL_PX), fill=_EMPTY_FILL)


def _procedural_object(canvas, draw, kind, kind_def, params, x0, y0):
    """Procedural fallback for objects/markers without a sprite.

    Dispatches on the kind def's optional `display` block first (the
    pack-visible vocabulary). Legacy paths kept only for value-coloured
    numeric tiles whose colour is a function of the value, since that
    can't yet be expressed in the DSL display block.
    """
    cx, cy = x0 + CELL_PX // 2, y0 + CELL_PX // 2

    display = (kind_def or {}).get("display")
    if display and _draw_from_display(draw, display, params, x0, y0, cx, cy):
        return

    # Numbers: HSL-from-value colouring stays procedural.
    if kind.startswith("num_"):
        value = kind[len("num_"):]
        _draw_number_tile(canvas, draw, value, cx, cy, x0, y0)
        return
    if kind == "number":
        value = params.get("value", "?")
        _draw_number_tile(canvas, draw, str(value), cx, cy, x0, y0)
        return

    # Generic fallback: labelled badge (first letter of kind).
    label = kind[:1].upper() if kind else "?"
    font = _font(int(CELL_PX * 0.45))
    draw.ellipse((x0 + 8, y0 + 8, x0 + CELL_PX - 8, y0 + CELL_PX - 8), fill="#94a3b8", outline=(50, 50, 50))
    draw.text((cx, cy), label, fill="white", font=font, anchor="mm")


def _draw_from_display(draw, display, params, x0, y0, cx, cy) -> bool:
    """Render the entity using its kind's `display` block. Returns True on
    success, False when the type is unrecognised (caller falls back)."""
    type_ = display.get("type")
    color = _resolve_display_color(display.get("color"), params)
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
    if type_ == "emoji":
        glyph = display.get("value", "?")
        font = _font(int(CELL_PX * 0.6))
        draw.text((cx, cy), glyph, font=font, anchor="mm")
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


def _resolve_display_color(spec, params):
    """Resolves a `display.color` spec to a hex string. Accepts a palette
    name ('red'), a `@param:<key>` reference that reads from the entity,
    or None (caller picks a default)."""
    if not isinstance(spec, str):
        return None
    if spec.startswith("@param:"):
        key = spec[len("@param:"):]
        v = params.get(key)
        if not isinstance(v, str):
            return None
        return _COLOR_HEX.get(v, "#94a3b8")
    return _COLOR_HEX.get(spec, "#94a3b8")


def _draw_number_tile(canvas, draw, value: str, cx: int, cy: int, x0: int, y0: int):
    """Render a number as a tile with the digit centred."""
    draw.rectangle((x0 + 4, y0 + 4, x0 + CELL_PX - 4, y0 + CELL_PX - 4), fill="#fef3c7", outline=(120, 80, 0), width=1)
    font = _font(int(CELL_PX * 0.55))
    draw.text((cx, cy), value, fill=(60, 30, 0), font=font, anchor="mm")


def _draw_avatar(canvas, draw, x0, y0, pack_dir, base_dir):
    img = _load_sprite(pack_dir, base_dir, "rabbit_idle_facing_player.png")
    if img is not None:
        if img.size != (CELL_PX, CELL_PX):
            img = img.resize((CELL_PX, CELL_PX), Image.LANCZOS)
        if img.mode == "RGBA":
            canvas.paste(img, (x0, y0), img)
        else:
            canvas.paste(img, (x0, y0))
        return
    # Fallback: blue circle with @
    cx, cy = x0 + CELL_PX // 2, y0 + CELL_PX // 2
    draw.ellipse((x0 + 6, y0 + 6, x0 + CELL_PX - 6, y0 + CELL_PX - 6), fill="#3b82f6", outline="white", width=2)
    font = _font(int(CELL_PX * 0.6))
    draw.text((cx, cy), "@", fill="white", font=font, anchor="mm")


@lru_cache(maxsize=256)
def _load_sprite(pack_dir: Path, base_dir: Path, fname: str) -> Image.Image | None:
    for candidate in (pack_dir / "assets" / "sprites" / fname, base_dir / fname):
        if candidate.exists():
            try:
                img = Image.open(candidate)
                img.load()
                return img.convert("RGBA")
            except (OSError, ValueError):
                pass
    return None


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


