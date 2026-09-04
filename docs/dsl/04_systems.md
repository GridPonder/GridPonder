# Gridponder DSL — System Catalog

The built-in engine systems, their execution order, and the per-system configuration reference.

## 1. System Architecture

### Execution Phases

Each system declares which phase(s) it participates in. During a turn, phases execute in this fixed order:

| # | Phase | Purpose |
|---|-------|---------|
| 1 | `input_validation` | Engine validates action legality. No system runs here — this is engine-internal. |
| 2 | `action_resolution` | Primary action executes (avatar moves, tiles slide, overlay shifts, etc.). |
| 3 | `movement_resolution` | Secondary movement triggered by the primary action (pushing, teleporting). |
| 4 | `interaction_resolution` | Reserved for future systems. In v0.5, item/environment interactions are handled by rules in phase 5. |
| 5 | `cascade_resolution` | Chain effects: rules evaluate, emitters fire, gravity settles. Repeats up to `maxCascadeDepth`. |
| 6 | `npc_resolution` | Autonomous NPC behavior executes. |
| 7 | `goal_evaluation` | Win and lose conditions are checked. |

### Events

Systems emit **events** as they modify state. Events accumulate during phases 2–4 and are consumed by rules during phase 5. See [05_rules.md](05_rules.md) for the full event catalog.

### Interaction Protocol

Systems interact through:
1. **Shared state** — all systems read/write the board, avatar, and variables. Phase ordering determines visibility.
2. **Events** — systems emit events; rules (and some systems) react to them.
3. **Phase ordering** — a phase-3 system always sees state changes from phase 2.

Systems never call each other directly.

### Config Override

Levels may override specific config fields per system via `systemOverrides`. Overrides are shallow-merged onto the game-level config.

---

## 2. System Catalog

### 2.1 `avatar_navigation`

**Purpose:** Move the avatar one step per `move` action. Enforce boundaries and solid collisions.

**Phase:** `action_resolution`

**Events emitted:** `avatar_entered`, `avatar_exited`, `move_blocked`

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `directions` | array of strings | `["up","down","left","right"]` | Allowed movement directions. |
| `solidHandling` | string | `"block"` | What happens when moving into a solid cell: `"block"` (reject move) or `"delegate"` (let later systems handle, e.g. push or consume). |
| `solidLayers` | array of strings | `["objects"]` | Layers checked for a `solid` blocker, in order; the first match wins. Packs that place blockers elsewhere — NPCs on `actors`, for instance — have to list that layer explicitly. |
| `moveAction` | string | `"move"` | Which action id triggers navigation. |
| `validGroundTags` | array of strings | `[]` | When non-empty, the target's ground cell must carry one of these tags. Empty keeps the void-only check, so packs that omit the field are unaffected. |
| `groundLayer` | string | `"ground"` | Layer checked by `validGroundTags`. |
| `faceOnBlockedMove` | boolean | `false` | Turn `avatar.facing` to the attempted direction even when the step is refused. Off by default for a reason beyond compatibility: `facing` is part of state identity, so a blocked move stops being a no-op and becomes a fresh search node — solvers expand what used to collapse, and the benchmark harness's repeated-state detector no longer recognises an agent bouncing off a wall. Turn it on only where leaning on an obstacle is a real move. |

**Behavior:**
1. Compute target position from direction.
2. Check bounds — reject if out of grid.
3. Check ground layer — reject if `void`.
4. If `validGroundTags` is non-empty, reject unless the `groundLayer` cell at the target carries one of those tags. This is how a game makes some non-void terrain unwalkable — landed debris, deep water, a roof you may stand beside but not on.
5. Check the `solid` tag on each layer in `solidLayers`, in order:
   - `"block"`: reject move.
   - `"delegate"`: mark the move as pending. Emit `move_blocked` with the target position and blocker kind. Later phases (push) or rules (`resolve_move` effect) may complete or reject the pending move.
6. If not blocked, move avatar to target. Emit `avatar_exited` for old position, `avatar_entered` for new position.
7. Update `avatar.facing` to the movement direction. With `faceOnBlockedMove`
   the turn also happens on a move that never lands, since a blocked move still
   spends the turn and turning is the only feedback that anything happened —
   at the cost described in the field's row above.

---

### 2.2 `push_objects`

**Purpose:** Allow the avatar to push configured objects into adjacent empty cells.

**Phase:** `movement_resolution`

**Events emitted:** `object_pushed`, `object_placed`, `avatar_entered`, `avatar_exited`

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `pushableTags` | array of strings | `["pushable"]` | Tags identifying pushable entities. |
| `validTargetTags` | array of strings | `["walkable"]` | Tags the destination ground must have. Also allows `null` (empty objects layer) cells. |
| `chainPush` | boolean | `false` | Whether pushing into another pushable triggers a chain push. |
| `blockingLayers` | array of strings | `[]` | Layers **besides `objects`** that stop a push, checked at both the push and chain destinations. Empty keeps the old behaviour, where only the objects and ground layers were consulted and a pushable travelled straight through an NPC on `actors`. Listing `objects` has no effect: the push logic owns that layer, including chain-push semantics a generic check would break. |
| `blockingTags` | array of strings | `["solid"]` | Tags that block a push on `blockingLayers`. Empty means any entity on those layers blocks. |
| `toolInteractions` | array | `[]` | List of item-based destruction interactions. Each entry: `{ "item": "<kind>", "targetTag": "<tag>", "consumeItem": false, "animation": "<name>" }`. When the avatar holds the specified item and moves into an entity with the specified tag, the entity is destroyed and the avatar enters the vacated cell. `consumeItem` (default `false`) controls whether the item is removed from inventory. `animation` (optional) names an animation defined on the target entity kind to play before removal. Applies before pushable logic — works on any solid entity, not just pushable ones. |

**Behavior:**
1. When avatar movement targets a cell with an entity in the objects layer:
   a. Check `toolInteractions` in order. If any interaction matches (avatar holds the required item, entity has the required tag), destroy entity, optionally consume item, play animation if configured, move avatar. Skip remaining push logic.
   b. If entity is not pushable, movement fails.
   c. Compute push destination (one cell further in movement direction).
   d. Check push destination: must be in bounds, ground must have a `validTargetTags` tag, no `blockingTags` match on any `blockingLayers` layer, and the objects layer must be empty (or have a matching tag if `chainPush`, in which case the chain destination is checked the same way).
   e. If valid: move pushed object, then move avatar into vacated cell.
   f. If invalid: movement fails, avatar stays.
2. Emit `object_pushed`, `object_placed` for pushed object; standard avatar events.

---

### 2.3 `sliding_blocks`

**Purpose:** Move rigid `multiCellObjects` directly, one cell at a time, using a `move` action that carries both a start `position` and a `direction`.

**Phase:** `action_resolution`

**Events emitted:** `multi_cell_object_moved`, `multi_cell_object_exited`,
`variable_changed` (only when an object exits)

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `moveAction` | string | `"move"` | Action id that triggers block movement. |
| `groundLayer` | string | `"ground"` | Layer checked for valid destination and exit cells. |
| `validGroundTags` | array of strings | `["walkable"]` | Tags required on the ground cell for every destination cell that remains on the board. |
| `blockingLayers` | array of strings | `["objects"]` | Ordinary board layers that can block a sliding object. |
| `blockingTags` | array of strings | `["solid"]` | Tags that block movement on `blockingLayers`. Empty means any entity on those layers blocks. |
| `coverableTags` | array of strings | `[]` | Blocking entity tags that ordinary sliding objects may overlap, for example a floor hatch or pressure plate that remains present under a block. |
| `coverableBlockedRoles` | array of strings | `[]` | Object roles that must still treat `coverableTags` as blocking. This lets scenery cover a tagged cell without allowing a protected role to enter it. |
| `escapeRoles` | array of strings | `[]` | Multi-cell object roles allowed to leave the board through an exit edge. |
| `exitTags` | array of strings | `["exit"]` | Ground tags that permit a configured escape role to leave the board. |
| `escapedVariable` | string | `"escapedCount"` | Variable incremented when a multi-cell object exits. |

**Multi-cell object params:**

| Field | Type | Description |
|-------|------|-------------|
| `axis` | string | `"horizontal"`, `"vertical"`, `"both"`, or any other value to make the object immovable. |
| `role` | string | Semantic role used by `escapeRoles`, `coverableBlockedRoles`, and other systems. |

**Presentation convention:** Give directly manipulated multi-cell entity kinds
the semantic tag `sliding_block`. UI clients may use this tag to render those
objects above ordinary cell layers and to show selection feedback. The engine
does not require the tag; movement is determined by the action and object
params above.

**Behavior:**
1. Read the action's `position` and find the `multiCellObject` occupying that cell.
2. Reject the action if no block is found or if the block's `axis` does not allow the requested `direction`.
3. Compute the block's translated cells one step in that direction.
4. Reject the action if any translated cell collides with another multi-cell object, a new blocking entity, void, out-of-bounds space, or invalid ground. Rejected actions leave the board, variables, counters, and undo history unchanged. A block may continue to overlap a blocking entity that was already under one of its old cells. It may enter a blocking entity tagged by `coverableTags` only when its role is not listed in `coverableBlockedRoles`.
5. If the translated cells leave the board, allow the move only when the block's `role` is listed in `escapeRoles` and its leading edge is currently on a ground cell tagged by `exitTags`. Remove the object, increment `escapedVariable`, and emit `multi_cell_object_exited`.
6. Otherwise, replace the block's cell list with the translated cell list and preserve each cell's optional sprite mapping.

The system does not contain collection, visibility, inventory, or door logic.
Compose it with [`line_of_sight`](#213-line_of_sight) and ordinary rules when
those mechanics are needed.

**Gesture convention:** UI clients should map a drag start cell to `position` and the drag direction to `direction`. There is no separate engine-level selection state.

---

### 2.4 `portals`

**Purpose:** Teleport avatar (or objects) between paired portal entities.

**Phase:** `movement_resolution`

**Events emitted:** `avatar_entered`, `avatar_exited`

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `teleportTags` | array of strings | `["teleport"]` | Tags identifying portal entities. |
| `matchKey` | string | `"channel"` | Entity parameter used to match portal pairs. |
| `endMovement` | boolean | `true` | Whether teleport ends the move (avatar lands on exit portal). |
| `teleportObjects` | boolean | `false` | Whether pushed objects can also teleport through portals. |
| `actorLayer` | string | — | When set, actors on this layer are also teleported on `actor_entered` events. |
| `actorPositionVariable` | string | — | Runtime variable updated to the actor's new position after teleport. |
| `trailClearing` | array | `[]` | Per-actor-kind trail clearing on teleport. Each entry: `{ "actorKind": "<kind>", "trailLayer": "<layer>", "trailKind": "<kind>", "restoreKind": "<kind>", "budgetVariable": "<var>" }`. When an actor of `actorKind` teleports, all tiles of `trailKind` on `trailLayer` are replaced with `restoreKind` (or removed if omitted) and the count of cleared tiles is added to `budgetVariable`. Use this for snake-like games where body trail should disappear on portal entry and the snake's length budget is restored. |
| `clearTrailAtPortalCells` | boolean | `false` | When `true` and `trailClearing` is configured, each cascade pass erases any trail tile found on a portal cell (without restoring budget). This keeps portal cells permanently traversable — neither the entering snake's step-off trail nor a previous snake's trail can block them. Enables bidirectional, multi-snake reuse of the same portal pair. |

**Behavior:**
1. When avatar enters a cell with a `teleportTags` entity:
   a. Read `matchKey` parameter (e.g., `channel: "blue"`).
   b. Find the paired portal with the same value.
   c. Move avatar to paired portal position.
   d. If `endMovement`: turn continues from portal position. If `false`: avatar continues moving in original direction.
2. If `teleportObjects` and an object is pushed onto a portal: teleport object similarly.
3. If `actorLayer` is set, actors on that layer that receive an `actor_entered` event at a portal cell are teleported to the matching exit portal. After relocation, `trailClearing` is applied: for each matching entry, all tiles of `trailKind` on `trailLayer` are cleared to `restoreKind` and the cleared count is added to `budgetVariable`. This makes a snake's body vanish when it enters a portal and restores the full length budget to spend as it exits.
4. If `clearTrailAtPortalCells` is `true`, each cascade pass additionally scans all portal cells and removes any trail tile from the configured `trailClearing` layers. The normal move budget cost for stepping off the portal still applies; only the trail tile is suppressed. This ensures portals remain open for re-entry regardless of how many actors have passed through them.

---

### 2.5 `slide_merge`

**Purpose:** Slide all mergeable tiles in the swipe direction; merge matching tiles.

**Phase:** `action_resolution`

**Events emitted:** `tiles_slid`, `tiles_merged`, `cell_cleared`

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mergeableTags` | array of strings | `["mergeable"]` | Tags identifying slideable/mergeable entities. |
| `mergeAction` | string | `"move"` | Which action id triggers sliding. |
| `mergePredicate` | string | `"equal_value"` | When two tiles merge: `"equal_value"` (same `value` param). |
| `mergeResult` | string | `"sum"` | Result of merge: `"sum"` or `"double"`. |
| `mergeLimit` | integer | `1` | Max merges per tile per action. |
| `blockerTags` | array of strings | `["solid"]` | Tags that stop sliding. |
| `wrapAround` | boolean | `false` | Whether tiles wrap around the board. |

**Behavior:**
1. On action, determine slide direction from action params.
2. Process rows/columns in slide direction order.
3. Each mergeable tile slides until hitting a boundary, blocker, void, or another tile.
4. If tile meets another tile with matching `mergePredicate`: merge. New tile has `mergeResult` value.
5. Each tile can merge at most `mergeLimit` times per action.
6. Emit events for each slide and merge.

---

### 2.6 `queued_emitters`

**Purpose:** Release one item per turn from each multi-cell emitter whose exit cell is empty.

**Phase:** `npc_resolution` (runs once per turn, after all slides and cascades have settled)

**Events emitted:** `item_released`

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `emitterKind` | string | `"pipe"` | Multi-cell object kind that acts as an emitter. |

**Behavior — unidirectional pipe** (no `exit2Position`):
1. Check whether the exit cell (`exitPosition`) and the spawn cell (one step in `exitDirection`) are both empty.
2. If both empty and the queue has remaining items: spawn the next item at the spawn cell, increment `currentIndex`, emit `item_released`.
3. Only one item is released per emitter per turn.

**Behavior — bidirectional pipe** (`exit2Position` present):

A bidirectional pipe has two open exits. Numbers occupy physical **slots** (cells) within the pipe. Initially, `queue[0]` is placed in cell 0 (the exit-1 cell), `queue[1]` in cell 1, and so on. The runtime state is stored in `pipeSlots` — an array of length `pipe_length` (one entry per cell, each `int | null`).

Each turn the pipe runs two phases:

1. **Emit phase:** For each exit, if an item occupies the exit cell and the exit's spawn cell is clear, emit it (place it on the board, set the slot to `null`). Both exits can emit simultaneously.

2. **Move phase:** Each remaining item moves **one step** toward its nearest exit:
   - Distance to exit 1 = cell index; distance to exit 2 = `(pipe_length - 1) - cell index`.
   - Closer to exit 1 → shift one cell toward exit 1 (index − 1).
   - Closer to exit 2 → shift one cell toward exit 2 (index + 1).
   - **Equidistant** (midpoint of an odd-length pipe):
     - If only exit 1 is clear → move toward exit 1.
     - If only exit 2 is clear → move toward exit 2.
     - If **both** clear or both blocked → **stuck**: no movement this turn.
   - An item arriving at an exit cell does **not** emit on the same turn — it exits on the next turn's emit phase.

**Even vs. odd pipe length:** In an even-length pipe every cell has a strictly nearer exit, so the stuck condition never arises. It is exclusive to odd-length pipes.

---

### 2.7 `overlay_cursor`

**Purpose:** Maintain a movable overlay region that `region_transform` operates on.

**Phase:** `action_resolution`

**Events emitted:** `overlay_moved`

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `size` | `[w, h]` | `[2, 2]` | Overlay dimensions. |
| `moveAction` | string | `"move"` | Action id that moves the overlay. |
| `anchorToAvatar` | boolean | `false` | If `true`, the overlay follows the avatar position. Avatar position = top-left (for 2x2) or center (for 3x3). |
| `boundsConstrained` | boolean | `true` | Whether the overlay must stay fully within the board. |

**Behavior:**
1. On `moveAction`, shift overlay position in the action's direction.
2. If `boundsConstrained`, clamp to board boundaries.
3. If `anchorToAvatar`, overlay tracks avatar position automatically.
4. Update `state.overlay.position`.
5. Emit `overlay_moved`.

---

### 2.8 `region_transform`

**Purpose:** Apply spatial transformations (rotate, flip, diagonal swap) to cell contents within the overlay region.

**Phase:** `action_resolution`

**Events emitted:** `region_rotated`, `region_flipped`, `cells_swapped`

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `overlaySystemId` | string | — | Id of the `overlay_cursor` system providing the region. |
| `affectedLayers` | array of strings | `["objects"]` | Which layers are transformed. |
| `operations` | object | `{}` | Map of operation name → operation config. |

Each operation:

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | `"rotate"`, `"flip"`, or `"diagonal_swap"`. |
| `action` | string | Action id that triggers this operation. |

Example config:
```json
{
  "overlaySystemId": "overlay",
  "affectedLayers": ["objects"],
  "operations": {
    "rotate": { "type": "rotate", "action": "rotate" },
    "flip": { "type": "flip", "action": "flip" },
    "swap": { "type": "diagonal_swap", "action": "diagonal_swap" }
  }
}
```

**Operation: `rotate`**

Rotates all cell contents within the overlay.

2×2 clockwise rotation:
```
[0,0] → [1,0]
[1,0] → [1,1]
[1,1] → [0,1]
[0,1] → [0,0]
```

3×3 clockwise (standard matrix rotation): `[x,y] → [size-1-y, x]`

Action params: `{ "rotation": "clockwise" }` or `{ "rotation": "counterclockwise" }`.

**Operation: `flip`**

Mirrors cell contents along an axis.

Vertical flip: `[x, y] → [x, size-1-y]`
Horizontal flip: `[x, y] → [size-1-x, y]`

Action params: `{ "axis": "vertical" }` or `{ "axis": "horizontal" }`.

**Operation: `diagonal_swap`**

Swaps two diagonal corner cells based on direction.

Swap mapping (2×2 overlay at `[ox, oy]`):

| Direction | Cell A | Cell B |
|-----------|--------|--------|
| `up_left` | `[ox+1, oy+1]` (bottom-right) | `[ox, oy]` (top-left) |
| `up_right` | `[ox, oy+1]` (bottom-left) | `[ox+1, oy]` (top-right) |
| `down_left` | `[ox+1, oy]` (top-right) | `[ox, oy+1]` (bottom-left) |
| `down_right` | `[ox, oy]` (top-left) | `[ox+1, oy+1]` (bottom-right) |

**Behavior:**
1. On the configured action, determine the operation type.
2. For rotate/flip: collect all entities within the overlay bounds on affected layers, apply the spatial mapping, reposition.
3. For diagonal_swap: swap the two mapped cells.
4. Emit the corresponding event.

---

### 2.9 `flood_fill`

**Purpose:** Flood fill from a source position, changing connected same-kind/same-color cells.

**Phase:** `action_resolution`

**Events emitted:** `cells_flooded`

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `floodAction` | string | `"flood"` | Action id that triggers flood fill. |
| `sourcePosition` | string | `"avatar"` | `"avatar"` (avatar position) or `"overlay_center"`. |
| `affectedLayer` | string | `"objects"` | Layer to flood fill on. |
| `matchBy` | string | `"color"` | `"color"` (match entities with same `color` param) or `"kind"` (match same entity kind). |
| `colorCycle` | array of strings | `["red","blue","green","yellow","purple","orange"]` | Color cycle for `matchBy: "color"`. Current color advances to next in cycle. |
| `kindTransform` | object | `{}` | For `matchBy: "kind"`, maps current kind → new kind. |

**Behavior:**
1. On `floodAction`, determine source position.
2. Read the entity at source position on `affectedLayer`.
3. Find all connected cells with the same match criterion (4-directional adjacency).
4. Apply the transformation (advance color in cycle, or transform kind).
5. Emit `cells_flooded`.

---

### 2.10 `anchor_point`

**Purpose:** Maintain a single movable anchor on the board. On the configured action: if no anchor entity exists, place one at the avatar's current position; if one exists, teleport the avatar to the anchor and remove it.

**Phase:** `action_resolution`

**Events emitted:** `avatar_exited`, `avatar_entered` (no `direction` field — `ice_slide` will not trigger a slide after teleport)

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `markerKind` | string | — | **Required.** Entity kind to use as the anchor marker. |
| `markerLayer` | string | — | **Required.** Layer to store the anchor on. Must be declared in the game's `layers` array. |
| `action` | string | — | **Required.** Action id that triggers the toggle. |
| `blockedByTags` | array of strings | `["solid"]` | Tags on the `objects` layer that prevent teleportation to the anchor cell. If a matching entity is present, the teleport is skipped and the anchor remains. |

**Behavior:**
1. On the configured action, scan `markerLayer` for any entity of `markerKind`.
2. If none found: place `markerKind` at the avatar's current cell in `markerLayer`. No events emitted.
3. If found: check the `objects` layer at the marker cell. If any entity there has a `blockedByTags` tag, do nothing.
4. Otherwise: remove the marker, teleport avatar to the marker cell. Emit `avatar_exited` from the old position and `avatar_entered` at the new position (without a `direction` field in the payload).

**Note on ice:** The `avatar_entered` event emitted during teleport intentionally omits `direction`. The `ice_slide` cascade system skips events without a direction, so teleporting onto ice does not trigger a slide. Rules that react to `avatar_entered` (pickup, liquid, etc.) still fire normally since they do not require a direction.

**Reuse:** This system type is game-agnostic. Any game can use it with a different `markerKind`, `markerLayer`, and `action` to implement "save point", "recall beacon", "twin", or similar mechanics.

---

### 2.11 `coupled_actors`

**Purpose:** Move every actor entity on a layer (default `actors`) together, one cell each, in response to a single `move` action — unlike `avatar_navigation`, which moves one avatar. Actors are resolved front-first (the actor closest to the direction of travel resolves first) so a trailing actor can legally "train" into a cell the actor ahead of it just vacated. Optionally claims territory as a side effect of reaching a new cell, tagging the claim with the mover's kind as `ownerKind`.

**Phase:** `action_resolution`

**Events emitted:** `actor_moved`, `actor_entered`, `actor_blocked`, `cell_claimed` (only when `claim` is configured)

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `moveAction` | string | `"move"` | Action id that triggers movement. |
| `directions` | array of strings | all 4 cardinals | Directions the system responds to. |
| `actorLayer` | string | `"actors"` | Layer holding the moving entities. |
| `groundLayer` | string | `"ground"` | Layer checked for wall collisions. |
| `wallTag` | string | `"solid"` | Tag on `groundLayer` that blocks a mover. |
| `directionTransforms` | object | `{}` | Actor kind → direction transform. Kinds not listed use `identity`. Values: `identity`, `invert` (180° reverse), `mirror_x` (flip left/right), `mirror_y` (flip up/down). Unrecognised values are treated as `identity`. |
| `tape` | object | — | Optional. Drives the system from a stored programme instead of from the action's direction. See [Tape-driven stepping](#tape-driven-stepping). |
| `claim` | object | — | Optional. When present, an actor that reaches a new cell also claims it in a territory layer. See below. |
| `excavate` | object | — | Optional. Lets actors cut through terrain that would otherwise block them, backfilling the cell they leave. See [Excavating movers](#excavating-movers). |

`claim` object:

| Field | Type | Description |
|-------|------|-------------|
| `layer` | string | Territory layer to write claims into. Must be declared in the game's `layers` array. |
| `map` | object | Mover's entity kind → claim-mark entity kind written to `claim.layer`. |
| `overwrite` | object | Optional. Policy for entering a cell that is already owned. Defaults to `{mode: "never"}` — the pre-0.8 behaviour. See [Claim overwrite](#215-claim-overwrite). |

Example config:
```json
{
  "actorLayer": "actors",
  "groundLayer": "ground",
  "directionTransforms": { "mirror": "invert" },
  "claim": {
    "layer": "territory",
    "map": { "runner": "terr_runner", "mirror": "terr_mirror" }
  }
}
```

**Behavior:**
1. On `moveAction` with a direction in `directions`, collect every actor entity on `actorLayer` as `(position, kind)` pairs, and compute each actor's **effective direction** by applying its `directionTransforms` entry to the action's direction.
2. Group actors into **buckets** by effective direction. Buckets resolve in the fixed canonical order `up, down, left, right`. Within a bucket, sort front-first: by the projection of `position` onto that bucket's direction, descending; ties are broken by the other-axis coordinate, then by kind — fully deterministic. When every actor uses `identity` there is exactly one bucket and this is identical to pre-0.8 ordering.
3. Seed the `occupied` set with every actor's current position.
4. For each actor in order: if its target cell is out of bounds, tagged `wallTag` on `groundLayer`, or still in `occupied`, the actor stays and emits `actor_blocked`. Otherwise it moves — `occupied` is updated live (old cell freed, new cell claimed) before the next actor resolves, the actor is relocated on `actorLayer`, and `actor_moved` + `actor_entered` are emitted.
5. If `claim` is configured and the actor moved, apply the claim policy — see [Claim overwrite](#215-claim-overwrite). Claiming applies only to cells reached by a move this turn — never to a blocked actor, and never to an actor's starting cell (seed the level's territory layer directly for those).

**Mirrored actors.** `directionTransforms` lets one input drive actors in different directions at once — mirrored/opposed avatars, tug-of-war pairs, reflection puzzles. Two actors that target each other's cells (a mutual swap) both stay put; this falls out of the live `occupied` set and needs no special case. `actor_moved` / `actor_entered` always report the **action's** direction, not the effective one.

<a name="tape-driven-stepping"></a>
**Tape-driven stepping.** With a `tape` block the system ignores the action's
`direction` and takes each step from a stored programme, so the world advances
on *any* accepted action — the player's turns drive a machine they do not
steer. This overrides both **Behavior** step 1 above (any accepted action can
trigger a step, not only `moveAction`) and the **Mirrored actors** note above
(`actor_moved` / `actor_entered` report the *tape's* chosen direction, not the
triggering action's own direction).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `program` | array of direction strings | — | The instruction word. Directions outside `directions` are ignored. |
| `cycle` | boolean | `false` | When `true` the programme repeats forever; when `false` the world stops stepping once it is exhausted. Read strictly: only the boolean `true` cycles, so a non-boolean value (e.g. `"cycle": 1`, a JSON typo) behaves as `false` rather than being coerced. |
| `indexVariable` | string | `"tapeIndex"` | Runtime variable holding the next instruction index. |

```json
"tape": { "program": ["right", "right", "down", "left"], "cycle": true }
```

The index lives in a runtime variable, so it is part of the state key: undo,
`previewTurn` and solver deduplication all work with no extra handling. A
cycling programme wraps its index, keeping it bounded by the programme length,
which keeps the joint state space finite for a domain solver. A vetoed turn
cannot leak an advanced index, because the turn engine runs the whole turn on a
working copy and discards it on veto. The index advances before the
`directions` check runs, so a filtered-out instruction still consumes its slot
and produces no movement — the machine ticks regardless. A negative stored
index (for instance from a rule that decrements it) is clamped to 0 rather
than wrapping, so a rewind-past-the-start is inert.

Two taped `coupled_actors` systems both left at the default `indexVariable`
(`"tapeIndex"`) share one counter and each advances it once per turn — give
independent machines their own `actorLayer` **and** their own `indexVariable`,
or they will silently desynchronise from their own programmes.

<a name="excavating-movers"></a>
**Excavating movers.** With an `excavate` block an actor treats terrain it
would normally be blocked by as passable at a price: the target cell is cut
down to `clearedKind`, the actor takes it, and the cell the actor *left* is
backfilled with `backfillKind`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `diggableTag` | string | `"diggable"` | Tag on `groundLayer` marking terrain a mover excavates instead of being blocked by. |
| `clearedKind` | string | — | **Required.** Kind the excavated cell becomes. |
| `backfillKind` | string | — | Optional. Kind placed in the vacated cell. **Omitted means no backfill** — a pure tunneller that simply removes terrain. |
| `extraDiggableTags` | object | `{}` | Mover kind → additional ground tags that kind may excavate, on top of `diggableTag`. |

```json
"excavate": {
  "diggableTag": "diggable",
  "clearedKind": "floor",
  "backfillKind": "rubble",
  "extraDiggableTags": { "digger_drill": ["diggable_hard"] }
}
```

Resolution, inside the existing per-actor loop:

1. Out of bounds, or a target still occupied by another actor → blocked, as
   without the block.
2. Target carries `wallTag` **and** either `diggableTag` or a tag granted to
   this mover's kind by `extraDiggableTags` → excavated, then entered.
3. Target carries `wallTag` without `diggableTag` → blocked, as without the
   block. Terrain is only diggable if a game opts in by tagging it; the tag
   alone does nothing without an `excavate` block.
4. Target is free ground → an ordinary move. **No backfill** — walking a
   corridor never seals it.
5. After **every** actor has resolved, each pending backfill cell is set to
   `backfillKind` **unless an actor occupies it at end of turn**, in which case
   nothing is placed.

Step 5 is deliberately outside the per-actor loop, and is the reason the block
is worth having: whether a corridor survives depends on whether a *second*
actor ends the turn in the excavator's vacated cell. Games get "one digger
seals the tunnel behind it, two diggers in a train leave it open" out of the
existing front-first ordering with no special case.

Both the cut and the backfill emit `cell_transformed`, the same event
`terrain_edit` emits — discriminate them on `toKind`. When a backfill is
*skipped* because a mover hauled the spoil out, a
[`spoil_hauled`](05_rules.md#spoil_hauled) event fires at that cell instead, so
the corridor surviving is observable rather than being a silent absence.

**Tolerance contract.** A non-object `excavate`, or one whose `clearedKind` is
missing or not a non-empty string, is **inert** — the system behaves exactly
as if the block were absent. A missing or non-string `backfillKind` means no
backfill. A missing or non-string `diggableTag` falls back to `"diggable"`.
Both engines implement precisely this; do not rely on any other coercion.

Note that `backfillKind` is normally a kind that is **not** tagged
`diggableTag`, which is what makes excavation irreversible. Tagging the spoil
diggable is legal and yields a freely re-cuttable medium instead.

**Differently-abled tunnellers.** `extraDiggableTags` grants named mover kinds
additional terrain tags on top of `diggableTag`, which every mover can always
cut. It is purely **additive** — it never narrows what a mover can dig, and a
kind absent from the map behaves exactly as it would with no block at all. The
consequence worth designing around is that one cell becomes a wall for one
mover and a doorway for another, so typed terrain can split a lock-stepped crew
without any blocker being manufactured: an ice-breaker beside a snow-plough, a
battering ram beside a lockpick, a drill rig entering strata a hand crew cannot.

Extending the tolerance contract: a non-object `extraDiggableTags` grants
nothing; an entry whose value is not a list of non-empty strings is ignored for
that kind; an empty list is indistinguishable from an absent entry. Grants are
per-tag, so a mover granted one tag is still blocked by every other undiggable
solid. Both engines implement precisely this; do not rely on any other
coercion.

**Reuse:** Game-agnostic — any game with two or more entities that must move in lock-step (racing, paired agents, tug-of-war mechanics) can use this system; the optional `claim` block is only needed for territory-painting mechanics such as the [`balance` goal](03_levels.md#goals); the optional `tape` block turns the same system into a scripted lock-step mover — a metronome or patrol driven by a stored programme rather than by input; the optional `excavate` block turns movers into tunnellers (mining, snow clearing, ice carving). The three blocks are orthogonal and compose. Because the tape drives every actor on the layer identically, it cannot move only the entities on particular cells (that would be a conveyor, which this is not).

---

### 2.12 `individual_actors`

**Purpose:** Select one actor entity on a layer (default `actors`) and move only that selected actor with a directional action. This is the individual-control counterpart to `coupled_actors`: it keeps actors as data-driven layer entities, supports the same territory-claim side effect, and can optionally enforce per-actor successful-move budgets.

**Phase:** `action_resolution`

**Events emitted:** `actor_selected`, `actor_moved`, `actor_entered`, `actor_blocked`, `actor_reacted` (only when `reactiveKinds` is configured), `cell_claimed` (only when `claim` is configured), `action_vetoed` (when selection/movement is invalid)

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `selectAction` | string | `"tap_cell"` | Action id used to select an actor. The action must carry a `position` param. |
| `moveAction` | string | `"move"` | Action id that moves the selected actor. |
| `directions` | array of strings | all 4 cardinals | Directions the system responds to. |
| `actorLayer` | string | `"actors"` | Layer holding selectable/moving actors. |
| `actorTag` | string | `"actor"` | Tag an entity kind must have to be selectable. |
| `groundLayer` | string | `"ground"` | Layer checked for wall collisions. |
| `wallTag` | string | `"solid"` | Tag on `groundLayer` that blocks a mover. |
| `selectedVariable` | string | `"selectedActorKind"` | Runtime variable storing the currently selected actor kind. |
| `selectedPositionVariable` | string | `"selectedActorPosition"` | Runtime variable storing the selected actor's current `[x, y]` position, so actors of the same kind remain distinguishable. |
| `budgets` | object | — | Optional actor kind → successful move count. When configured, a selected actor at 0 remaining moves cannot move. |
| `budgetVariable` | string | `"actorMovesRemaining"` | Runtime variable storing remaining move budgets. |
| `claim` | object | — | Optional. Same shape and semantics as `coupled_actors.claim`. |
| `reactiveKinds` | object | `{}` | Optional. Actor kind → direction transform, using the same vocabulary as `coupled_actors.directionTransforms` (`identity`, `invert`, `mirror_x`, `mirror_y`). Actors of these kinds are **not** driven by the player: after each successful player move they take one step of their own, derived from the player's direction. See [Reactive actors](#reactive-actors). |

Example config:
```json
{
  "actorLayer": "actors",
  "selectAction": "tap_cell",
  "moveAction": "move",
  "budgets": { "wei": 7, "shu": 7, "wu": 7 },
  "claim": {
    "layer": "territory",
    "map": { "wei": "terr_wei", "shu": "terr_shu", "wu": "terr_wu" }
  }
}
```

**Behavior:**
1. On `selectAction`, if the tapped cell contains an actor entity, store its kind and position in `selectedVariable` and `selectedPositionVariable`, then emit `actor_selected`. If `budgets` is configured, initialise `budgetVariable` from it the first time an actor is selected.
2. On `moveAction`, reject with `action_vetoed` if no actor is selected, the selected actor is missing, or its remaining budget is 0.
3. Compute the selected actor's target cell. If the target is out of bounds, tagged `wallTag` on `groundLayer`, or occupied by another actor, the actor stays and emits `actor_blocked`.
4. Otherwise relocate only the selected actor, emit `actor_moved` + `actor_entered`, apply the claim policy to the destination cell (see [Claim overwrite](#215-claim-overwrite)), and decrement that actor's remaining budget when budgets are configured.

<a name="reactive-actors"></a>
**Reactive actors (opposition).** `reactiveKinds` turns named kinds into an
*opposition* that answers the player rather than obeying them. After a player
move resolves successfully, each reactive actor computes its own direction by
applying its transform to the **player's** direction — `invert` makes it mirror
the player, so moving left drives it right — and takes one step. Rules:

1. Reactive actors move **only after a successful player step**. A blocked
   attempt costs the player the action but gives the opposition nothing.
2. Resolution matches `coupled_actors`: bucket by effective direction in the
   canonical order `up, down, left, right`, front-first within a bucket, with a
   live `occupied` set. Fully deterministic — the whole turn stays a pure
   function of the player's move, so a solver's branching factor does not grow.
3. A blocked reactive actor simply holds position and emits nothing.
4. Reactive movement emits **`actor_reacted`**, never `actor_moved`. This keeps
   move counters, budgets and rules keyed on player movement unaffected by the
   opposition. A system that should treat a rival's landing as an anchor names
   the event explicitly — e.g. `flank_capture` with
   `"triggerEvents": ["actor_moved", "actor_reacted"]`, which lets the rival
   capture with the same bracket rule the player uses.
5. Reactive actors ignore `budgets`; only the player spends a pool.

**Reuse:** Game-agnostic — any game with multiple layer-entity actors can use it
for tap-to-select movement, squad puzzles, or budgeted routing; `reactiveKinds`
adds deterministic opposition (mirror-chasers, pursuit puzzles, adversarial
capture games) without any per-game engine code.

---

### 2.13 `line_of_sight`

**Purpose:** Detect an unobstructed horizontal or vertical relation between
configured source entities and target entities. The system is read-only:
games use rules to decide whether detection means collection, activation,
attack, communication, or something else.

**Phase:** `cascade_resolution`

**Events emitted:** `line_of_sight_detected`

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `triggerEvents` | array of strings | `["multi_cell_object_moved"]` | Run detection when at least one pending event has a listed type. |
| `sourceLayer` | string | — | Optional ordinary board layer containing source entities. When omitted, sources are selected from `multiCellObjects`. |
| `sourceKinds` | array of strings | `[]` | Optional source kind filter. |
| `sourceTags` | array of strings | `[]` | Optional source tag filter. |
| `sourceRoles` | array of strings | `[]` | Optional `multiCellObjects.params.role` filter. Ignored when `sourceLayer` is set. |
| `targetLayer` | string | `"objects"` | Layer containing candidate target entities. |
| `targetKinds` | array of strings | `[]` | Optional target kind filter. |
| `targetTags` | array of strings | `[]` | Optional target tag filter. |
| `blockingLayers` | array of strings | `["objects"]` | Ordinary layers checked between source and target. |
| `blockingTags` | array of strings | `["solid"]` | Entity tags that block sight. Empty means every entity on `blockingLayers` blocks. |
| `multiCellObjectsBlock` | boolean | `true` | Whether other multi-cell objects block sight and prevent detection of a covered target. |
| `maxMatches` | integer | `1` | Maximum events emitted per cascade pass. A value at or below zero means unlimited. |

**Behavior:**
1. Ignore a cascade pass unless one of its pending events matches `triggerEvents`.
2. Resolve sources from `sourceLayer`, or from `multiCellObjects` when no source layer is configured.
3. Filter sources and targets by their configured kinds, tags, and roles.
4. A source and target match only when they share a row or column, differ in position, and every intermediate cell is clear.
5. Void cells and matching blockers on `blockingLayers` break the sightline. When `multiCellObjectsBlock` is `true`, other multi-cell objects also break the sightline and prevent detection of a covered target.
6. Emit `line_of_sight_detected` without modifying the board or variables. Rules can react with standard effects such as `destroy`, `transform`, `set_variable`, or `increment_variable`.

Example:

```json
{
  "id": "visibility",
  "type": "line_of_sight",
  "config": {
    "triggerEvents": ["multi_cell_object_moved"],
    "sourceRoles": ["observer"],
    "targetLayer": "objects",
    "targetTags": ["signal"],
    "blockingLayers": ["objects"],
    "blockingTags": ["opaque"]
  }
}
```

**Reuse:** The same detector can support remote pickup, lasers, sentries,
line-activation switches, communication links, or visibility puzzles without
embedding any of those effects in the system.

---

### 2.14 `follower_npcs`

**Purpose:** Move autonomous entities once per turn according to a declared,
deterministic step rule. The system owns motion only — reacting to a move is
left to rules and lose conditions.

**Phase:** `npc_resolution` (after the player's action and all cascades have
settled, before goal evaluation)

**Events emitted:** `npc_moved`, `avatar_caught`, `line_of_sight_detected`

A behavior with `requiresLineOfSight` already computes the same relation the
[`line_of_sight`](#213-line_of_sight) system detects, so it publishes it under
the same event name rather than keeping it private. The event fires once per
seeing NPC per turn, and the `frequency` gate does not suppress it — an NPC that
only steps every other turn still reports what it can see on the turns it stands
still, which is what a "this one has noticed you" indicator needs. `kind` is the
literal string `avatar`, since the avatar is not a board entity and has no
entity kind.

`sourcePosition` is where the NPC **ends** the turn, not where it stood when the
check ran, so a beam drawn from it lands on the board the player is looking at
rather than trailing a segment behind a chaser that has already advanced along
that line. The shortened line is a sub-segment of the same unobstructed
sightline, so the report stays true. `sourceId` still names the cell the NPC
started from, matching the `npcId` on that turn's `npc_moved`, so the two events
can be correlated. Behaviors that never test a line (`patrol`, and
`toward_avatar` without `requiresLineOfSight`) emit nothing, because they never
checked.

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `npcTags` | array of strings | `["npc"]` | An entity on the `actors` layer is an NPC when it carries one of these tags. |
| `behaviors` | object | `{}` | Named behavior definitions. An NPC selects one by its `behavior` param; an NPC with no `behavior`, or one naming a missing definition, never moves. |
| `contactVariable` | string | `"caught"` | State variable incremented when a `lethalContact` NPC steps onto the avatar. Pair it with a `variable_threshold` lose condition. |

**Behavior definition fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string | — | `toward_avatar`, `toward_tag`, `toward_color`, `patrol`, or `clockwise`. |
| `frequency` | integer | `1` | Act only when `turnCount % frequency == 0`. The counter is incremented after this phase, so the first turn always acts. |
| `solidBlocking` | boolean | `true` | Whether entities tagged `solid` on the `objects` layer block the NPC. |
| `targetTag` | string | — | `toward_tag` only: seek the nearest entity with this tag on the `objects` or `markers` layer. |
| `targetColor` | string | — | `toward_color` only: seek the nearest entity whose `color` param matches, on the `objects` or `actors` layer. |
| `requiresLineOfSight` | boolean | `false` | `toward_avatar` only: move only while the avatar is visible, using the same relation [`line_of_sight`](#213-line_of_sight) detects. Losing sight freezes the NPC where it stands. |
| `blockingLayers` | array of strings | `["objects"]` | `requiresLineOfSight` only: layers checked for sight blockers. |
| `blockingTags` | array of strings | `["solid"]` | `requiresLineOfSight` only: tags that break the sightline. Empty means every entity on those layers blocks. |
| `multiCellObjectsBlock` | boolean | `true` | `requiresLineOfSight` only: whether a multi-cell object standing between the NPC and the avatar breaks the sightline. Both systems trace the line through one shared implementation, so this means here exactly what it means for [`line_of_sight`](#213-line_of_sight); the two used to answer differently for the same pair of cells. |
| `lethalContact` | boolean | `false` | Allow the NPC to step onto the avatar. On contact it increments `contactVariable` and emits `avatar_caught`. When `false` the avatar's cell is impassable, so a seeking NPC with no other distance-reducing step stands still and a `patrol` or `clockwise` NPC turns around — which makes the avatar's body a usable, movable blocker. Applies to every behavior, so a patrolling hazard has to declare its lethality rather than inherit it. |
| `gazeParam` | string | — | `toward_avatar` only: entity param to write each turn with the cardinal direction of the avatar while the NPC can see it, or `rest` when it cannot. Pair it with [`spriteParam`](02_game.md#entity-kinds) to give the NPC a per-direction look. Refreshed before the `frequency` gate and whether or not a step happens, since gaze is about seeing rather than moving. A behavior without `requiresLineOfSight` always counts as seeing the avatar, so it never rests. Levels should seed the param to match their opening geometry — the system only writes it during a turn, so the first frame shows whatever the level authored. |

**Behavior:**
1. Collect NPCs from the `actors` layer in row-major order. The board is
   mutated as they resolve, so a later NPC sees earlier moves this turn.
2. Skip an NPC whose `frequency` gate does not admit this turn.
3. Compute one candidate step:
   - `toward_avatar`, `toward_tag`, `toward_color` — the first passable cardinal
     step that strictly reduces Manhattan distance to the target, trying the
     dominant axis first (x on ties) and then up, down, left, right.
   - `patrol` — the cell ahead of `facing`; when blocked, reverse `facing` and
     take that cell instead.
   - `clockwise` — the cell ahead of `facing`, rotating `facing` clockwise
     (right → down → left → up) until a passable cell is found.
   Both circuit behaviors write the resulting `facing` back onto the entity, so
   heading is persistent state.
4. A cell is impassable when out of bounds, `void` ground, occupied by another
   NPC's post-move position, blocked by a `solid` object under
   `solidBlocking`, or occupied by the avatar unless `lethalContact` is set.
   Every behavior shares this one test, so passability cannot drift between
   them.
5. Move the NPC and emit `npc_moved`. On lethal contact also bump
   `contactVariable` and emit `avatar_caught`.

Example:

```json
{
  "id": "npcs",
  "type": "follower_npcs",
  "config": {
    "contactVariable": "caught",
    "behaviors": {
      "hunt": {
        "type": "toward_avatar",
        "requiresLineOfSight": true,
        "lethalContact": true,
        "blockingLayers": ["objects", "actors"]
      },
      "sweep": { "type": "patrol", "frequency": 2 }
    }
  }
}
```

**Reuse:** guards, chasers, patrols, scripted hazards, and creatures that seek a
resource rather than the player. Sight-gated motion makes the avatar's position
the only control channel, so an NPC can be steered rather than merely avoided.

> **Blocking the avatar.** An NPC is on the `actors` layer, which
> [`avatar_navigation`](#21-avatar_navigation) does not consult by default. To
> stop the player from walking through an NPC, tag the NPC `solid` and set
> `solidLayers: ["objects", "actors"]` on the navigation system.

---

### 2.15 Claim overwrite

Shared by `coupled_actors` and `individual_actors` — both resolve claims identically.

`claim.overwrite` object:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | string | `"never"` | `never` — an owned cell is never repainted (pre-0.8 behaviour). `always` — the last visitor owns every cell. `tagged` — the last visitor owns only cells carrying `tag`. |
| `tag` | string | — | Required when `mode` is `"tagged"`. |
| `layer` | string | the system's `groundLayer` | Layer checked for `tag`. |

**Resolution, in order:**
1. No `claim` block, or no `claim.map` entry for the mover's kind → nothing happens.
2. Destination already owned **by the mover's own kind** → nothing happens, **no event**. Re-entering your own territory is never a re-claim, under any policy.
3. Destination unowned → claimed; emits `cell_claimed`.
4. Destination owned by another kind, and the policy allows overwriting it → repainted; emits `cell_claimed`.
5. Destination owned by another kind, and the policy does not → untouched, no event. The mover passes over it freely: a **transit**.

```json
"claim": {
  "layer": "territory",
  "map": { "runner": "terr_runner", "mirror": "terr_mirror" },
  "overwrite": { "mode": "tagged", "tag": "contested" }
}
```

**Design note.** `never` and `tagged` differ in a way worth planning around: under `never`, owned ground is a free corridor — a mover crosses it without taking it. Tagged ground is the opposite: it **cannot be crossed without taking it**, since every entry repaints. A game can therefore use the tag to mark ground that costs ownership to traverse.

**Interaction with the balance lose conditions.** Both `balance_unreachable` and `balance_budget_exhausted` treat an owner past its equal share as terminal, which is only true while claims are permanent. When the current board carries repaintable cells, the engine suppresses that over-claim test in both conditions rather than report a false loss — see [03_levels.md](03_levels.md#lose-conditions).

---

### 2.15 `flank_capture`

**Purpose:** Reversi/Othello-style bracket capture, applied after an actor
moves. A straight run of one piece kind that ends up bracketed between two of
the opposing kind (or a terminating wall) is flipped to the bracketing kind.
Two `pairs` entries make the rule cut both ways: an aggressor bracketing a run
of its victim **captures** it, and a run of that same aggressor bracketed by the
victim is **flipped back** — the piece that just moved included. The system
transforms the board directly; it does not require rules.

**Phase:** `cascade_resolution`, event-triggered (like [`line_of_sight`](#213-line_of_sight)).

**Events emitted:** `cell_transformed` (one per flipped cell).

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `pieceLayer` | string | `"pieces"` | Layer holding the flippable pieces. |
| `pairs` | object | — | Aggressor kind → victim kind, **or an array of victim kinds**. `{ "alien": "human", "human": "alien" }` makes aliens capture human runs and human-bracketed alien runs flip back; `{ "alien": ["human", "splinter"] }` lets alien terminals capture runs of either kind. |
| `order` | array of strings | keys of `pairs` | Order the aggressor passes run in. With `["alien","human"]` the possess pass runs before the expose pass. Observable only when two aggressors share a victim kind — see **Multiple victim kinds** below. |
| `directions` | array of strings | all 4 cardinals | Which axes are scanned: any of `left`/`right` scans the **row** through the moved cell; any of `up`/`down` scans the **column**. |
| `wallTerminates` | boolean | `true` | Whether a wall may serve as a bracket terminal. |
| `wallLayer` | string | `"ground"` | Layer checked for wall terminals. |
| `wallTag` | string | `"solid"` | Tag that marks a wall terminal on `wallLayer`. |
| `terminalKinds` | object | `{}` | Aggressor kind → extra `pieceLayer` kinds that may close a bracket **for that aggressor only**. Gives a game asymmetric terrain: `{"human": ["insulator"]}` lets a neutral pylon bracket runs on the `human` pass while never closing one for any other aggressor. |
| `triggerEvents` | array of strings | `["actor_moved"]` | Events whose `position` (the mover's destination) anchors a capture pass. |

**Behavior (per move):**
1. Ignore the cascade pass unless one of its pending events matches
   `triggerEvents`. Collect the destination cell **B** of each matching event.
2. Take a **single snapshot** of `pieceLayer`. Every pass below reads this
   pre-flip snapshot.
3. For each aggressor `K` in `order` (victim `V = pairs[K]`), and each `B`, scan
   the full row and/or column through `B` (per `directions`). On each line, find
   every **maximal run of `V`** that is
   - **bracketed** on both ends by a `K` piece (snapshot) or, when
     `wallTerminates`, a wall — the **board edge is never a terminal**; and
   - **anchored to the mover**: `B` lies inside the run, or `B` is one of the
     two bracketing terminals.

   Flip every cell of such a run to `K` and emit `cell_transformed`.
4. Because all passes read the one snapshot, a cell never flips twice per move
   and the passes never observe each other's fresh cells. In particular a victim
   captured this move still counts as a terminal for a later pass — the elegant,
   deterministic "single snapshot, possess-then-expose" rule; a solver must
   mirror it bit-for-bit.

Anchoring keeps captures tied to the move that caused them: a run sitting
between two walls is not silently flipped the first time an unrelated piece
happens onto its row. The mover is automatically a **terminal** in the capture
pass and a **member of the run** in the flip-back pass, so both directions fall
out of the same rule.

**Multiple victim kinds.** An aggressor may name a list of victim kinds. Each
victim kind is scanned on its own pass, so victim runs are always
**homogeneous**: a run that mixes two victim kinds is not a maximal run of
either, and is therefore immune. Two aggressors may name the same victim kind —
with `{"alien": ["human", "splinter"], "human": ["alien", "splinter"]}` a
`splinter` cell can be claimed by either pass. Flips dedupe **first-writer-wins**
in `order`, so the aggressor listed earlier claims a contested cell; with a
single victim kind per aggressor the victim sets are disjoint and `order` has no
observable effect. Three-way configurations are how a pack builds rival factions
that are each other's jaws (Pincer's arc 4).

Example config:
```json
{
  "id": "capture",
  "type": "flank_capture",
  "config": {
    "pieceLayer": "pieces",
    "pairs": { "alien": "human", "human": "alien" },
    "order": ["alien", "human"],
    "wallLayer": "ground",
    "wallTag": "solid"
  }
}
```

Pair with [`individual_actors`](#212-individual_actors) or
[`coupled_actors`](#211-coupled_actors) (whose moves emit `actor_moved`) and an
[`all_cleared`](03_levels.md#all_cleared) goal on the victim kind for a
"convert every opponent" win.

**Reuse:** Any game with two opposing piece kinds that flip on a straight-line
bracket — Reversi/Othello puzzles, contagion-by-flanking, tug-of-war captures —
uses it by naming its own `pairs` and `pieceLayer`.

---

### 2.16 `support_collapse`

**Purpose:** Cells that lose their connection to a support root fall as rigid
components. A structure is held up by cells tagged as roots; after any cell is
removed, every maximal group of member cells that can no longer reach a root is
an orphan and falls, keeping its exact shape.

**Phase:** `action_resolution` (the sever verb) and `cascade_resolution`
(event-driven recompute)

**Events emitted:** `cell_cleared`, `object_settled`, `variable_changed`,
`action_vetoed`

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `layer` | string | `"ground"` | Layer holding the structure. |
| `severAction` | string | — | Action id that removes a cell adjacent to the avatar. Omit for a purely event-driven collapse. |
| `severableTags` | array of strings | `["severable"]` | Tags a cell must carry to be removable by the sever action. |
| `rootTags` | array of strings | `["support_root"]` | Cells that are always supported. |
| `memberTags` | array of strings | `["supported"]` | Cells that participate in the support graph. |
| `connectivity` | string | `"orthogonal"` | `"orthogonal"` or `"diagonal"`. |
| `direction` | string | `"down"` | Direction orphaned components fall. |
| `restLayers` | array of strings | `[layer]` | Layers checked for what stops a falling component. |
| `restTags` | array of strings | `["solid"]` | Tags on `restLayers` that stop a falling component. |
| `settleTransform` | object | `{}` | Kind→kind map applied to each cell when its component comes to rest. |
| `deflect` | object | `{}` | Map of tag → direction. A component blocked by cells carrying one of these tags steps one cell in the mapped direction instead of resting, then carries on falling. Empty disables deflection. |
| `carryAvatar` | boolean | `true` | Whether the avatar rides the component it is standing on. |
| `avatarFellVariable` | string | — | Variable incremented when the avatar rides a component down. Pair with a [`variable_threshold`](03_levels.md#variable_threshold) lose condition. |
| `triggerEvents` | array of strings | `[]` | Event types that trigger a cascade-phase recompute. Empty disables the cascade path. |

**Behavior:**
1. On the sever action, resolve the target cell. The action may name it either
   as a `position` param (a tapped cell, which must be orthogonally adjacent to
   the actor) or as a `direction` param (one step from the actor). Reject with
   `action_vetoed` if the target is out of bounds, holds nothing on `layer`, or
   carries no `severableTags` tag. A vetoed action does not count as a move.
2. Remove the target cell and emit `cell_cleared`.
3. BFS the supported set from every `rootTags` cell through `memberTags` cells
   using `connectivity`.
4. Every maximal connected group of member cells outside the supported set is an
   orphan component.
5. Lift every orphan cell off the board, so a component is never blocked by the
   hole it is falling out of, nor by a component that has not fallen yet.
6. Resolve components one at a time, the one furthest along `direction` first
   (ties broken by lowest `x`, then lowest `y`), writing each back to the board
   as soon as it comes to rest. Ordering them this way is what makes the result
   deterministic: every component that could block another has already landed
   by the time the other is resolved.
   - A component steps in `direction` while nothing blocks it. It is blocked
     when a destination cell holds an entity carrying a `restTags` tag on a
     `restLayers` layer.
   - Leaving the board does **not** block. A component whose cells have all left
     the board is destroyed.
   - **Deflection.** When `deflect` is non-empty and the component is blocked,
     the blocking kinds decide what happens next. If every blocker carries a
     `deflect` tag and they all map to the same direction, the component steps
     one cell that way and carries on falling. If any blocker carries no
     `deflect` tag, or the blockers disagree, the component rests. The sideways
     step is refused — and the component rests — when a destination cell is out
     of bounds or holds a `restTags` entity.
   - A component may deflect **at most once per lane**, and must travel one cell
     along `direction` before it may deflect again. Without this, two ramps
     facing each other would trade a component back and forth forever.
7. Apply `settleTransform` to each landed cell and emit `object_settled` per
   cell.
8. If `carryAvatar` and the avatar stood on an orphan, move it with the
   component and increment `avatarFellVariable`.

**Clearing on an `exactly_one` layer** writes that layer's declared `default`
kind, not an empty cell.

Example:

```json
{
  "id": "collapse",
  "type": "support_collapse",
  "config": {
    "layer": "ground",
    "severAction": "cut",
    "severableTags": ["severable"],
    "rootTags": ["support_root"],
    "memberTags": ["supported"],
    "direction": "down",
    "restLayers": ["ground"],
    "restTags": ["solid"],
    "settleTransform": { "hull": "wreck", "pod": "pod_settled" },
    "deflect": { "slope_left": "left", "slope_right": "right" },
    "carryAvatar": true,
    "avatarFellVariable": "wrecked"
  }
}
```

**Reuse:** `severAction` is optional, so the collapse half stands alone for any
game where rules or other systems remove cells. Suits hanging structures,
crumbling bridges, calving ice shelves, mining a ceiling, or any "cut the
support" mechanic. Without `deflect`, gravity is a straight translation: with
`direction: "down"` a cell's column never changes, only how far it falls.
`deflect` relaxes exactly that, and only at obstructions — a component never
changes lane in free fall.

---

### 2.17 `terrain_skip`

**Purpose:** Transport an actor across a contiguous block of tagged terrain in one step. When an actor steps onto a cell carrying `terrainTag`, it is immediately moved to the first non-terrain cell beyond the far edge of that region in the direction of travel. No additional events are emitted, so trail/budget rules do not fire a second time for the transit.

**Phase:** `cascade_resolution`, triggered by `actor_entered` events.

**Events emitted:** none (actor is relocated silently)

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `terrainTag` | string | `"water"` | Ground tag identifying the terrain to skip. |
| `groundLayer` | string | `"ground"` | Layer checked for `terrainTag`. |
| `actorLayer` | string | — | Layer holding the moving actors. |
| `actorPositionVariable` | string | — | Runtime variable updated to the actor's new position after transport. |
| `exitPortal` | object | — | When set, chains the transport through a `portals`-system portal found sitting on the exit cell: `{ "tags": ["teleport"], "matchKey": "channel" }`. Needed because this system's relocation is silent (no `actor_entered` fires for the exit cell), so the `portals` system can never see a landing there on its own — without this, an actor whose water-skip exit happens to be a portal tile gets stranded on it instead of teleporting through. |

**Behavior:**
1. On `actor_entered`, check whether the actor's new position carries `terrainTag` on `groundLayer`.
2. Walk forward in the movement direction through all contiguous `terrainTag` cells in the same row/column.
3. Exit position = one step beyond the last terrain cell in that direction.
4. Validate exit: in-bounds, not void, `groundLayer` cell is walkable, `actorLayer` cell is empty.
5. If valid: relocate actor to exit, update `actorPositionVariable`. If invalid: do nothing (actor remains on terrain). If `exitPortal` is configured and the exit cell carries a matching portal tag, the final position is instead the paired portal (same kind, matching `exitPortal.matchKey` value) — exit-hazard/exit-food checks then run against that final position, not the portal tile itself.

The entry move still costs the normal trail/budget (rules fire for the `actor_entered` that lands the actor on terrain). Add a `not: position_has_tag` guard to trail rules to make the transport fully free if desired.

**Example config:**
```json
{
  "id": "water_mover",
  "type": "terrain_skip",
  "config": {
    "terrainTag": "water",
    "groundLayer": "ground",
    "actorLayer": "snakes",
    "actorPositionVariable": "selectedSnakePosition",
    "exitPortal": { "tags": ["teleport"], "matchKey": "channel" }
  }
}
```

**Reuse:** Game-agnostic — any game with lanes, current channels, slip-streams, or wormhole corridors can use it. The `terrainTag` field distinguishes different terrain types within the same game, and the system fires once per cascade pass so chained transports resolve cleanly across multiple passes.

---

### 2.18 `terrain_edit`

**Purpose:** Consume a position-carrying action and write one entity kind onto
a layer, optionally spending from a runtime budget. This is the generic hook
for player-driven terrain change — the rules engine cannot express it, because
there is no "player acted at position" event.

**Phase:** `action_resolution`

**Events emitted:** `cell_transformed`

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `action` | string | `"place"` | Action id consumed. Must declare a `position` param. |
| `layer` | string | — | **Required.** Layer written to. |
| `kind` | string | — | **Required.** Entity kind written. |
| `fromKind` | string | — | Optional. The target cell must currently hold exactly this kind, or the edit is refused. |
| `budgetVariable` | string | — | Optional. Runtime variable that must be greater than zero; decremented on a successful edit. |

Example config:
```json
{
  "action": "place_wall",
  "layer": "ground",
  "kind": "wall",
  "fromKind": "empty",
  "budgetVariable": "walls"
}
```

**Behavior:**
1. Ignore any action whose id is not `action`.
2. Read the `position` param; ignore the action if it is missing, malformed, or out of bounds — a malformed position (a non-numeric element, a non-finite number, a too-short list) is refused, never raised.
3. If `budgetVariable` is set and its value is zero or less, refuse.
4. If `fromKind` is set and the target cell does not hold exactly that kind, refuse.
5. Otherwise write `kind` to `layer` at that cell, decrement the budget when
   configured, and emit `cell_transformed`. A refused edit mutates nothing and
   emits nothing — it is a wasted turn, not a vetoed one.

**Reuse:** Game-agnostic — any pack where the player places, paves, blocks or
marks a cell.

---

### 2.19 `sonar`

**Purpose:** Write a distance reading per source entity kind into
`state.variables` every turn — for each source, the distance to its paired (or
nearest) target entity. The system is **read-only with respect to the board**:
it mutates variables and nothing else.

This is the generic hook for "warmer/colder" sensing. A game can hide the
target layer from the player and let them locate it by moving and reading
(exploration by triangulation), or use the same reading as a proximity alarm,
a heat-seeker, or a scoring input.

**Phase:** `npc_resolution` — the last phase that runs unconditionally for
every system on every turn, after action, movement and cascade resolution have
settled the board and before goal evaluation. A reading therefore always
describes the board the player is looking at when the turn ends.

**Events emitted:** none.

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sourceLayer` | string | `"actors"` | Layer whose entities take readings. |
| `targetLayer` | string | — | **Required.** Layer holding the sensed entities. |
| `pairing` | object | — | Optional. Source kind → target kind. Omitted: each source reads the *nearest* target of any kind. Present: a source kind that is **not a key** is not sensed by this instance at all. |
| `metric` | string | `"manhattan"` | Reserved for future distance functions. Only `manhattan` is implemented. |
| `variablePrefix` | string | `"echo_"` | The reading for source kind `k` is written to `variablePrefix + k`. |
| `aggregate` | string | — | Optional. `"sum"`, `"min"` or `"max"`. Writes one combined reading for the whole source layer instead of one variable per source kind. Any other value behaves as absent. |
| `aggregateVariable` | string | `variablePrefix + "total"` | Variable receiving the combined reading. Only consulted when `aggregate` is set. |

```json
{
  "id": "echo",
  "type": "sonar",
  "config": {
    "sourceLayer": "actors",
    "targetLayer": "seams",
    "pairing": { "digger_a": "seam_a", "digger_b": "seam_b" }
  }
}
```

**Behavior:**
1. For each entity on `sourceLayer`, select candidate targets on
   `targetLayer` — filtered to `pairing[sourceKind]` when `pairing` is set,
   otherwise all targets.
2. Compute the Manhattan distance to the nearest candidate.
3. Write it to `state.variables[variablePrefix + sourceKind]`.

**Pairing scopes the instance.** When `pairing` is present, a source whose kind
is not one of its keys is skipped entirely — no variable is written for it, and
it contributes nothing to an aggregate. This is what lets **two `sonar`
instances share one source layer**, each sensing only its own kinds; without
it the second instance would sense the first's sources against whatever target
happened to be nearest. A pairing omitted altogether still means
nearest-of-any-kind for every source.

**Aggregate mode.** When `aggregate` is set, steps 1–2 run unchanged but the
per-source distances are reduced to a single value written to
`aggregateVariable`; no per-kind variables are written by that instance. A pack
wanting both surfaces declares two `sonar` instances.

This turns N independent readings into one equation in N unknowns. Under
lockstep movement — every source stepping together — consecutive readings are
redundant and the system never closes, so an aggregate gauge only yields
information on turns where the sources *split*: some blocked, some moving.
Packs using it for deduction must supply that asymmetry through terrain; a
gauge over sources that always move together is unsolvable by reasoning.

```json
{
  "id": "crew_gauge",
  "type": "sonar",
  "config": {
    "sourceLayer": "actors",
    "targetLayer": "seams",
    "pairing": { "digger_d": "hidden_seam_d", "digger_e": "hidden_seam_e" },
    "aggregate": "sum",
    "aggregateVariable": "echo_total"
  }
}
```

**The reading ignores terrain completely.** It reports how far, never how to
get there — routing around walls remains the player's problem. Games relying
on this gap should pin it with a test.

**Why variables and not events.** Readings live in `state.variables`, so they
are inside `to_key()` and undo, `previewTurn` and solver deduplication work
with no extra handling. Because a reading is a pure function of board state it
adds no new state distinctions and cannot inflate a solver's search space.

**Tolerance contract.** A missing or non-string `targetLayer` makes the system
**inert** — it writes nothing at all. A non-object `pairing` is treated as
absent, selecting nearest-of-any-kind mode. A `metric` other than
`"manhattan"` falls back to `"manhattan"` rather than raising. A non-string
`variablePrefix` falls back to `"echo_"`. An `aggregate` other than `"sum"`,
`"min"` or `"max"` is treated as absent, selecting per-kind mode. A non-string
or empty `aggregateVariable` falls back to `variablePrefix + "total"`. Under
`sum`, a single source without a target makes the whole reading `-1` — a
partial sum is numerically indistinguishable from a real one and would silently
corrupt a player's deduction. Under `min` and `max`, target-less sources are
skipped and the result is `-1` only when no source has a target. An empty
source layer reads `-1`; a *missing* source layer leaves the system inert. Both
engines implement precisely this; do not rely on any other coercion.

**No target reads `-1`,** rather than leaving the variable unwritten, so a
level can never read a stale value from a previous turn. Two source entities
sharing a kind write the same variable and the value is the **minimum** over
them, so the result does not depend on iteration order.

**Hiding the target layer** is a presentation concern and lives outside this
system: give the target entity kinds a `display` of type `none` (see
[02_game.md](02_game.md)) so they occupy state without being drawn.

**Reuse:** Game-agnostic. Any pack can point it at any layer pair — hidden
objectives, pursuit distance, "hot and cold" hint systems, or a scoring signal
— without new code.

---

### 2.20 `elastic_block`

**Purpose:** Control one rectangular `multiCellObject` whose footprint expands
to the next obstacle or collapses against the obstructed edge. The object always
remains a solid axis-aligned rectangle.

**Phase:** `action_resolution`

**Events emitted:** `elastic_block_inflated`, `elastic_block_collapsed`,
`object_pushed`, `target_completed`, `target_consumed`, `cell_cleared`,
`cell_transformed`, `variable_changed`, `action_vetoed`

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `objectKind` | string | `"elastic_block"` | Kind of the single `multiCellObject` controlled by the system. Exactly one matching rectangular object must exist. |
| `moveAction` | string | `"move"` | Action id that carries the direction press. |
| `directions` | array of strings | `["up","down","left","right"]` | Directions accepted from `moveAction`. |
| `inflateMode` | string | `"to_obstacle"` | `"to_obstacle"` repeats until the next whole line is blocked; `"single_step"` adds at most one line. |
| `collapseWhenBlocked` | boolean | `true` | Collapse toward the obstructed leading edge when the first new line cannot be entered. |
| `collapseThickness` | integer | `1` | Thickness retained along the pressed axis after a collapse. Values below 1 are treated as 1. |
| `rejectNoOpMoves` | boolean | `true` | Veto a blocked press that cannot collapse. The veto leaves state, counters, and undo history unchanged. |
| `groundLayer` | string | `"ground"` | Layer checked for ground validity. |
| `validGroundTags` | array of strings | `["walkable"]` | At least one required tag on every new block or pushed-object ground cell. |
| `blockingLayers` | array of strings | `["objects"]` | Layers checked for solid obstacles and pushable entities. |
| `blockingTags` | array of strings | `["solid"]` | Tags identifying blockers on `blockingLayers`. |
| `pushableTags` | array of strings | `["pushable"]` | Tags identifying blockers that the advancing face may push. |
| `chainPush` | boolean | `false` | Allow aligned pushable entities to move together as a chain. |
| `chainPushableTags` | array of strings | value of `pushableTags` | Tags required for every entity participating in a chain push. A pushable without one of these tags can still be pushed by itself. |
| `targetLayer` | string | `"markers"` | Default layer containing target marker kinds. |
| `targets` | array | `[]` | Target definitions described below. Empty disables target tracking and board mutation. |
| `completedTargetIdsVariable` | string | `"completedTargetIds"` | Sorted list of target ids that have matched exactly. |
| `consumedTargetIdsVariable` | string | `"consumedTargetIds"` | Sorted list of completed targets whose rectangle has subsequently been fully vacated. |
| `completedTargetsVariable` | string | `"completedTargetCount"` | Number of completed targets. Pair with a `variable_threshold` goal. |

Each `targets` entry has this form:

```json
{
  "id": "forge",
  "markerKind": "target_forge",
  "onLeave": "wall",
  "wallKind": "wall"
}
```

`id` defaults to `markerKind`. All cells of `markerKind` on `targetLayer` (or
the entry's optional `markerLayer`) form that target. They must be one solid
rectangle. `onLeave` is `"none"`, `"void"`, or `"wall"`; the latter two use
`voidKind`/`groundLayer` or `wallKind`/`wallLayer`, defaulting to
`void`/`ground` and `wall`/`objects`.

**Behavior:**

1. Resolve the one `multiCellObject` whose kind equals `objectKind`. Veto the
   action when it is missing, duplicated, non-rectangular, or the direction is
   invalid.
2. Build the complete one-cell line beyond the pressed edge. A line is
   enterable only when every cell is in bounds, has valid ground, contains no
   other multi-cell object, and contains no unpushable blocker.
3. A pushable blocker is enterable only when its next cell in the pressed
   direction independently passes the same ground and collision checks. Two
   aligned pushables jam when `chainPush` is false. When it is true, the entire
   aligned chain moves only if every member matches `chainPushableTags` and the
   cell beyond the chain is enterable. Move every accepted pushable one cell,
   extend the leading edge by the whole line, and repeat for `to_obstacle` mode.
4. If the first line is blocked, retain the leading `collapseThickness` slices
   and remove the trailing slices. The perpendicular extent does not change.
   If this changes no cells, follow `rejectNoOpMoves`.
5. After an accepted inflation or collapse, compare the complete block cell set
   with every unfinished target cell set. Exact equality permanently completes
   a target and increments `completedTargetsVariable`; containment is not a
   match.
6. A completed target is consumed only after the block footprint is disjoint
   from its full rectangle. Its markers are cleared, then `onLeave` optionally
   changes every target cell to impassable ground or an unpushable wall. A
   target never reactivates.

The target state is stored in ordinary variables, so it participates in solver
state identity and survives engine copies. Packs that only need deformation can
leave `targets` empty and use another goal system.

---

## 3. System Summary Table

| System | Type | Phase | Primary Action |
|--------|------|-------|---------------|
| Avatar Navigation | `avatar_navigation` | `action_resolution` | `move` |
| Push Objects | `push_objects` | `movement_resolution` | (automatic on move into pushable) |
| Sliding Blocks | `sliding_blocks` | `action_resolution` | `move(position, direction)` |
| Elastic Block | `elastic_block` | `action_resolution` | `move(direction)` |
| Line of Sight | `line_of_sight` | `cascade_resolution` | event-triggered detection |
| Flank Capture | `flank_capture` | `cascade_resolution` | event-triggered bracket capture |
| Support Collapse | `support_collapse` | `action_resolution` + `cascade_resolution` | configurable sever verb (`position` or `direction`) |
| Portals | `portals` | `movement_resolution` | (automatic on portal entry) |
| Slide Merge | `slide_merge` | `action_resolution` | `move` |
| Queued Emitters | `queued_emitters` | `cascade_resolution` | (event-triggered) |
| Gravity | `gravity` | `cascade_resolution` | (automatic after state changes) |
| Overlay Cursor | `overlay_cursor` | `action_resolution` | `move` |
| Region Transform | `region_transform` | `action_resolution` | `rotate`, `flip`, `diagonal_swap` |
| Flood Fill | `flood_fill` | `action_resolution` | `flood` |
| Anchor Point | `anchor_point` | `action_resolution` | configurable |
| Coupled Actors | `coupled_actors` | `action_resolution` | `move` (configurable via `moveAction`; any accepted action when `tape` is set) |
| Individual Actors | `individual_actors` | `action_resolution` | `tap_cell` + `move` (configurable) |
| Terrain Skip | `terrain_skip` | `cascade_resolution` | event-triggered actor transport across tagged terrain |
| Terrain Edit | `terrain_edit` | `action_resolution` | `place` (configurable via `action`) |
| Sonar | `sonar` | `npc_resolution` | (automatic every turn; writes distance readings to variables) |
| Follower NPCs | `follower_npcs` | `npc_resolution` | (automatic once per turn) |

**Demoted to rule recipes** (see [05_rules.md §9](05_rules.md)): single-slot inventory, consumable interactions, liquid transitions. These use the standard event–condition–effect primitives and no longer require dedicated engine systems.

---

## 4. System Combinations by Game Type

### Flag-style games (avatar navigation puzzles)
`avatar_navigation` + `push_objects` + `portals` + inventory/consumable/liquid rule recipes

### Sokoban-style games with recall mechanic
`avatar_navigation` + `push_objects` + `anchor_point` + object-on-target rule recipe

### Number-style games (slide and merge)
`slide_merge` + `queued_emitters` + `gravity` (with `sequence_match` goal)

### Number-style with diagonal swaps
`slide_merge` + `overlay_cursor` + `region_transform` (diagonal_swap op) (with `sequence_match` goal)

### Direct sliding-block escape games
`sliding_blocks` (with `multiCellObjects` and a `variable_threshold` escape goal);
optionally add `line_of_sight` and rules for remote interactions.

### Elastic-footprint games
`elastic_block` (with one rectangular `multiCellObject`, optional pushable
obstacles, and a `variable_threshold` completed-target goal).

### Transformation-style games (pattern matching)
`overlay_cursor` + `region_transform` (rotate + flip ops) + `flood_fill`

### Hybrid games
Any combination of the above. The system architecture supports free composition as long as there are no conflicting action handlers.

---

## 5. Reserved System Types (v1+)

These types are reserved for future built-in systems:

- `line_push` — push entire rows/columns
- `multi_slot_inventory` — carry multiple items
- `timers` — turn-count-based triggers
- `collectibles` — collect N of M items
- `rule_tiles` — Baba-Is-You-style mutable rule objects
- `rotate_flip_board` — rotate/flip the entire board (not just an overlay region)
- `spawners` — periodic entity spawning
