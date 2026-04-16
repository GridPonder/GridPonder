#!/usr/bin/env python3
"""
Generate box fragment and box target tile PNG assets for box_builder.

box_0.png … box_15.png  — one per 4-bit sides bitmask (U=1 R=2 D=4 L=8)
box_target.png           — landing zone marker

Visual language mirrors the original _BoxFragmentPainter / box_target Container:
  • Fragment body: faint brown rounded-rect fill inside a 10 % margin.
  • Active sides: thick rounded-cap lines along the matching edges.
  • Complete box (15): solid brown fill + small white centre dot.
  • Target: dashed rounded square outline (semi-transparent brown) with margin.

Tiles are drawn at 4× scale (256 × 256) then down-sampled to 64 × 64 with
LANCZOS anti-aliasing.

Run from the repo root:
  python3 platform/packs/box_builder/generate_box_tiles.py
"""

from PIL import Image, ImageDraw, ImageFilter
import os

OUT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "../gridponder-base/sprites/tiles")
)

TILE  = 64
SCALE = 4
S     = TILE * SCALE          # draw-space size: 256

# ── Proportions (mirror the Dart CustomPainter exactly) ───────────────────────
MARGIN   = round(S * 0.10)    # 10 % → 26 px   (inner rect inset)
HALF_SW  = round(S * 0.06)    # half stroke-width (strokeWidth = 12 % → hw = 6 %)
CORNER_R = round(S * 0.08)    # body rounded-corner radius → 21 px
CENTER_R = round(S * 0.12)    # complete-box centre dot radius → 31 px

# ── Colours ───────────────────────────────────────────────────────────────────
BROWN       = (139,  94, 60, 255)   # 0xFF8B5E3C
BROWN_FAINT = (139,  94, 60,  38)   # 15 % opacity body fill (incomplete)

_U = 1; _R = 2; _D = 4; _L = 8


def _rounded_rect(d: ImageDraw.Draw, x0, y0, x1, y1, r, fill) -> None:
    """Filled rounded rectangle, works on Pillow ≥ 8.2 and older alike."""
    try:
        d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill)
    except AttributeError:
        # Pillow < 8.2: approximate with rect + corner circles
        d.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
        d.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
        for cx, cy in [(x0+r, y0+r), (x1-r, y0+r), (x0+r, y1-r), (x1-r, y1-r)]:
            d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=fill)


def _line_h(d: ImageDraw.Draw, x1, x2, y, hw, color=BROWN) -> None:
    """Horizontal rounded-cap line."""
    d.rectangle([x1, y - hw, x2, y + hw], fill=color)
    d.ellipse([x1 - hw, y - hw, x1 + hw, y + hw], fill=color)
    d.ellipse([x2 - hw, y - hw, x2 + hw, y + hw], fill=color)


def _line_v(d: ImageDraw.Draw, x, y1, y2, hw, color=BROWN) -> None:
    """Vertical rounded-cap line."""
    d.rectangle([x - hw, y1, x + hw, y2], fill=color)
    d.ellipse([x - hw, y1 - hw, x + hw, y1 + hw], fill=color)
    d.ellipse([x - hw, y2 - hw, x + hw, y2 + hw], fill=color)


def make_tile(sides: int) -> None:
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)

    full = (sides == 15)
    rx0, ry0, rx1, ry1 = MARGIN, MARGIN, S - MARGIN, S - MARGIN

    # Body fill (rounded rect) — always faint, regardless of completeness
    _rounded_rect(d, rx0, ry0, rx1, ry1, CORNER_R, BROWN_FAINT)

    # Active side walls — lines along the edges of the inner rect
    hw = HALF_SW
    if sides & _U: _line_h(d, rx0, rx1, ry0, hw)
    if sides & _D: _line_h(d, rx0, rx1, ry1, hw)
    if sides & _L: _line_v(d, rx0, ry0, ry1, hw)
    if sides & _R: _line_v(d, rx1, ry0, ry1, hw)

    out  = img.resize((TILE, TILE), Image.LANCZOS)
    path = os.path.join(OUT_DIR, f"box_{sides}.png")
    out.save(path)
    print(f"  wrote {path}")


def make_target_tile() -> None:
    """Mirrors the original Dart box_target Container: semi-transparent brown
    rounded-rect outline with a 15 % margin."""
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)

    m  = round(S * 0.15)        # 15 % margin → 38 px
    bw = round(S * 0.08)        # border width → ~5 px at output (thicker)
    r  = round(S * 0.08)        # corner radius → 21 px
    color = (100, 65, 30, 210)  # darker, more opaque brown

    try:
        d.rounded_rectangle([m, m, S - m, S - m], radius=r, outline=color, width=bw)
    except TypeError:
        # Older Pillow: outline not supported in rounded_rectangle — fall back
        for i in range(bw):
            _rounded_rect(d, m + i, m + i, S - m - i, S - m - i, max(1, r - i),
                          (*color[:3], color[3] // bw))

    out  = img.resize((TILE, TILE), Image.LANCZOS)
    path = os.path.join(OUT_DIR, "box_target.png")
    out.save(path)
    print(f"  wrote {path}")


if __name__ == '__main__':
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Generating box tiles…")
    for sides in range(16):
        make_tile(sides)
    make_target_tile()
    print("Done.")
