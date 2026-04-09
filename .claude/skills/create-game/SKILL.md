---
name: create-game
description: >
  Interactive session to design and implement a new GridPonder game pack from
  scratch. Proceeds in three phases: discovery questions, design approval, then
  full implementation (entity kinds, systems, rules, tiles, solver, levels).
  Works for concepts fitting the GridPonder DSL — deterministic, turn-based,
  single-player, perfect-information, 2D grid puzzle. Invoke with a concept
  ("create a sokoban-style game") or blank ("create game").
argument-hint: [game concept or description]
effort: high
---

Read `{base_dir}/../revise-level/level-design-principles.md` and
`{base_dir}/../test-level/game-rules.md` before starting. You will also need
`docs/gridponder_platform_overview.md` and `docs/dsl/` (scan the full folder)
to reason about DSL scope and system availability.

---

## Phase 1 — Concept Discovery

Ask the user the following questions. You may ask them all at once if the
invocation was bare ("create game"), or skip ones that were already answered
in `$ARGUMENTS`.

**Core mechanic questions:**
1. What is the player's primary action? (move, rotate, swap, flood, shoot, …)
2. What is the win condition? (reach a target, match a board pattern, clear all
   tiles, reach a numeric threshold, …)
3. Is there a resource, inventory, or counter the player manages?
4. What is the visual/thematic style? (abstract shapes, nature, machines, …)
5. Roughly how many levels are you aiming for initially?
6. Is this inspired by an existing puzzle game? (useful for scoping, not
   required)

**Scope check** — before moving to Phase 2, verify the concept against the
GridPonder DSL constraints. The DSL covers:

> Deterministic · discrete · single-player · perfect information ·
> turn-based · 2D grid

Flag any of the following as **out of scope**:
- Real-time or timing-based mechanics → not supported
- Multiplayer or adversarial AI → not supported
- 3D, hex, or irregular grids → not supported
- Randomness or hidden information → not supported

If the concept fits entirely → proceed directly to Phase 2.

If the concept requires a **minor DSL extension** (e.g. a new built-in system,
a new goal type, a new effect kind), explain:
- Exactly what would need to be added to the DSL spec
- That a DSL version bump means the pack will only run on engines at that
  version or higher — it will not be immediately shareable with all players
- Ask for explicit confirmation before designing around the extension

If the concept is fundamentally incompatible, propose the closest in-scope
variant and ask if the user wants to pivot to that instead.

---

## Phase 2 — Design Plan

Present a written game design for the user to approve before writing any code.
Structure it as follows:

### 2.1 Pack identity
- Proposed `packId` (snake_case, short, unique among existing packs)
- Display title and one-line description

### 2.2 Entity kinds
List every entity kind the game needs. For each:
- **id** (snake_case), **layer** (ground or objects), **symbol** (one Unicode
  char, unique across the game), **tags** from the DSL tag vocabulary
  (solid, walkable, pushable, pickup, breakable, burnable, liquid, bridge,
  teleport, mergeable, goal_target, npc, target_marker)
- Brief description of its role

Check whether all needed entity behaviours are covered by existing entity tags
and systems before proposing custom rules.

### 2.3 Systems
Identify which of the 10 built-in systems cover the game mechanics:

| System | Phase | When to use |
|---|---|---|
| avatar_navigation | action_resolution | Player movement on ground layer |
| push_objects | movement_resolution | Pushable objects, tool consumption |
| portals | movement_resolution | Teleport between paired cells |
| slide_merge | action_resolution | Sliding tiles that merge on collision |
| queued_emitters | npc_resolution | Multi-cell pipe emitters |
| overlay_cursor | action_resolution | Movable selection region |
| region_transform | action_resolution | Rotate/flip/diagonal-swap a region |
| flood_fill | action_resolution | Flood-fill connected same-kind cells |
| follower_npcs | npc_resolution | Autonomous entity movement |
| sided_box | cascade_resolution | Fragment assembly by side counts |

If none of these cover a mechanic, describe the custom rule (event → condition
→ effect) needed. If a new system type is required, that is a DSL extension
(see Phase 1 scope check).

### 2.4 Rules
List any game-specific rules beyond what the systems provide, using the
event → condition → effect model. Reference the rule recipes in
`docs/dsl/05_rules.md` before writing custom logic.

### 2.5 Controls and theme
- Gesture/button mapping (swipe_cardinal, swipe_diagonal, tap_cell, button)
- Colour palette (primaryColor, backgroundColor)
- Tile style (pixel art, flat, sketch — informs tile-gen prompts)

### 2.6 Level progression plan
Describe the arc of the first N levels:
- Level 1: mechanic introduction (≤ 3 moves, near-zero ambiguity)
- Level 2: add one complication (≤ 5 moves)
- Level 3+: combine mechanics for a genuine aha moment

State the **aha moment** planned for each level beyond level 1.

### 2.7 Solver strategy
State whether you will write a solver for this game (recommended for any game
where state is enumerable and the move space is small). A solver is critical
for ensuring harder levels cannot be cracked by BFS or a simple AI — see the
difficulty guidance in Phase 3 below.

---

**Wait for explicit user approval of the design before proceeding.**
If the user requests changes, revise the relevant section and re-present.

---

## Phase 3 — Implementation

Implement in this order. Use the relevant skills for level creation and testing.

### 3.1 Pack folder scaffold

Create the following files (do not create empty placeholders — write real
content):

```
packs/<packId>/
  manifest.json      ← dslVersion, packVersion, gameId, title, minEngineVersion
  game.json          ← full game definition (layers, actions, entityKinds,
                        systems, rules, levelSequence, defaults)
  theme.json         ← controls gestureMap, colours, boardStyle
  levels/            ← populated in step 3.4
  assets/            ← populated in step 3.3
```

For `manifest.json`, use DSL version `0.5` unless an extension was agreed.
For `game.json`, include a `"ui"` block with `showGoal` and `showGuide` if the
game has a sequence or board-match goal type.

### 3.2 Solver (strongly recommended)

If the game's state is enumerable, write a Python solver following the pattern
in `tools/solver/games/`. The solver should:
- Represent the full board state as a hashable Python object
- Implement `apply_action(state, action) → state | None`
- Expose the state to the BFS engine in `tools/solver/solve.py`

A solver is the primary tool for validating that a level is correctly
designed and not trivially solvable. Commit it to `tools/solver/games/`.

### 3.3 Tiles

Generate sprites for every entity kind using the tile-gen skill:

```bash
python3 tools/tile-gen/generate_tile.py \
  --prompt "<description of tile>" \
  --size 64 \
  --style pixel_art \
  --name <entity_id> \
  --output packs/<packId>/assets/
```

For animated entities (e.g. NPCs, emitters), pass `--count <frames>`.
Inspect each output before registering the sprite path in `game.json`.
Re-generate with a revised prompt if quality is poor.

### 3.4 Levels

Use the **create-level** skill to build each level:

```
/create-level <packId> <levelId> [design notes from Phase 2]
```

**Difficulty and solver validation** — this is the most important constraint:

- For level 1, a trivially short BFS solution is acceptable (it is a pure
  mechanic demo).
- From level 3 onward, a level must NOT be solvable by BFS or a naive AI
  within a small search budget. The intended solution should require a creative
  subgoal or a non-obvious ordering that a general search cannot stumble upon
  cheaply. If the solver finds the gold path too easily, deepen the constraints:
  add a blocking element, tighten the board geometry, or increase the
  move count while closing off shortcuts.
- Every level beyond level 1 must have a stated **aha moment** — a
  non-obvious realisation without which the player cannot make progress.
  The aha moment is what makes the level resistant to brute-force search.

After writing each level, verify with the **test-level** skill:

```
/test-level <levelId>
```

Fix any visual or logic issues before moving to the next level.

### 3.5 Register the pack

Add the pack to the app by verifying the symlink `app/assets/packs →
../../packs` resolves correctly (it is a repo-wide symlink, no action
usually needed).

To make the pack appear in the level selector, confirm `game.json →
levelSequence` lists all created levels in order.

### 3.6 Final checklist

Before declaring the game done:

- [ ] `manifest.json` passes DSL validation (required fields present, version
      correct)
- [ ] Every entity kind in `game.json` has a sprite path that resolves to an
      existing file in `assets/`
- [ ] Every level in `levelSequence` has a corresponding `.json` file in
      `levels/`
- [ ] Every level has a valid `goldPath` confirmed by integration test
      (last screenshot shows "Level Complete!")
- [ ] All levels from level 3 onward resist trivial BFS (solver confirms gold
      path is unique or near-unique at the intended depth)
- [ ] At least one hint stop is placed in each level with a gold path > 2 moves,
      biased toward the early/critical steps
- [ ] Theme colours and gesture map are consistent and tested on device

Report a summary: pack ID, level count, aha moments, any open design questions,
and whether a solver was written.
