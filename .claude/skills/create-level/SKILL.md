---
name: create-level
description: >
  Create a new GridPonder level from scratch. Works for any game pack.
  Reads the game definition to understand entity kinds and mechanics, designs
  a level meeting the stated constraints, writes the JSON file, registers it in
  game.json, and runs the integration test to verify. Use a solver if one
  exists for the game. Arguments: <pack-id> <new-level-id> [design notes]
  e.g. "rotate_flip rf_004 4x4 grid, 8 moves, use all 4 colours".
argument-hint: <pack-id> <new-level-id> [design notes]
---

You are creating a new GridPonder level. Follow these steps.

Before starting, read `{base_dir}/../test-level/game-rules.md` for mechanics
reference and `{base_dir}/../revise-level/level-design-principles.md` for
design guidance.

## 1. Parse arguments

Extract from the arguments:
- `pack_id` — the pack folder name (e.g. `rotate_flip`, `number_cells`)
- `level_id` — the new level's ID (e.g. `rf_004`, `nc_006`)
- Free-text design notes (constraints, target difficulty, mechanics to use)

## 2. Read the game definition

Read `packs/<pack_id>/game.json` to understand:
- Available entity kinds and their symbols
- Actions and systems
- Level sequence (where does the new level fit?)

Also read 1–2 existing levels in the same pack for format reference.

## 3. Use a solver if available

Check `tools/solver/games/` for a solver matching this pack. If one exists:
- For **rotate_flip**: run `python3 tools/solver/gen_rotate_flip.py` to generate
  a configuration meeting the target depth, then verify with
  `python3 tools/solver/solve.py packs/<pack_id>/levels/<level_id>.json`.
- For **number_cells**: run `python3 tools/solver/solve.py` after designing.
- If no solver exists, simulate the gold path manually step by step.

A level is only accepted when the solver (or manual simulation) confirms:
  - The gold path reaches the goal.
  - No shorter solution exists (shortest = declared gold path length).

## 4. Design the level

Apply the difficulty curve from the design principles:
- Level 1: introduce the primary mechanic, almost no ambiguity, ≤ 3 moves.
- Level 2: add one complication, ≤ 5 moves.
- Level 3+: combine mechanics for genuine insight, 6–10 moves.

Every level must have an **aha moment** — a non-obvious realisation the player
needs to make. State it explicitly before writing the JSON.

Tightness goals:
- Prefer a unique shortest solution (or a very small equivalence class).
- No wasted cells: every tile serves a purpose.
- No cheap escapes: obvious wrong moves should fail instructively.

## 5. Write the level JSON

Create `packs/<pack_id>/levels/<level_id>.json` following the exact format
of existing levels. Required fields:

```json
{
  "id": "...",
  "title": "...",
  "board": {
    "size": [cols, rows],
    "layers": { "objects": { "format": "sparse", "entries": [...] } }
  },
  "state": {
    "avatar": { "enabled": true, "position": [x, y], "facing": "right" },
    "overlay": { "position": [x, y], "size": [w, h] }   ← if applicable
  },
  "goals": [{ "id": "match", "type": "board_match", "config": { ... } }],
  "solution": {
    "goldPath": [{ "action": "...", "direction": "..." }, ...],
    "hintStops": [N]   ← midpoint of gold path; omit if path ≤ 2 moves
  }
}
```

## 6. Register in game.json

Add the new level to `packs/<pack_id>/game.json` → `levelSequence`:

```json
{ "type": "level", "ref": "<level_id>" }
```

Insert it in the correct position (after the preceding level).

## 7. Verify with the integration test

Run the integration test:
```bash
cd platform/app && flutter test integration_test/app_test.dart -d macos 2>&1
```

Update `kPackId`, `kLevelId`, and `kMoves` in
`app/integration_test/app_test.dart` first. `kMoves` accepts:
- Direction strings: `'right'`, `'left'`, `'up'`, `'down'`
- Button labels: `'rotate'`, `'flip'`, `'flood'`

Copy screenshots to `app/test/screenshots/` and analyse the final state.
The last screenshot must show **"Level Complete!"**.

## 8. Report

Summarise in 3–5 bullet points:
- The aha moment
- Gold path and length
- Solver verdict (unique? any shorter solutions?)
- Any open design questions
