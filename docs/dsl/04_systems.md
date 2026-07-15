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
| `moveAction` | string | `"move"` | Which action id triggers navigation. |

**Behavior:**
1. Compute target position from direction.
2. Check bounds — reject if out of grid.
3. Check ground layer — reject if `void`.
4. Check `solid` tag on objects layer:
   - `"block"`: reject move.
   - `"delegate"`: mark the move as pending. Emit `move_blocked` with the target position and blocker kind. Later phases (push) or rules (`resolve_move` effect) may complete or reject the pending move.
5. If not blocked, move avatar to target. Emit `avatar_exited` for old position, `avatar_entered` for new position.
6. Update `avatar.facing` to the movement direction.

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
| `toolInteractions` | array | `[]` | List of item-based destruction interactions. Each entry: `{ "item": "<kind>", "targetTag": "<tag>", "consumeItem": false, "animation": "<name>" }`. When the avatar holds the specified item and moves into an entity with the specified tag, the entity is destroyed and the avatar enters the vacated cell. `consumeItem` (default `false`) controls whether the item is removed from inventory. `animation` (optional) names an animation defined on the target entity kind to play before removal. Applies before pushable logic — works on any solid entity, not just pushable ones. |

**Behavior:**
1. When avatar movement targets a cell with an entity in the objects layer:
   a. Check `toolInteractions` in order. If any interaction matches (avatar holds the required item, entity has the required tag), destroy entity, optionally consume item, play animation if configured, move avatar. Skip remaining push logic.
   b. If entity is not pushable, movement fails.
   c. Compute push destination (one cell further in movement direction).
   c. Check push destination: must be in bounds, ground must have a `validTargetTags` tag, objects layer must be empty (or have matching tag if `chainPush`).
   d. If valid: move pushed object, then move avatar into vacated cell.
   e. If invalid: movement fails, avatar stays.
2. Emit `object_pushed`, `object_placed` for pushed object; standard avatar events.

---

### 2.3 `sliding_blocks`

**Purpose:** Move rigid `multiCellObjects` directly, one cell at a time, using a `move` action that carries both a start `position` and a `direction`.

**Phase:** `action_resolution`

**Events emitted:** `multi_cell_object_moved`, `multi_cell_object_exited`,
`object_placed`, `object_removed`, `line_of_sight_collected`,
`cell_transformed`, `variable_changed`

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `moveAction` | string | `"move"` | Action id that triggers block movement. |
| `validGroundTags` | array of strings | `["walkable"]` | Tags required on the ground cell for every destination cell that remains on the board. |
| `blockingLayers` | array of strings | `["objects"]` | Ordinary board layers that can block a sliding object. |
| `blockingTags` | array of strings | `["solid"]` | Tags that block movement on `blockingLayers`. Empty means any entity on those layers blocks. |
| `coverableTags` | array of strings | `[]` | Blocking entity tags that ordinary sliding objects may overlap, for example a floor hatch or pressure plate that remains present under a block. |
| `coverableBlockedRoles` | array of strings | `["escapee"]` | Object roles that must still treat `coverableTags` as blocking. This lets scenery cover a tagged cell without allowing a protected role to enter it. |
| `exitTags` | array of strings | `["exit"]` | Ground tags that allow an escapee to leave the board. |
| `escapedVariable` | string | `"escapedCount"` | Variable incremented when an escapee exits. |
| `revealOnUncovered` | array | `[]` | Spawn configured objects after a block moves away from their hidden positions. |
| `collectOnEnter` | array | `[]` | Collect configured objects when a moving multi-cell object enters their cells. |
| `lineOfSightCollect` | array | `[]` | After an accepted slide, collect configured objects that have an unobstructed same-row or same-column line to an eligible multi-cell collector. |
| `objectInteractions` | array | `[]` | Transform or remove configured objects when variable requirements are satisfied. By default interactions check the moving object's destination cells; `scope: "board"` checks the whole target layer. |

**Multi-cell object params:**

| Field | Type | Description |
|-------|------|-------------|
| `axis` | string | `"horizontal"`, `"vertical"`, `"both"`, or any other value to make the object immovable. |
| `role` | string | Use `"escapee"` for blocks allowed to leave through an exit edge. |

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
5. If the translated cells leave the board, allow the move only when the block has `role: "escapee"` and its leading edge is currently on a ground cell tagged by `exitTags`. The block is then removed, `escapedVariable` is incremented, and the post-move reveal, line-of-sight, and board interaction steps still run.
6. Before collision validation, apply matching destination-scoped `objectInteractions` to destination cells. This supports generic cases such as a collected key opening a locked gate.
7. Otherwise, replace the block's cell list with the translated cell list.
8. After the move, apply matching `collectOnEnter` rules to the block's new cells.
9. After the move, apply `revealOnUncovered` rules whose hidden positions are no longer covered by any multi-cell object.
10. After the move, apply matching `lineOfSightCollect` rules to every eligible collector. A collectible covered by another multi-cell object cannot be collected.
11. After collection and reveal effects, apply `objectInteractions` again. This lets board-scoped interactions update visible objects immediately after a variable changes, for example opening all visible locked gates as soon as a key is collected.

**Optional `revealOnUncovered` entries:**

| Field | Type | Description |
|-------|------|-------------|
| `position` | position | Hidden cell to watch. |
| `layer` | string | Layer to place the revealed object on, usually `"objects"`. |
| `kind` | string | Entity kind to spawn when the position is no longer covered. |
| `revealedVariable` | string | Optional boolean variable set after the reveal to prevent duplicate spawns. |

**Optional `collectOnEnter` entries:**

| Field | Type | Description |
|-------|------|-------------|
| `roles` | array of strings | Optional allowed multi-cell object roles, such as `["escapee"]`. |
| `layer` | string | Layer to inspect for collectible objects. |
| `kinds` | array of strings | Optional specific entity kinds to collect. |
| `tags` | array of strings | Optional entity tags to collect. |
| `variable` | string | Optional variable incremented for each collected object. |
| `remove` | boolean | Whether to remove the collected object. Defaults to `true`. |

**Optional `lineOfSightCollect` entries:**

| Field | Type | Description |
|-------|------|-------------|
| `roles` | array of strings | Optional allowed multi-cell object roles, such as `["escapee"]`. |
| `layer` | string | Layer to inspect for collectible objects. |
| `kinds` | array of strings | Optional specific entity kinds to collect. |
| `tags` | array of strings | Optional entity tags to collect. |
| `variable` | string | Optional variable incremented for each collected object. |
| `remove` | boolean | Whether to remove the collected object. Defaults to `true`. |
| `blockingLayers` | array of strings | Layers checked as line-of-sight blockers. Defaults to the system `blockingLayers`. |
| `blockingTags` | array of strings | Tags that block line of sight on `blockingLayers`. Defaults to the system `blockingTags`. |

**Optional `objectInteractions` entries:**

| Field | Type | Description |
|-------|------|-------------|
| `layer` | string | Layer to inspect for target objects. |
| `targetKinds` | array of strings | Optional specific target entity kinds. |
| `targetTags` | array of strings | Optional target entity tags. |
| `requiredVariable` | string | Optional variable that must meet `minValue`. |
| `minValue` | number | Minimum required variable value. Defaults to `1`. |
| `toKind` | string | Entity kind to transform the target into. |
| `remove` | boolean | Whether to remove the target instead of transforming it. |
| `scope` | string | `"destination"` checks only the moving object's destination cells. `"board"` checks every occupied cell on `layer`. Defaults to `"destination"`. |

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

**Behavior:**
1. When avatar enters a cell with a `teleportTags` entity:
   a. Read `matchKey` parameter (e.g., `channel: "blue"`).
   b. Find the paired portal with the same value.
   c. Move avatar to paired portal position.
   d. If `endMovement`: turn continues from portal position. If `false`: avatar continues moving in original direction.
2. If `teleportObjects` and an object is pushed onto a portal: teleport object similarly.

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
| `claim` | object | — | Optional. When present, an actor that reaches a new cell also claims it in a territory layer. See below. |

`claim` object:

| Field | Type | Description |
|-------|------|-------------|
| `layer` | string | Territory layer to write claims into. Must be declared in the game's `layers` array. |
| `map` | object | Mover's entity kind → claim-mark entity kind written to `claim.layer`. |
| `overwrite` | object | Optional. Policy for entering a cell that is already owned. Defaults to `{mode: "never"}` — the pre-0.10 behaviour. See [Claim overwrite](#claim-overwrite). |

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
2. Group actors into **buckets** by effective direction. Buckets resolve in the fixed canonical order `up, down, left, right`. Within a bucket, sort front-first: by the projection of `position` onto that bucket's direction, descending; ties are broken by the other-axis coordinate, then by kind — fully deterministic. When every actor uses `identity` there is exactly one bucket and this is identical to pre-0.10 ordering.
3. Seed the `occupied` set with every actor's current position.
4. For each actor in order: if its target cell is out of bounds, tagged `wallTag` on `groundLayer`, or still in `occupied`, the actor stays and emits `actor_blocked`. Otherwise it moves — `occupied` is updated live (old cell freed, new cell claimed) before the next actor resolves, the actor is relocated on `actorLayer`, and `actor_moved` + `actor_entered` are emitted.
5. If `claim` is configured and the actor moved, apply the claim policy — see [Claim overwrite](#claim-overwrite). Claiming applies only to cells reached by a move this turn — never to a blocked actor, and never to an actor's starting cell (seed the level's territory layer directly for those).

**Mirrored actors.** `directionTransforms` lets one input drive actors in different directions at once — mirrored/opposed avatars, tug-of-war pairs, reflection puzzles. Two actors that target each other's cells (a mutual swap) both stay put; this falls out of the live `occupied` set and needs no special case. `actor_moved` / `actor_entered` always report the **action's** direction, not the effective one.

**Reuse:** Game-agnostic — any game with two or more entities that must move in lock-step (racing, paired agents, tug-of-war mechanics) can use this system; the optional `claim` block is only needed for territory-painting mechanics such as the [`balance` goal](03_levels.md#goals).

---

### 2.12 `individual_actors`

**Purpose:** Select one actor entity on a layer (default `actors`) and move only that selected actor with a directional action. This is the individual-control counterpart to `coupled_actors`: it keeps actors as data-driven layer entities, supports the same territory-claim side effect, and can optionally enforce per-actor successful-move budgets.

**Phase:** `action_resolution`

**Events emitted:** `actor_selected`, `actor_moved`, `actor_entered`, `actor_blocked`, `cell_claimed` (only when `claim` is configured), `action_vetoed` (when selection/movement is invalid)

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
| `budgets` | object | — | Optional actor kind → successful move count. When configured, a selected actor at 0 remaining moves cannot move. |
| `budgetVariable` | string | `"actorMovesRemaining"` | Runtime variable storing remaining move budgets. |
| `claim` | object | — | Optional. Same shape and semantics as `coupled_actors.claim`. |

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
1. On `selectAction`, if the tapped cell contains an actor entity, store its kind in `selectedVariable` and emit `actor_selected`. If `budgets` is configured, initialise `budgetVariable` from it the first time an actor is selected.
2. On `moveAction`, reject with `action_vetoed` if no actor is selected, the selected actor is missing, or its remaining budget is 0.
3. Compute the selected actor's target cell. If the target is out of bounds, tagged `wallTag` on `groundLayer`, or occupied by another actor, the actor stays and emits `actor_blocked`.
4. Otherwise relocate only the selected actor, emit `actor_moved` + `actor_entered`, apply the claim policy to the destination cell (see [Claim overwrite](#claim-overwrite)), and decrement that actor's remaining budget when budgets are configured.

**Reuse:** Game-agnostic — any game with multiple layer-entity actors can use it for tap-to-select movement, squad puzzles, or budgeted routing.

---

### 2.13 Claim overwrite

Shared by `coupled_actors` and `individual_actors` — both resolve claims identically.

`claim.overwrite` object:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | string | `"never"` | `never` — an owned cell is never repainted (pre-0.10 behaviour). `always` — the last visitor owns every cell. `tagged` — the last visitor owns only cells carrying `tag`. |
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

## 3. System Summary Table

| System | Type | Phase | Primary Action |
|--------|------|-------|---------------|
| Avatar Navigation | `avatar_navigation` | `action_resolution` | `move` |
| Push Objects | `push_objects` | `movement_resolution` | (automatic on move into pushable) |
| Sliding Blocks | `sliding_blocks` | `action_resolution` | `move(position, direction)` |
| Portals | `portals` | `movement_resolution` | (automatic on portal entry) |
| Slide Merge | `slide_merge` | `action_resolution` | `move` |
| Queued Emitters | `queued_emitters` | `cascade_resolution` | (event-triggered) |
| Gravity | `gravity` | `cascade_resolution` | (automatic after state changes) |
| Overlay Cursor | `overlay_cursor` | `action_resolution` | `move` |
| Region Transform | `region_transform` | `action_resolution` | `rotate`, `flip`, `diagonal_swap` |
| Flood Fill | `flood_fill` | `action_resolution` | `flood` |
| Anchor Point | `anchor_point` | `action_resolution` | configurable |
| Coupled Actors | `coupled_actors` | `action_resolution` | `move` (configurable via `moveAction`) |
| Individual Actors | `individual_actors` | `action_resolution` | `tap_cell` + `move` (configurable) |

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
`sliding_blocks` (with `multiCellObjects` and a `variable_threshold` escape goal)

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
