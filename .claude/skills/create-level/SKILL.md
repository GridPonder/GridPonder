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

Before starting, read `docs/games/<pack-name>.md` for mechanics reference and
`{base_dir}/../revise-level/level-design-principles.md` for design guidance.

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
use it — starting immediately with `mutate_and_test.py` rather than reasoning
manually about entity placement. If no solver exists yet, simulate the gold
path manually step by step.

### 3a. Start with mutate_and_test.py (when solver exists)

Write a **rough seed JSON** (approximate positions, don't overthink) and run
`mutate_and_test.py --mode astar` immediately as the first action. The mutator
explores hundreds of structurally-valid variants automatically — manual
placement reasoning before this step is wasted effort.

```bash
python3 tools/solver/mutate_and_test.py packs/<pack_id>/levels/<seed>.json \
  --mode astar --max-depth 40 --timeout 180 \
  --criterion solution_length:min=<min>:max=<max> \
  --mc-trials 5000 --criterion mc_difficulty:min=8.0 \
  --candidates 10 --output-dir /tmp/<pack>_variants/
```

**Constraint filters** allow you to bake design requirements into the search
so only candidates that satisfy the intended mechanic pass:

```bash
# Only candidates where breaking a rock is REQUIRED (no solution without it):
--forbid-constraint '{"type":"must_not","event":"object_removed","kind":"rock"}'

# Only candidates where a specific rock MUST be broken:
--forbid-constraint '{"type":"must_not","event":"object_removed","kind":"rock","position":[x,y]}'

# Only candidates where breaking a specific rock is NOT required
# (i.e. a solution still exists even if that rock is forbidden):
--require-constraint '{"type":"must_not","event":"object_removed","kind":"rock","position":[x,y]}'
```

These run extra A* calls per candidate inside the worker, so increase
`--timeout` if the constraint checks are slow.

Pick the most interesting passing candidate as the level basis.

### 3b. Validate the chosen candidate with solve.py

After picking a candidate, confirm it with `solve.py` directly:

- **Short gold paths (≤ 15 moves):** BFS:
  ```
  python3 tools/solver/solve.py packs/<pack_id>/levels/<level_id>.json \
    --mode bfs --max-depth <gold_len + 3>
  ```
- **Longer gold paths (> 15 moves):** A*:
  ```
  python3 tools/solver/solve.py packs/<pack_id>/levels/<level_id>.json \
    --mode astar --max-depth <gold_len + 8> --timeout 120
  ```
  A* reports `OPTIMAL` when it confirms the gold path is globally shortest.
- **Event trace** — add `--trace` to print a step-by-step account of each
  move. Useful for understanding what the solver actually found.

A level is accepted when the solver confirms:
  - The gold path reaches the goal.
  - No significantly shorter solution exists (a few equivalent move orderings
    are fine; a solution half the length is not).

**Measuring difficulty with Monte Carlo:**

After the solver confirms correctness, measure how hard the level is for a
random agent:

```
python3 tools/solver/solve.py packs/<pack_id>/levels/<level_id>.json \
  --mc-trials 10000
```

This runs 10 000 random walks and reports a solve rate and **difficulty in
bits** (`-log2(solve_rate)`). Use this scale to guide level design:

| Bits | Meaning | Suitable for |
|------|---------|--------------|
| < 4  | Trivially easy — random agent often wins | Mechanic-introduction levels |
| 4–8  | Easy/medium | Early levels |
| 8–12 | Hard — random agent rarely wins | Mid/late game |
| > 12 | Very hard — near zero lucky solves | Endgame levels |

Aim for ≥ 8 bits from level 3 onward. If a level that should be hard scores
< 6 bits, the geometry is too open or there are too many routes — constrain it
further (void cells, narrower corridors, forced ordering).

The "avg steps when solved" being much larger than the optimal path length is
normal — the random agent stumbles onto the goal by accident, not by following
the intended path. What matters for design is the bits value and whether the
gold path represents a genuine insight rather than brute-force luck.

**Verifying that key mechanics are essential (constraint checking):**

Constraints let you prove that a specific action is *required* — not just used
in the gold path, but inescapable. Run the solver with a `must_not` constraint;
if the search exhausts the space and finds no solution, the mechanic is proven
necessary. If a solution is still found, the mechanic is optional and the level
design may be too loose.

```
python3 tools/solver/solve.py packs/<pack_id>/levels/<level_id>.json \
  --mode astar --max-depth <N> \
  --constraint '{"type":"must_not","event":"<event_type>", <field>: <value>}'
```

Common constraint patterns for box_builder:

| Goal | Constraint JSON |
|------|----------------|
| Rock at [x,y] must be broken | `{"type":"must_not","event":"object_removed","kind":"rock","position":[x,y]}` |
| Portal at [x,y] must be used | `{"type":"must_not","event":"avatar_entered","position":[x,y]}` |
| Merge must happen at [x,y] | `{"type":"must_not","event":"boxes_merged","position":[x,y]}` |

Multiple `--constraint` flags are AND-ed. The position field matches as a list
or tuple (the solver normalises both). A* with constraints is efficient — the
constraint prunes branches early, so exhausted searches complete quickly even
for deep levels.

Example — bb_016 has two rocks; to verify which is essential:
- `--constraint '{"type":"must_not","event":"object_removed","kind":"rock","position":[2,1]}'`
  → no solution found (258 states) — rock at [2,1] is **essential**
- `--constraint '{"type":"must_not","event":"object_removed","kind":"rock","position":[1,0]}'`
  → 34-move solution still found — rock at [1,0] is **optional**

If a mechanic you intended to be essential turns out to be optional, tighten
the level: remove the bypass route, narrow the corridor, or add a void cell
that forces the player through the intended gate.

**Difficulty: design for subgoal decomposition**

Beyond levels which introduce game mechanics, the goal is _not_ "make BFS fail by
enlarging the search space". The goal is to design a level where the correct approach is to identify
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
- Level 1: introduce the primary mechanic, almost no ambiguity, ≤ 5 moves.
- Level 2: add one complication, ≤ 10 moves.
- Level 3+: combine mechanics for genuine insight, 10-50 moves.

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
- Solver verdict (unique? any shorter solutions? A* optimal confirmed?)
- Monte Carlo difficulty (bits value and what it implies)
- Any open design questions
