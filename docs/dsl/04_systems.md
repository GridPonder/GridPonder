# Gridponder DSL v0 — System Catalog

## 1. System Architecture

### Execution Phases

Each system declares which phase(s) it participates in. During a turn, phases execute in this fixed order:

| # | Phase | Purpose |
|---|-------|---------|
| 1 | `input_validation` | Engine validates action legality. No system runs here — this is engine-internal. |
| 2 | `action_resolution` | Primary action executes (avatar moves, tiles slide, overlay shifts, etc.). |
| 3 | `movement_resolution` | Secondary movement triggered by the primary action (pushing, teleporting). |
| 4 | `interaction_resolution` | Reserved for future systems. In v0, item/environment interactions are handled by rules in phase 5. |
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

### 2.3 `portals`

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

### 2.4 `slide_merge`

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

### 2.5 `queued_emitters`

**Purpose:** Release one item per turn from each multi-cell emitter whose exit cell is empty.

**Phase:** `npc_resolution` (runs once per turn, after all slides and cascades have settled)

**Events emitted:** `item_released`

**Config:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `emitterKind` | string | `"pipe"` | Multi-cell object kind that acts as an emitter. |

**Behavior:**
1. For each MCO of `emitterKind`, check whether the exit cell (from `mco.params.exitPosition`) is empty.
2. If empty and the queue has remaining items: dequeue next item, spawn at exit, emit `item_released`.
3. Only one item is released per emitter per turn.

---

### 2.6 `overlay_cursor`

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

## 3. System Summary Table

| System | Type | Phase | Primary Action |
|--------|------|-------|---------------|
| Avatar Navigation | `avatar_navigation` | `action_resolution` | `move` |
| Push Objects | `push_objects` | `movement_resolution` | (automatic on move into pushable) |
| Portals | `portals` | `movement_resolution` | (automatic on portal entry) |
| Slide Merge | `slide_merge` | `action_resolution` | `move` |
| Queued Emitters | `queued_emitters` | `cascade_resolution` | (event-triggered) |
| Gravity | `gravity` | `cascade_resolution` | (automatic after state changes) |
| Overlay Cursor | `overlay_cursor` | `action_resolution` | `move` |
| Region Transform | `region_transform` | `action_resolution` | `rotate`, `flip`, `diagonal_swap` |
| Flood Fill | `flood_fill` | `action_resolution` | `flood` |

**Demoted to rule recipes** (see [05_rules.md §9](05_rules.md)): single-slot inventory, consumable interactions, liquid transitions. These use the standard event–condition–effect primitives and no longer require dedicated engine systems.

---

## 4. System Combinations by Game Type

### Flag-style games (avatar navigation puzzles)
`avatar_navigation` + `push_objects` + `portals` + inventory/consumable/liquid rule recipes

### Number-style games (slide and merge)
`slide_merge` + `queued_emitters` + `gravity` (with `sequence_match` goal)

### Number-style with diagonal swaps
`slide_merge` + `overlay_cursor` + `region_transform` (diagonal_swap op) (with `sequence_match` goal)

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
