# Gridponder DSL — Rules Model

How game-specific interactions are expressed as data-driven if/then rules that fire between system execution phases.

## 1. Purpose

Rules are the **glue between systems**. They handle game-specific interactions that are too narrow to justify a dedicated engine system but too important to ignore.

**Design principle:** If the same rule pattern appears across many levels or games, it should become a system. Rules handle the long tail.

Examples of what rules express:
- When a pipe's exit cell is cleared, release the next queued item.
- When all gems are collected, open the exit door.
- When a bomb is pushed onto a pressure plate, destroy the adjacent wall.
- When a number settles after gravity, check for merges.

---

## 2. Rule Structure

```json
{
  "id": "pipe_release",
  "on": "cell_cleared",
  "where": { ... },
  "if": { ... },
  "then": [ ... ],
  "priority": 0,
  "once": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | **yes** | Unique rule identifier. |
| `on` | string | **yes** | Event type that triggers this rule. See event catalog. |
| `where` | condition | no | Spatial/contextual filter on the triggering event. If omitted, all events of this type match. |
| `if` | condition | no | Additional state conditions. If omitted, no extra conditions required. |
| `then` | array of effects | **yes** | Effects to apply when the rule fires. |
| `priority` | integer | no | Higher priority rules fire first. Default: `0`. |
| `once` | boolean | no | If `true`, the rule fires at most once per level attempt. Default: `false`. |

### Evaluation order

1. Collect all events accumulated during phases 2–4.
2. For each event, find all matching rules (event type matches `on`).
3. Filter by `where` condition against event data.
4. Filter by `if` condition against board/avatar/variable state.
5. Sort matching rules by `priority` (descending), then by declaration order.
6. Execute `then` effects in order.
7. Effects may produce new events.
8. Repeat from step 1 with new events (cascade pass). Maximum `maxCascadeDepth` passes (default: 3).

### Value references

Effect fields may use **value references** — strings beginning with `$` — to read live game state instead of hardcoded values. References are resolved once when the rule matches, before any effects execute (snapshot semantics).

| Reference | Resolves to |
|-----------|-------------|
| `$event.<field>` | A field from the triggering event's payload. |
| `$cell.<layer>.kind` | The entity kind at `$event.position` on the named layer. |
| `$cell.<layer>.param.<key>` | An entity parameter at `$event.position` on the named layer. |
| `$avatar.position` | The avatar's current `[x, y]` position. |
| `$avatar.item` | The avatar's current inventory item kind, or `null`. |

Examples:
```json
{ "destroy": { "position": "$event.position", "layer": "objects" } }
{ "set_inventory": { "item": "$cell.objects.kind" } }
{ "transform": { "position": "$event.position", "layer": "ground", "toKind": "bridge" } }
```

Constraints:
- References may only appear in effect fields, not in conditions.
- `$cell` always reads at `$event.position`. To check a different position, use a condition.
- If a reference resolves to `null` (e.g., no entity on that layer), the effect is skipped silently.

---

## 3. Event Catalog

Events are typed objects emitted by systems and the engine.

### `avatar_entered`
Avatar moved to a new cell.

| Payload | Type | Description |
|---------|------|-------------|
| `position` | `[x, y]` | Cell the avatar entered. |
| `direction` | string | Direction of movement. |
| `fromPosition` | `[x, y]` | Previous avatar position. |

### `avatar_exited`
Avatar left a cell.

| Payload | Type | Description |
|---------|------|-------------|
| `position` | `[x, y]` | Cell the avatar left. |

### `move_blocked`
Avatar attempted to move but was blocked by a solid entity (when `avatar_navigation.solidHandling` is `"delegate"`).

| Payload | Type | Description |
|---------|------|-------------|
| `position` | `[x, y]` | Target cell (the blocked destination). |
| `direction` | string | Movement direction. |
| `fromPosition` | `[x, y]` | Avatar's current position. |
| `blockerKind` | string | Entity kind that blocked movement. |

Rules can react to this event to implement tool-based interactions (e.g., torch burns burnable, pickaxe breaks breakable). Use the `resolve_move` effect to complete the avatar's pending movement after removing the blocker.

### `tiles_slid`
Tiles slid during a slide-merge action.

| Payload | Type | Description |
|---------|------|-------------|
| `direction` | string | Slide direction. |
| `movedCount` | integer | Number of tiles that moved. |

### `object_placed`
An entity was placed or moved to a cell on the objects layer.

| Payload | Type | Description |
|---------|------|-------------|
| `position` | `[x, y]` | Destination cell. |
| `kind` | string | Entity kind. |
| `params` | object | Entity parameters. |

### `object_removed`
An entity was removed from the objects layer (by any mechanism: pickup, destruction, push-away, consumption). This is the general "something was removed" event. Systems that remove entities emit this. Note: `cell_cleared` is a more specific event that fires only when a cell goes from occupied to empty — `object_removed` fires even if another entity immediately replaces the removed one.

| Payload | Type | Description |
|---------|------|-------------|
| `position` | `[x, y]` | Cell it was removed from. |
| `kind` | string | Entity kind that was removed. |

### `cell_cleared`
A cell on the objects layer became empty (had content, now has `null`).

| Payload | Type | Description |
|---------|------|-------------|
| `position` | `[x, y]` | Cell that was cleared. |
| `previousKind` | string | Kind that was there before. |

### `cell_transformed`
A cell's entity was replaced with a different entity.

| Payload | Type | Description |
|---------|------|-------------|
| `position` | `[x, y]` | Cell that changed. |
| `fromKind` | string | Previous kind. |
| `toKind` | string | New kind. |
| `layer` | string | Which layer changed. |

### `inventory_changed`
Avatar inventory changed.

| Payload | Type | Description |
|---------|------|-------------|
| `oldItem` | string or null | Previous inventory slot. |
| `newItem` | string or null | New inventory slot. |

### `object_pushed`
An object was pushed by the avatar.

| Payload | Type | Description |
|---------|------|-------------|
| `kind` | string | Pushed entity kind. |
| `fromPosition` | `[x, y]` | Original position. |
| `toPosition` | `[x, y]` | New position. |
| `direction` | string | Push direction. |

### `tiles_merged`
Two tiles merged during slide.

| Payload | Type | Description |
|---------|------|-------------|
| `position` | `[x, y]` | Position of the resulting merged tile. |
| `resultValue` | integer | Value of the merged tile. |
| `inputValues` | array of integers | Values of the tiles that merged. |

### `item_released`
An emitter released an item.

| Payload | Type | Description |
|---------|------|-------------|
| `emitterId` | string | Multi-cell object id. |
| `kind` | string | Released entity kind. |
| `position` | `[x, y]` | Spawn position. |
| `params` | object | Entity parameters. |

### `object_settled`
An entity settled after gravity/motion.

| Payload | Type | Description |
|---------|------|-------------|
| `kind` | string | Entity kind. |
| `position` | `[x, y]` | Final position. |
| `fromPosition` | `[x, y]` | Position before settling. |

### `npc_moved`
An NPC moved during NPC resolution.

| Payload | Type | Description |
|---------|------|-------------|
| `npcId` | string | NPC identifier (derived from position or kind). |
| `fromPosition` | `[x, y]` | Old position. |
| `toPosition` | `[x, y]` | New position. |

### `goal_step_completed`
A goal milestone was reached.

| Payload | Type | Description |
|---------|------|-------------|
| `goalId` | string | Goal identifier. |
| `stepIndex` | integer | Which step was completed. |

### `variable_changed`
A state variable was modified.

| Payload | Type | Description |
|---------|------|-------------|
| `variable` | string | Variable name. |
| `oldValue` | any | Previous value. |
| `newValue` | any | New value. |

### `turn_ended`
All phases completed for this turn.

| Payload | Type | Description |
|---------|------|-------------|
| `turnNumber` | integer | Current turn count. |

---

## 4. Condition Catalog

Conditions filter when a rule should fire. Every condition evaluates to `true` or `false`.

### Spatial/event conditions (used in `where`)

#### `position`
Match against the event's primary position.

```json
{ "position": [3, 2] }
```

#### `position_has_tag`
The event position's cell has a specific tag on a layer.

```json
{ "position_has_tag": { "layer": "ground", "tag": "liquid" } }
```

#### `event`
Match fields from the event payload. Consolidates kind and parameter matching.

```json
{ "event": { "kind": "metal_crate" } }
{ "event": { "param": "value", "equals": 5 } }
{ "event": { "kind": "metal_crate", "param": "value", "equals": 5 } }
```

| Field | Type | Description |
|-------|------|-------------|
| `kind` | string | Match entity kind in event data. |
| `param` | string | Event parameter key to match. |
| `equals` | any | Required value for the `param` field. |

When both `kind` and `param`/`equals` are present, both must match (implicit AND).

### State conditions (used in `if`)

#### `cell`
Check a cell's content on a specific layer.

```json
{ "cell": { "position": [3, 2], "layer": "objects", "kind": "rock" } }
{ "cell": { "position": [3, 2], "layer": "objects", "isEmpty": true } }
{ "cell": { "position": [3, 2], "layer": "objects", "hasTag": "solid" } }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `position` | `[x, y]` | **yes** | Cell to check. |
| `layer` | string | **yes** | Layer to check. |
| `kind` | string | — | Cell must contain this exact kind. |
| `isEmpty` | boolean | — | `true`: cell must be empty. `false`: cell must be occupied. |
| `hasTag` | string | — | Cell entity must have this tag. |

Exactly one of `kind`, `isEmpty`, or `hasTag` must be present.

#### `avatar`
Check avatar state.

```json
{ "avatar": { "at": [3, 2] } }
{ "avatar": { "hasItem": "torch" } }
{ "avatar": { "hasItem": true } }
{ "avatar": { "hasItem": false } }
{ "avatar": { "at": [3, 2], "hasItem": "torch" } }
```

| Field | Type | Description |
|-------|------|-------------|
| `at` | `[x, y]` | Avatar must be at this position. |
| `hasItem` | string or boolean | String: specific item kind. `true`: slot not empty. `false`: slot empty. |

At least one field must be present. When both are present, both must be true (implicit AND).

#### `variable`
Check a state variable against a value.

```json
{ "variable": { "name": "gemsCollected", "op": "eq", "value": 5 } }
{ "variable": { "name": "gemsCollected", "op": "gte", "value": 3 } }
```

Operators: `"eq"`, `"neq"`, `"gt"`, `"gte"`, `"lt"`, `"lte"`.

#### `emitter_has_next`
An emitter has remaining items in its queue.

```json
{ "emitter_has_next": { "emitterId": "pipe_1" } }
```

#### `board_count`
Count entities matching a selector.

```json
{ "board_count": { "kind": "gem", "op": "eq", "value": 0 } }
```

### Logical combinators

#### `all_of`
All sub-conditions must be true (AND).

```json
{ "all_of": [
  { "avatar": { "hasItem": "torch" } },
  { "cell": { "position": [3, 2], "layer": "objects", "hasTag": "burnable" } }
]}
```

#### `any_of`
At least one sub-condition must be true (OR).

```json
{ "any_of": [
  { "variable": { "name": "mode", "op": "eq", "value": "fire" } },
  { "avatar": { "hasItem": "torch" } }
]}
```

#### `not`
Negate a condition.

```json
{ "not": { "cell": { "position": [3, 2], "layer": "objects", "isEmpty": true } } }
```

---

## 5. Effect Catalog

Effects are state mutations applied when a rule fires.

### `spawn`
Place a new entity on the board.

```json
{ "spawn": { "position": [3, 2], "layer": "objects", "kind": "number", "value": 5 } }
```

### `destroy`
Remove an entity from the board. If `animation` is specified, the engine plays the named animation on the entity before removing it.

```json
{ "destroy": { "position": [3, 2], "layer": "objects" } }
{ "destroy": { "position": [3, 2], "layer": "objects", "animation": "burning" } }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `position` | `[x, y]` or ref | **yes** | Cell to destroy. |
| `layer` | string | **yes** | Layer to remove from. |
| `animation` | string | no | Animation name from the entity kind's `animations` map. Played before removal. |

### `transform`
Change an entity at a position to a different kind. If `animation` is specified, the engine plays the named animation on the source entity before transforming it.

```json
{ "transform": { "position": [3, 2], "layer": "ground", "toKind": "bridge" } }
{ "transform": { "position": [3, 2], "layer": "ground", "toKind": "bridge", "animation": "dissolving" } }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `position` | `[x, y]` or ref | **yes** | Cell to transform. |
| `layer` | string | **yes** | Layer to modify. |
| `toKind` | string | **yes** | New entity kind. |
| `animation` | string | no | Animation name from the source entity kind's `animations` map. Played before transform. |

### `move_entity`
Move an entity from one position to another.

```json
{ "move_entity": { "from": [3, 2], "to": [3, 4], "layer": "objects" } }
```

### `set_cell`
Directly set a cell's content (kind + params).

```json
{ "set_cell": { "position": [3, 2], "layer": "objects", "kind": "number", "value": 7 } }
```

### `release_from_emitter`
Trigger a queued emitter to release its next item.

```json
{ "release_from_emitter": { "emitterId": "pipe_1" } }
```

### `apply_gravity`
Apply gravity to matching entities.

```json
{ "apply_gravity": { "selector": { "tag": "mergeable" }, "direction": "down" } }
```

### `set_variable`
Set a state variable to a value.

```json
{ "set_variable": { "name": "doorsOpen", "value": true } }
```

### `increment_variable`
Increment a numeric variable.

```json
{ "increment_variable": { "name": "gemsCollected", "amount": 1 } }
```

### `set_inventory`
Set the avatar's inventory slot.

```json
{ "set_inventory": { "item": "torch" } }
```

### `clear_inventory`
Empty the avatar's inventory slot.

```json
{ "clear_inventory": {} }
```

### `resolve_move`
Complete a pending avatar move that was blocked (requires a prior `move_blocked` event in this cascade). The avatar moves to the blocked target cell. Emits `avatar_exited` and `avatar_entered`.

```json
{ "resolve_move": {} }
```

No-op if there is no pending move. Typically used after destroying or transforming the blocking entity.

### Effect-emitted events

Effects automatically emit events when they modify state. These events are available in subsequent cascade passes.

| Effect | Events emitted |
|--------|---------------|
| `destroy` | `object_removed`, potentially `cell_cleared` |
| `spawn` | `object_placed` |
| `transform` | `cell_transformed` |
| `set_cell` | `cell_transformed` or `object_placed` |
| `move_entity` | `object_removed` + `object_placed` |
| `set_inventory` | `inventory_changed` |
| `clear_inventory` | `inventory_changed` |
| `resolve_move` | `avatar_exited` + `avatar_entered` |

---

## 6. Cascade Semantics

### Cascade Resolution Loop

During phase 5 (`cascade_resolution`), the engine executes:

```
events = events accumulated from phases 2–4
for pass = 1 to maxCascadeDepth:
    matching_rules = evaluate all rules against events
    if no matching rules: break
    for each rule (sorted by priority desc, then declaration order):
        execute rule.then effects
        collect new events from effects
    run cascade-phase systems (queued_emitters, gravity)
    collect their events
    events = new events only
```

### Loop Termination

The cascade loop terminates when:
- No rules matched in a pass, OR
- `maxCascadeDepth` is reached (default: 3)

This prevents infinite loops. If a game genuinely needs deeper chaining, `maxCascadeDepth` can be increased in `game.json` defaults.

### Priority and Ordering

1. Rules with higher `priority` fire first.
2. Among equal-priority rules, declaration order wins (game-level rules before level-local rules, then by array position within each).
3. A rule with `"once": true` fires at most once per level attempt (tracked across all turns).

---

## 7. Constraint

Rules must **not** contain:
- Arbitrary code strings or expressions
- Embedded scripts
- Custom function references
- Unbounded loops

All conditions and effects use the fixed catalogs defined above. This keeps the DSL safe, deterministic, and analyzable.

---

## 8. Worked Examples

### Example A: Pipe releases number when exit is clear

```json
{
  "id": "pipe_1_release",
  "on": "cell_cleared",
  "where": { "position": [1, 2] },
  "if": { "emitter_has_next": { "emitterId": "pipe_1" } },
  "then": [
    { "release_from_emitter": { "emitterId": "pipe_1" } },
    { "apply_gravity": { "selector": { "tag": "mergeable" }, "direction": "down" } }
  ]
}
```

### Example B: Collecting all gems opens the exit

```json
{
  "id": "all_gems_collected",
  "on": "object_removed",
  "where": { "event": { "kind": "gem" } },
  "if": { "board_count": { "kind": "gem", "op": "eq", "value": 0 } },
  "then": [
    { "spawn": { "position": [4, 4], "layer": "markers", "kind": "exit" } }
  ],
  "once": true
}
```

### Example C: Pressure plate opens door

```json
{
  "id": "plate_activated",
  "on": "avatar_entered",
  "where": { "position": [2, 3] },
  "then": [
    { "destroy": { "position": [5, 1], "layer": "objects" } },
    { "set_variable": { "name": "plateActive", "value": true } }
  ]
}
```

---

## 9. Rule Recipes

Rule recipes are documented patterns that replace what was previously handled by dedicated engine systems. They use the standard rule primitives (events, conditions, effects, value references) and can be copied into a game's `rules` array.

### Recipe A: Single-slot inventory pickup

Replaces `single_slot_inventory` system. The avatar picks up tagged objects on cell entry.

```json
{
  "id": "pickup_item",
  "on": "avatar_entered",
  "where": { "position_has_tag": { "layer": "objects", "tag": "pickup" } },
  "then": [
    { "set_inventory": { "item": "$cell.objects.kind" } },
    { "destroy": { "position": "$event.position", "layer": "objects" } }
  ]
}
```

**Variant — ignore if slot filled:** Add an `if` condition to skip pickup when carrying an item.

```json
{
  "id": "pickup_item_if_empty",
  "on": "avatar_entered",
  "where": { "position_has_tag": { "layer": "objects", "tag": "pickup" } },
  "if": { "avatar": { "hasItem": false } },
  "then": [
    { "set_inventory": { "item": "$cell.objects.kind" } },
    { "destroy": { "position": "$event.position", "layer": "objects" } }
  ]
}
```

### Recipe B: Consumable tool interactions

Replaces `consumable_interactions` system. When avatar movement is blocked, a carried tool can destroy the blocker.

```json
{
  "id": "torch_burns",
  "on": "move_blocked",
  "where": { "position_has_tag": { "layer": "objects", "tag": "burnable" } },
  "then": [
    { "destroy": { "position": "$event.position", "layer": "objects", "animation": "burning" } },
    { "clear_inventory": {} },
    { "resolve_move": {} }
  ]
}
```

```json
{
  "id": "pickaxe_breaks",
  "on": "move_blocked",
  "where": { "position_has_tag": { "layer": "objects", "tag": "breakable" } },
  "then": [
    { "destroy": { "position": "$event.position", "layer": "objects", "animation": "breaking" } },
    { "clear_inventory": {} },
    { "resolve_move": {} }
  ]
}
```

The `resolve_move` effect completes the avatar's pending movement into the now-cleared cell. The cascade produces `avatar_entered`, which can trigger further rules (e.g., Recipe A for pickup).

### Recipe C: Liquid transitions

Replaces `liquid_transitions` system. Handles objects entering liquid and avatar crossing water.

**Object pushed into liquid creates bridge:**

```json
{
  "id": "object_creates_bridge",
  "on": "object_placed",
  "where": { "all_of": [
    { "position_has_tag": { "layer": "ground", "tag": "liquid" } },
    { "position_has_tag": { "layer": "objects", "tag": "pushable" } }
  ]},
  "then": [
    { "destroy": { "position": "$event.position", "layer": "objects" } },
    { "transform": { "position": "$event.position", "layer": "ground", "toKind": "bridge" } }
  ]
}
```

**Water crossing clears inventory:**

```json
{
  "id": "water_clears_items",
  "on": "avatar_entered",
  "where": { "position_has_tag": { "layer": "ground", "tag": "liquid" } },
  "if": { "avatar": { "hasItem": true } },
  "then": [
    { "clear_inventory": {} }
  ]
}
```

### Why recipes, not systems?

These patterns are simple reactive logic — an event happens, a condition is checked, state is modified. This is exactly what rules are for. Expressing them as rules:

- **Makes them visible and modifiable** in game.json (game authors can adjust, extend, or omit them)
- **Removes implicit behavior** that was hidden inside engine systems
- **Reduces the system count** without losing expressiveness
- **Allows per-game variation** (e.g., water that heals instead of clearing inventory)
