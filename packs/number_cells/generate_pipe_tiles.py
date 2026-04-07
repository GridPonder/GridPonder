#!/usr/bin/env python3
"""
Generate pipe tile PNG assets for GridPonder.

Tiles are drawn at 4× scale then down-sampled to 64×64 with LANCZOS
anti-aliasing.  Each tile is named by its open sides:
  pipe_straight_h  → open left + right
  pipe_straight_v  → open up + down
  pipe_corner_ld   → open left + down
  pipe_corner_rd   → open right + down
  pipe_corner_lu   → open left + up
  pipe_corner_ru   → open right + up
  pipe_end_l       → open left only
  pipe_end_r       → open right only
  pipe_end_u       → open up only
  pipe_end_d       → open down only
  pipe_t_lru       → open left + right + up
  pipe_t_lrd       → open left + right + down
  pipe_t_lud       → open left + up + down
  pipe_t_rud       → open right + up + down
  pipe_cross       → open all four sides

Run from the repo root:
  python3 platform/packs/number_cells/generate_pipe_tiles.py
"""

from PIL import Image, ImageDraw, ImageFilter
import os

OUT_DIR = os.path.join(os.path.dirname(__file__), "assets")
TILE = 64
SCALE = 4
S = TILE * SCALE   # draw-space size: 256
C = S // 2         # centre: 128

# Pipe proportions in draw-space pixels
PO   = 80   # outer half-width  (80/256 ≈ 31 % of tile)
WALL = 16   # border thickness  (16/256 = 4 px at output)
# Channel half-width = PO - WALL = 64 → channel diameter ≈ 32 px at output

# ── Colours ──────────────────────────────────────────────────────────────────
BG     = (0,   0,   0,   0)     # transparent background
BORDER = (195, 140, 45,  255)   # amber/gold outline
FILL   = ( 40,  24,  8,  255)   # dark brown channel interior (white text readable)


# ── Tile builder ──────────────────────────────────────────────────────────────
#
# Strategy: "body mask → erode → paint two colours"
#   1. Draw the pipe body onto a grayscale mask (white = pipe, black = bg).
#      Open sides are overbled by WALL pixels so erosion leaves them flush
#      with the tile edge.  Closed sides are flush so erosion insets by WALL.
#   2. Erode the mask by WALL pixels using MinFilter → channel mask.
#   3. Composite: paint BORDER where body=255, paint FILL where channel=255.
#   4. Downscale 4× with LANCZOS.

def make_tile(name, open_left=False, open_right=False, open_up=False, open_down=False):
    OB = WALL  # overbleed on open faces

    body = Image.new('L', (S, S), 0)
    bd   = ImageDraw.Draw(body)

    # H component (any horizontal arm)
    if open_left or open_right:
        x0 = -OB   if open_left  else C - PO
        x1 = S + OB if open_right else C + PO
        bd.rectangle([x0, C - PO, x1, C + PO], fill=255)

    # V component (any vertical arm)
    if open_up or open_down:
        y0 = -OB   if open_up   else C - PO
        y1 = S + OB if open_down else C + PO
        bd.rectangle([C - PO, y0, C + PO, y1], fill=255)

    # Erode body mask → channel mask
    chan = body.filter(ImageFilter.MinFilter(WALL * 2 + 1))

    # Compose RGBA image
    img    = Image.new('RGBA', (S, S), BG)
    border = Image.new('RGBA', (S, S), BORDER)
    fill   = Image.new('RGBA', (S, S), FILL)
    img.paste(border, mask=body)
    img.paste(fill,   mask=chan)

    # Downscale
    out  = img.resize((TILE, TILE), Image.LANCZOS)
    path = os.path.join(OUT_DIR, f"{name}.png")
    out.save(path)
    print(f"  wrote {path}")


# ── Generate all tiles ───────────────────────────────────────────────────────

if __name__ == '__main__':
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Generating pipe tiles …")

    # Straight
    make_tile('pipe_straight_h', open_left=True, open_right=True)
    make_tile('pipe_straight_v', open_up=True, open_down=True)

    # Corners
    make_tile('pipe_corner_ld', open_left=True, open_down=True)
    make_tile('pipe_corner_rd', open_right=True, open_down=True)
    make_tile('pipe_corner_lu', open_left=True, open_up=True)
    make_tile('pipe_corner_ru', open_right=True, open_up=True)

    # End caps
    make_tile('pipe_end_l', open_left=True)
    make_tile('pipe_end_r', open_right=True)
    make_tile('pipe_end_u', open_up=True)
    make_tile('pipe_end_d', open_down=True)

    # T-junctions
    make_tile('pipe_t_lru', open_left=True, open_right=True, open_up=True)
    make_tile('pipe_t_lrd', open_left=True, open_right=True, open_down=True)
    make_tile('pipe_t_lud', open_left=True, open_up=True, open_down=True)
    make_tile('pipe_t_rud', open_right=True, open_up=True, open_down=True)

    # Cross
    make_tile('pipe_cross', open_left=True, open_right=True, open_up=True, open_down=True)

    print("Done.")
