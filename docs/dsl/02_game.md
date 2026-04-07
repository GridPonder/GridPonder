# Gridponder DSL v0 — Game Schema

## Purpose

`game.json` contains all gameplay content shared across levels: entity kinds, systems, actions, rules, defaults, and the level sequence. It does **not** repeat identity or presentation metadata — those live exclusively in `manifest.json`.

Visual presentation and input bindings are defined separately in `theme.json` — see [06_theme.md](06_theme.md).

---

## Top-Level Structure

```json
{
  "layers": [ ... ],
  "actions": [ ... ],
  "entityKinds": { ... },
  "systems": [ ... ],
  "rules": [ ... ],
  "levelSequence": [ ... ],
  "defaults": { ... }
}
```

---

## Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `layers` | array | **yes** | Board layer definitions. |
| `actions` | array | **yes** | Available player action types. |
| `entityKinds` | object | **yes** | Catalog of entity kind definitions. |
| `systems` | array | **yes** | Enabled engine systems with configuration. |
| `rules` | array | no | Game-level rules (shared across levels). |
| `levelSequence` | array | **yes** | Ordered list of levels and story screens. |
| `defaults` | object | no | Default values for level fields. |

---

## Layers

Defines the board's layer stack. Each layer has a name and occupancy rule.

```json
"layers": [
  { "id": "ground",   "occupancy": "exactly_one", "default": "empty" },
  { "id": "objects",   "occupancy": "zero_or_one" },
  { "id": "markers",   "occupancy": "zero_or_one" },
  { "id": "actors",    "occupancy": "zero_or_one" },
  { "id": "structures","occupancy": "zero_or_one" }
]
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | **yes** | Layer identifier. |
| `occupancy` | string | **yes** | `"exactly_one"` (every cell has a value) or `"zero_or_one"` (cells may be null). |
| `default` | string | no | Default cell value for `exactly_one` layers. Default: `"empty"`. |

The layer order defines rendering order (first = bottom). The avatar is not part of any layer — it is rendered separately on top.

---

## Actions

Declares the abstract action types available in this game.

```json
"actions": [
  {
    "id": "move",
    "params": { "direction": { "type": "direction", "values": ["up", "down", "left", "right"] } }
  },
  {
    "id": "diagonal_swap",
    "params": { "direction": { "type": "direction", "values": ["up_left", "up_right", "down_left", "down_right"] } }
  },
  {
    "id": "rotate",
    "params": { "rotation": { "type": "enum", "values": ["clockwise", "counterclockwise"] } }
  },
  {
    "id": "flip",
    "params": { "axis": { "type": "enum", "values": ["vertical", "horizontal"] } }
  },
  {
    "id": "flood",
    "params": {}
  },
  {
    "id": "tap_cell",
    "params": { "position": { "type": "position" } }
  }
]
```

Each action:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | **yes** | Unique action identifier. Referenced by controls and systems. |
| `params` | object | **yes** | Parameter definitions. Keys are param names, values describe the type. |

Parameter types:
- `direction` — a direction value from the given `values` list
- `position` — a `[x, y]` board coordinate
- `enum` — one of the given `values`
- `integer` — an integer value

---

## Entity Kinds

Defines all entity types used by this game. Levels reference kinds by their key name.

```json
"entityKinds": {
  "empty": {
    "layer": "ground",
    "tags": ["walkable"],
    "sprite": null,
    "description": "Walkable floor"
  },
  "void": {
    "layer": "ground",
    "tags": [],
    "sprite": "assets/sprites/void.png",
    "description": "Non-playable area"
  },
  "wall": {
    "layer": "ground",
    "tags": ["solid"],
    "sprite": "assets/sprites/wall.png"
  },
  "water": {
    "layer": "ground",
    "tags": ["liquid", "walkable"],
    "sprite": "assets/sprites/water.png"
  },
  "rock": {
    "layer": "objects",
    "tags": ["solid", "breakable"],
    "sprite": "assets/sprites/rock.png"
  },
  "wood": {
    "layer": "objects",
    "tags": ["solid", "burnable", "pushable"],
    "sprite": "assets/sprites/wood.png"
  },
  "torch": {
    "layer": "objects",
    "tags": ["pickup"],
    "sprite": "assets/sprites/torch.png"
  },
  "pickaxe": {
    "layer": "objects",
    "tags": ["pickup"],
    "sprite": "assets/sprites/pickaxe.png"
  },
  "metal_crate": {
    "layer": "objects",
    "tags": ["solid", "pushable"],
    "sprite": "assets/sprites/metal_crate.png"
  },
  "flag": {
    "layer": "markers",
    "tags": ["goal_target"],
    "sprite": "assets/sprites/flag.png"
  },
  "portal": {
    "layer": "objects",
    "tags": ["teleport"],
    "sprite": "assets/sprites/portal.png",
    "params": { "channel": { "type": "string", "required": true } }
  },
  "number": {
    "layer": "objects",
    "tags": ["mergeable"],
    "sprite": "assets/sprites/number.png",
    "params": { "value": { "type": "integer", "required": true } }
  },
  "spirit": {
    "layer": "actors",
    "tags": ["npc"],
    "sprite": "assets/sprites/spirit.png",
    "params": {
      "behavior": { "type": "string", "required": true },
      "targetTag": { "type": "string" }
    }
  },
  "colored": {
    "layer": "objects",
    "tags": ["pushable"],
    "sprite": "assets/sprites/colored.png",
    "params": { "color": { "type": "string", "required": true } }
  }
}
```

### Entity Kind Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `layer` | string | **yes** | Which board layer this kind belongs to. Must reference a defined layer. |
| `tags` | array of strings | **yes** | Semantic labels. Systems use tags for entity selection. |
| `sprite` | string or null | no | Path to sprite asset. `null` means invisible/transparent. |
| `symbol` | string | **yes** | Single Unicode character used in text grid representations (`TextRenderer`). Must be unique within a game; `@` is reserved for the avatar. Use narrow (display-width 1) characters only — basic ASCII, box-drawing (`═║╬`), math symbols (`≈`), or similar. Wide characters (emoji, CJK) break grid alignment and must not be used. |
| `symbolParam` | string | no | If set, the symbol is taken from this instance parameter at render time instead of `symbol`. Used for entities whose symbol varies by value (e.g. number tiles show their numeric digit). `symbol` acts as the legend label and fallback. |
| `params` | object | no | Parameterized fields that instances may set. Each param defines its `type` and optionally `required`. |
| `description` | string | no | Human-readable description. |
| `uiName` | string | no | Display name for UI. Defaults to the kind key. |
| `animations` | object | no | Named animation sequences for this entity. See [Animations](#animations). |
| `render` | object | no | Additional rendering hints (opacity, tint). |

### Animations

Entity kinds may define named **animation sequences** triggered by effects or systems. Each animation is a named key mapping to a frame sequence.

```json
"wood": {
  "layer": "objects",
  "tags": ["solid", "burnable", "pushable"],
  "sprite": "assets/sprites/wood.png",
  "animations": {
    "burning": {
      "frames": ["assets/sprites/wood_fire_ignites.png", "assets/sprites/wood_full_burn.png", "assets/sprites/wood_smoke_and_ash.png"],
      "duration": 1500,
      "mode": "once"
    }
  }
}
```

```json
"rock": {
  "layer": "objects",
  "tags": ["solid", "breakable"],
  "sprite": "assets/sprites/rock.png",
  "animations": {
    "breaking": {
      "frames": ["assets/sprites/rock_with_cracks.png", "assets/sprites/rock_broken.png"],
      "duration": 1000,
      "mode": "once"
    }
  }
}
```

Animation fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `frames` | array of strings | **yes** | Ordered sprite paths. Played sequentially. |
| `duration` | integer | **yes** | Total animation duration in milliseconds. Divided evenly across frames. |
| `mode` | string | no | `"once"` (default) — plays once. `"loop"` — repeats until state changes. |

Effects reference animations by name via the `animation` field (see [05_rules.md §5](05_rules.md#5-effect-catalog)). When an effect specifies an animation, the engine plays it before (or during) the state change. If no animation is specified, the state change is instant.

The animation name is scoped to the entity kind at the target position. For example, `"animation": "burning"` on a `destroy` effect at a cell containing `wood` looks up `wood.animations.burning`.

---

### Tags

Tags are simple semantic labels. They do not carry behavior on their own — systems read tags to decide what to do.

Standard tags for v0:

| Tag | Meaning |
|-----|---------|
| `solid` | Blocks avatar movement (unless a system handles the interaction) |
| `walkable` | Avatar can enter this cell |
| `pickup` | Can be picked up by avatar |
| `pushable` | Can be pushed by avatar |
| `breakable` | Can be destroyed by a tool |
| `burnable` | Can be burned by a fire tool |
| `liquid` | A terrain type with liquid behavior |
| `bridge` | Walkable surface created over liquid |
| `teleport` | Triggers portal system |
| `mergeable` | Can be merged with matching entities |
| `goal_target` | Target for reach-type goals |
| `npc` | Non-player character with autonomous behavior |
| `target_marker` | Non-blocking marker for NPC targeting |

Games may define custom tags beyond these.

### Multi-Cell Object Kinds

Multi-cell objects (e.g., pipes) referenced in level `multiCellObjects` arrays should also have an entity kind definition in `entityKinds`. The kind defines tags, sprite, and parameter schema. The `layer` for multi-cell objects is typically `"structures"`.

```json
"pipe": {
  "layer": "structures",
  "tags": ["emitter"],
  "sprite": "assets/sprites/pipe.png",
  "params": {
    "queue": { "type": "array", "required": true },
    "exitPosition": { "type": "position", "required": true },
    "exitDirection": { "type": "string" }
  }
}
```

---

## Systems

Declares which engine systems are active and their configuration.

```json
"systems": [
  {
    "id": "movement",
    "type": "avatar_navigation",
    "config": {
      "directions": ["up", "down", "left", "right"],
      "solidHandling": "delegate"
    }
  },
  {
    "id": "push",
    "type": "push_objects",
    "config": {
      "pushableTags": ["pushable"],
      "chainPush": false
    }
  }
]
```

Each system entry:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | **yes** | Unique instance identifier for this system. Used by levels for overrides. |
| `type` | string | **yes** | Built-in system type. See [System Catalog](04_systems.md). |
| `config` | object | **yes** | System-specific configuration. |
| `enabled` | boolean | no | Whether the system is active. Default: `true`. |

See [04_systems.md](04_systems.md) for the complete system type catalog and config schemas.

---

## Rules (Game-Level)

Game-level rules apply to all levels unless overridden. See [05_rules.md](05_rules.md) for the full rules model.

```json
"rules": [
  {
    "id": "water_clears_inventory",
    "on": "avatar_entered",
    "where": { "position_has_tag": { "layer": "ground", "tag": "liquid" } },
    "if": { "avatar": { "hasItem": true } },
    "then": [
      { "clear_inventory": {} }
    ]
  }
]
```

---

## Level Sequence

An ordered list defining the game's playable progression. Entries are either level references or story screens.

```json
"levelSequence": [
  { "type": "story", "title": "Chapter 1", "text": "The rabbit sets out on a journey...", "image": "assets/story/intro.png" },
  { "type": "level", "ref": "fw_001" },
  { "type": "level", "ref": "fw_002" },
  { "type": "story", "text": "The rabbit reaches the river...", "image": "assets/story/river.png" },
  { "type": "level", "ref": "fw_003" },
  { "type": "level", "ref": "fw_004" },
  { "type": "story", "text": "Victory!", "image": "assets/story/victory.png" }
]
```

### Level Entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"level"` | **yes** | Marks this as a level. |
| `ref` | string | **yes** | Level `id`. Must match a file in the levels directory. |

### Story Entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"story"` | **yes** | Marks this as a story screen. |
| `title` | string | no | Optional heading text. |
| `text` | string | no | Body text. |
| `image` | string | no | Path to an illustration. |

At least one of `text` or `image` must be present. Story screens are displayed between levels and dismissed by tapping.

---

## Defaults

Default values applied to levels when those fields are not specified. This reduces repetition.

```json
"defaults": {
  "avatar": {
    "enabled": true,
    "facing": "right",
    "inventory": { "slot": null }
  },
  "maxCascadeDepth": 3
}
```

| Field | Type | Description |
|-------|------|-------------|
| `avatar` | object | Default avatar configuration. Levels can override. |
| `maxCascadeDepth` | integer | Maximum cascade passes during rule resolution. Default: `3`. |

---

## Complete Example

```json
{
  "id": "com.gridponder.flag_worlds",
  "dslVersion": "0.1.0",
  "title": "Flag Worlds",
  "description": "Guide the rabbit to the flag using tools, crates, and portals.",

  "layers": [
    { "id": "ground",  "occupancy": "exactly_one", "default": "empty" },
    { "id": "objects",  "occupancy": "zero_or_one" },
    { "id": "markers",  "occupancy": "zero_or_one" },
    { "id": "actors",   "occupancy": "zero_or_one" }
  ],

  "actions": [
    { "id": "move", "params": { "direction": { "type": "direction", "values": ["up","down","left","right"] } } }
  ],

  "entityKinds": {
    "empty": { "layer": "ground", "tags": ["walkable"], "sprite": null },
    "void":  { "layer": "ground", "tags": [], "sprite": "assets/sprites/void.png" },
    "wall":  { "layer": "ground", "tags": ["solid"], "sprite": "assets/sprites/wall.png" },
    "water": { "layer": "ground", "tags": ["liquid", "walkable"], "sprite": "assets/sprites/water.png" },
    "bridge":{ "layer": "ground", "tags": ["walkable"], "sprite": "assets/sprites/bridge.png" },
    "rock":  { "layer": "objects", "tags": ["solid", "breakable"], "sprite": "assets/sprites/rock.png",
               "animations": { "breaking": { "frames": ["assets/sprites/rock_with_cracks.png", "assets/sprites/rock_broken.png"], "duration": 1000, "mode": "once" } } },
    "wood":  { "layer": "objects", "tags": ["solid", "burnable", "pushable"], "sprite": "assets/sprites/wood.png",
               "animations": { "burning": { "frames": ["assets/sprites/wood_fire_ignites.png", "assets/sprites/wood_full_burn.png", "assets/sprites/wood_smoke_and_ash.png"], "duration": 1500, "mode": "once" } } },
    "torch": { "layer": "objects", "tags": ["pickup"], "sprite": "assets/sprites/torch.png" },
    "pickaxe": { "layer": "objects", "tags": ["pickup"], "sprite": "assets/sprites/pickaxe.png" },
    "metal_crate": { "layer": "objects", "tags": ["solid", "pushable"], "sprite": "assets/sprites/metal_crate.png" },
    "flag":  { "layer": "markers", "tags": ["goal_target"], "sprite": "assets/sprites/flag.png" },
    "portal": { "layer": "objects", "tags": ["teleport"], "sprite": "assets/sprites/portal.png",
                "params": { "channel": { "type": "string", "required": true } } }
  },

  "systems": [
    { "id": "movement", "type": "avatar_navigation", "config": { "directions": ["up","down","left","right"], "solidHandling": "delegate" } },
    { "id": "push", "type": "push_objects", "config": { "pushableTags": ["pushable"], "chainPush": false } },
    { "id": "portals", "type": "portals", "config": { "teleportTags": ["teleport"], "matchKey": "channel", "endMovement": true } }
  ],

  "rules": [
    {
      "id": "pickup_item",
      "on": "avatar_entered",
      "where": { "position_has_tag": { "layer": "objects", "tag": "pickup" } },
      "then": [
        { "set_inventory": { "item": "$cell.objects.kind" } },
        { "destroy": { "position": "$event.position", "layer": "objects" } }
      ]
    },
    {
      "id": "torch_burns",
      "on": "move_blocked",
      "where": { "position_has_tag": { "layer": "objects", "tag": "burnable" } },
      "if": { "avatar": { "hasItem": "torch" } },
      "then": [
        { "destroy": { "position": "$event.position", "layer": "objects", "animation": "burning" } },
        { "clear_inventory": {} },
        { "resolve_move": {} }
      ]
    },
    {
      "id": "pickaxe_breaks",
      "on": "move_blocked",
      "where": { "position_has_tag": { "layer": "objects", "tag": "breakable" } },
      "if": { "avatar": { "hasItem": "pickaxe" } },
      "then": [
        { "destroy": { "position": "$event.position", "layer": "objects", "animation": "breaking" } },
        { "clear_inventory": {} },
        { "resolve_move": {} }
      ]
    },
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
    },
    {
      "id": "water_clears_items",
      "on": "avatar_entered",
      "where": { "position_has_tag": { "layer": "ground", "tag": "liquid" } },
      "if": { "avatar": { "hasItem": true } },
      "then": [
        { "clear_inventory": {} }
      ]
    }
  ],

  "levelSequence": [
    { "type": "level", "ref": "fw_001" },
    { "type": "level", "ref": "fw_002" },
    { "type": "level", "ref": "fw_003" }
  ],

  "defaults": {
    "avatar": { "enabled": true, "facing": "right", "inventory": { "slot": null } },
    "maxCascadeDepth": 3
  }
}
```
