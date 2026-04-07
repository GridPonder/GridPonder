---
name: tile-gen
description: >
  Generate game tile or sprite images from a natural language description
  using local AI (SDXL-Turbo + pixel-art LoRA). Runs entirely on-device via
  MPS (Apple Silicon). Single tiles use text2img; animation sequences use
  img2img conditioning so all frames share the same character and palette.
  Arguments: <prompt> [--size N] [--count N] [--style STYLE] [--strength F]
             [--output DIR] [--name NAME]
argument-hint: "<prompt> [--size 64] [--count 1] [--style pixel_art] [--strength 0.75] [--output DIR] [--name tile]"
allowed-tools: Bash, Read
---

You are generating game tile or sprite images using a local AI image model.

## Setup

- Script:  `platform/tools/tile-gen/generate_tile.py`
- Python:  `platform/tools/tile-gen/.venv/bin/python`
- Output:  write to `platform/tools/tile-gen/output/` unless the user specifies otherwise
- Working directory for all commands: `platform/tools/tile-gen/`

## 1. Parse arguments

`$ARGUMENTS` is a free-text request such as:
- `"green grass tile"`
- `"stone wall tile" --style retro --size 64`
- `"rabbit running right" --count 3 --size 96`
- `"explosion effect" --count 4 --style cartoon --size 64`

Extract:
- `prompt`    — the description in quotes (required)
- `--size`    — tile size in pixels, square (default: 64; typical: 32, 64, 96, 128)
- `--count`   — number of frames/tiles (default: 1; use > 1 for animation)
- `--style`   — one of: `pixel_art` (default), `retro`, `cartoon`, `default`
- `--strength`— img2img strength for animation frames (default: 0.75; range 0.5–0.9)
- `--output`  — output directory (default: `output/`)
- `--name`    — base filename without extension (default: `tile`; use something descriptive)

If the user's request is ambiguous, pick sensible defaults rather than asking.
Derive `--name` from the prompt if not given (e.g. "grass tile" → `grass`).

## 2. Run the generator

```bash
cd platform/tools/tile-gen
.venv/bin/python generate_tile.py <prompt> [flags] 2>&1
```

The script prints `[tile-gen] …` progress to stderr and the saved file path(s)
to stdout. A typical run takes:
- ~2 s model load (cached after first run; first-ever run downloads ~6.5 GB)
- ~1–2 s per frame on MPS

If the script fails, report the error and stop.

## 3. Display and report

After the script completes, read each output image with the Read tool and
display it inline so the user can see the results immediately.

Then give a one-line summary per image:
- filename, size, style
- for animation sets: note whether the character looks consistent across frames

## Style guide

| Style      | Best for                              | Notes                        |
|------------|---------------------------------------|------------------------------|
| pixel_art  | environment tiles, sprites (default)  | LoRA active, NEAREST resample|
| retro      | 8-bit look, NES/SNES aesthetic        | LoRA active, NEAREST resample|
| cartoon    | characters, icons, mobile-game feel   | no LoRA, LANCZOS resample    |
| default    | general assets, less opinionated      | no LoRA, LANCZOS resample    |

## Animation notes

When `--count > 1`:
- Frame 1 is generated with text2img (sets the character design)
- Frames 2+ are generated with img2img conditioned on frame 1
- `--strength` controls pose variation vs. character consistency:
  - 0.5–0.6 → nearly identical poses (good for subtle idle animation)
  - 0.7–0.8 → visible pose change while preserving character colours
  - 0.9+    → maximum variation, may drift from original character
- Default of 0.75 is a good starting point for a walk/run cycle
