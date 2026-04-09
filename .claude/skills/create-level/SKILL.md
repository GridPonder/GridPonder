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

Check `tools/solver/games/` for a solver matching this pack. If one exists,
run it after designing the level to verify the gold path is reachable. If no
solver exists for this pack yet, simulate the gold path manually step by step.
(For a new game, consider writing a solver — see the create-game skill.)

A level is accepted when the solver (or manual simulation) confirms:
  - The gold path reaches the goal.
  - No significantly shorter solution exists (a few equivalent move orderings
    are fine; a solution half the length is not).

**Difficulty: design for subgoal decomposition, not BFS resistance**

From level 3 onward, the goal is _not_ "make BFS fail by enlarging the search
space". The goal is to design a level where the correct approach is to identify
good intermediate targets (subgoals) and then work out how to reach each one
without locking out the next. A flat BFS that ignores subgoal structure should
struggle — but a human or AI that reasons about intermediate states should be
able to crack it with genuine insight.

Concretely:
- The level should have at least one **critical ordering constraint**: doing the
  obvious first step in the obvious way blocks a later step. The player must
  realise they need to set up for step B _while_ executing step A.
- Prefer constrained geometry over large open boards. Restricted space forces
  the player to think about order and positioning simultaneously, which is where
  real difficulty comes from.
- Two or three nearly-equivalent movement paths to achieve a subgoal are fine
  (they all require the same insight). Many independent routes to the _goal_ are
  a signal the level is too loose — redesign to close them off.
- After designing, ask: "Could I solve this by trying all move sequences up to
  depth N?" If yes for small N, the level probably lacks a strong subgoal
  structure. Add a constraint that forces the player to commit to an
  intermediate configuration before the final steps become available.

## 4. Design the level

Apply the difficulty curve from the design principles:
- Level 1: introduce the primary mechanic, almost no ambiguity, ≤ 3 moves.
- Level 2: add one complication, ≤ 5 moves.
- Level 3+: combine mechanics for genuine insight, 6–10 moves.

Every level must have an **aha moment** — a non-obvious realisation the player
needs to make. State it explicitly before writing the JSON.

Tightness goals:
- No wasted cells: every tile serves a purpose.
- No cheap escapes: obvious wrong moves should fail instructively.
- Prefer a small number of routes to the goal (not necessarily unique) — many
  independent paths signal the level lacks a strong subgoal structure.

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
