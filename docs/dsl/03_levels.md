# Gridponder DSL v0 — Level Schema

## Purpose

Each level file defines one puzzle instance: its board layout, initial state, goals, and solution. Level files live in the levels directory and are referenced by `levelSequence` in `game.json`.

---

## Top-Level Structure

```json
{
  "id": "fw_004",
  "title": "Water and Metal",

  "board": { ... },
  "state": { ... },
  "goals": [ ... ],
  "loseConditions": [ ... ],
  "rules": [ ... ],
  "systemOverrides": { ... },
  "solution": { ... },
  "metadata": { ... }
}
```

---

## Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | **yes** | Unique level identifier. Must match the `ref` in `levelSequence`. |
| `title` | string | no | Human-readable level name. |
| `board` | object | **yes** | Board definition: size, layers, and multi-cell objects. |
| `state` | object | **yes** | Initial runtime state: avatar, variables. |
| `goals` | array | **yes** | Win conditions. At least one required. |
| `loseConditions` | array | no | Lose conditions. Empty by default. |
| `rules` | array | no | Level-local rules. Appended to game-level rules. |
| `systemOverrides` | object | no | Per-system config overrides for this level. |
| `solution` | object | **yes** | Gold path and hint stops. |
| `metadata` | object | no | Description, difficulty, author notes. |

---

## Board

### Structure

```json
"board": {
  "size": [7, 5],
  "layers": {
    "ground": [ ... ],
    "objects": [ ... ],
    "markers": [ ... ],
    "actors": [ ... ]
  },
  "multiCellObjects": [ ... ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `size` | `[width, height]` | **yes** | Board dimensions. |
| `layers` | object | **yes** | Layer data keyed by layer `id`. |
| `multiCellObjects` | array | no | Multi-cell object definitions. |

### Layer Data Formats

Each layer supports two formats: **dense** (2D matrix) or **sparse** (entry list).

#### Dense Format

A 2D array with dimensions matching `board.size`. Row-major order: `layers.ground[y][x]`.

Each cell is one of:
- `null` — empty (for `zero_or_one` layers)
- `"kind_name"` — entity kind reference (no parameters)
- `{ "kind": "kind_name", "param1": value, ... }` — entity with parameters

```json
"ground": [
  ["empty", "empty", "water", "empty", "empty"],
  ["empty", "empty", "water", "empty", "empty"],
  ["empty", "empty", "empty", "empty", "empty"]
]
```

```json
"objects": [
  [null, "rock", null, null, null],
  [null, null, null, {"kind": "portal", "channel": "blue"}, null],
  ["torch", null, null, {"kind": "portal", "channel": "blue"}, "metal_crate"]
]
```

#### Sparse Format

An object with `"format": "sparse"` and an `entries` array. Useful when a layer is mostly empty.

```json
"objects": {
  "format": "sparse",
  "entries": [
    { "position": [1, 0], "kind": "rock" },
    { "position": [3, 1], "kind": "portal", "channel": "blue" },
    { "position": [0, 2], "kind": "torch" },
    { "position": [3, 2], "kind": "portal", "channel": "blue" },
    { "position": [4, 2], "kind": "metal_crate" }
  ]
}
```

The engine normalizes both formats to the same internal representation. Dense is the default; sparse is an authoring convenience.

**Rule:** A layer is dense if its value is an array, and sparse if its value is an object with `"format": "sparse"`.

### Void vs. Empty

- `"empty"` — playable floor cell. Avatar and objects can occupy it.
- `"void"` — non-playable area. Rendered as absent. Nothing can enter or interact with void cells.

Ground layers should use `"void"` for cells outside the playable region. Other layers use `null` for absent content.

### Multi-Cell Objects

Objects that span multiple cells or have internal state beyond what a single entity can express.

```json
"multiCellObjects": [
  {
    "id": "pipe_1",
    "kind": "pipe",
    "cells": [[0,0], [0,1], [0,2]],
    "params": {
      "queue": [5, 7],
      "exitPosition": [1, 2],
      "exitDirection": "down"
    }
  }
]
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | **yes** | Unique identifier for this object instance. Referenced by rules and systems. |
| `kind` | string | **yes** | Multi-cell object kind (e.g., `"pipe"`). |
| `cells` | array of `[x,y]` | **yes** | All cells this object occupies. |
| `params` | object | no | Kind-specific parameters (queue contents, exit position, etc.). |

Multi-cell objects are rendered on the `structures` layer by default.

---

## State

Initial runtime state of the level.

```json
"state": {
  "avatar": {
    "enabled": true,
    "position": [1, 3],
    "facing": "right",
    "inventory": { "slot": null }
  },
  "variables": {
    "gemsCollected": 0
  },
  "overlay": {
    "position": [0, 0],
    "size": [2, 2]
  }
}
```

### Avatar

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `enabled` | boolean | no | Whether the avatar is active. Default from `game.json` defaults. |
| `position` | `[x, y]` | conditional | Starting position. Required if `enabled` is `true`. |
| `facing` | string | no | Initial facing direction. Default from `game.json` defaults. |
| `inventory` | object | no | Initial inventory state. |
| `inventory.slot` | string or null | no | Currently held item kind, or `null` for empty. |

### Variables

Key-value pairs for tracking game state beyond the board. Types: integers, strings, booleans.

Variables can be read by rule conditions and modified by rule effects. Systems can also reference variables.

### Overlay

If the game uses an `overlay_cursor` system, initial overlay state is defined here.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `position` | `[x, y]` | **yes** | Top-left corner of the overlay. |
| `size` | `[w, h]` | **yes** | Overlay dimensions (e.g., `[2,2]` or `[3,3]`). |

---

## Goals

Win conditions for the level. The level is complete when **all** goals are satisfied simultaneously.

```json
"goals": [
  {
    "id": "main",
    "type": "reach_target",
    "config": { "targetKind": "flag" }
  }
]
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | **yes** | Unique goal identifier. |
| `type` | string | **yes** | Goal type. See below. |
| `config` | object | **yes** | Type-specific configuration. |
| `display` | object | no | Text or icon for the UI rules panel. |

### Partial Progress Tracking

The engine tracks **partial progress** for each goal so the UI can visualize how close the player is to completion. This is engine-internal behavior — not configured in the DSL — but goal types are designed to support it:

- `reach_target`: binary (reached or not).
- `sequence_match`: progress = number of sequence steps completed / total steps.
- `board_match`: progress = number of matching cells / total non-null target cells.
- `variable_threshold`: progress = current value / target value (clamped to 0–1).
- `all_cleared`: progress = 1 − (remaining matching entities / initial count).

### Goal Types

#### `reach_target`
Avatar reaches a cell containing the specified kind.

```json
{ "type": "reach_target", "config": { "targetKind": "flag" } }
```

| Config Field | Type | Description |
|-------------|------|-------------|
| `targetKind` | string | Entity kind the avatar must reach. |
| `targetTag` | string | Alternative: match any entity with this tag. |

#### `sequence_match`
Complete an ordered sequence of target values. Each step is satisfied when a matching value exists on the board (or is collected). Satisfied steps are consumed. The engine evaluates this during goal evaluation phase — no separate system needed.

```json
{ "type": "sequence_match", "config": {
    "sequence": [4, 5, 6],
    "matchBy": "exists_on_board",
    "consumeOnMatch": true,
    "scanTrigger": "turn_end"
}}
```

| Config Field | Type | Description |
|-------------|------|-------------|
| `sequence` | array | Ordered list of target values. |
| `matchBy` | string | `"exists_on_board"` or `"collected_by_avatar"`. |
| `consumeOnMatch` | boolean | Remove matched entity from board. Default: `true`. |
| `scanTrigger` | string | When to scan: `"turn_end"` (default) or `"on_merge"` (scan after each merge event). |

**Engine behavior:** At the scan trigger, the engine scans the board for the current target value in the sequence. If found: removes the entity (if `consumeOnMatch`), advances the sequence index, and emits `goal_step_completed`. The UI uses the sequence index as partial progress.

#### `board_match`
Board state matches a target pattern.

```json
{ "type": "board_match", "config": {
    "targetLayers": {
      "objects": [
        [null, {"kind":"colored","color":"red"}, null],
        [null, null, null]
      ]
    },
    "matchMode": "exact_non_null"
}}
```

| Config Field | Type | Description |
|-------------|------|-------------|
| `targetLayers` | object | Layer data in the same format as board layers. |
| `matchMode` | string | `"exact"` (all cells match), `"exact_non_null"` (only non-null target cells must match). Default: `"exact_non_null"`. |

#### `variable_threshold`
A variable reaches or exceeds a target value.

```json
{ "type": "variable_threshold", "config": { "variable": "gemsCollected", "target": 5, "comparison": "gte" } }
```

| Config Field | Type | Description |
|-------------|------|-------------|
| `variable` | string | Variable name from `state.variables`. |
| `target` | integer | Target value. |
| `comparison` | string | `"eq"`, `"gte"`, `"lte"`. Default: `"gte"`. |

#### `all_cleared`
All entities matching a selector are removed from the board.

```json
{ "type": "all_cleared", "config": { "kind": "monster" } }
```

---

## Lose Conditions

Optional conditions that cause the level to fail.

```json
"loseConditions": [
  { "type": "max_actions", "config": { "limit": 15 } },
  { "type": "variable_threshold", "config": { "variable": "damage", "target": 3, "comparison": "gte" } }
]
```

### Lose Condition Types

#### `max_actions`
Player exceeds a maximum number of actions.

#### `variable_threshold`
Same as the goal type but triggers a loss.

#### `board_state`
A specific board condition is detected (e.g., an entity reaches a forbidden cell).

---

## System Overrides

Per-level overrides for system configurations defined in `game.json`. Only the specified fields are overridden; all other config is inherited.

```json
"systemOverrides": {
  "movement": {
    "directions": ["up", "down", "left", "right", "up_left", "up_right"]
  },
  "push": {
    "chainPush": true
  }
}
```

Keys match the system `id` from `game.json`. Values are partial config objects merged on top of the game-level config.

---

## Rules (Level-Local)

Level-specific rules appended after game-level rules. Same format as game-level rules. See [05_rules.md](05_rules.md).

```json
"rules": [
  {
    "id": "pipe_release",
    "on": "cell_cleared",
    "where": { "position": [1, 2] },
    "if": { "emitter_has_next": { "emitterId": "pipe_1" } },
    "then": [
      { "release_from_emitter": { "emitterId": "pipe_1" } },
      { "apply_gravity": { "selector": { "tag": "mergeable" }, "direction": "down" } }
    ]
  }
]
```

---

## Solution

The gold path and hint system.

```json
"solution": {
  "goldPath": [
    { "action": "move", "direction": "right" },
    { "action": "move", "direction": "down" },
    { "action": "move", "direction": "right" },
    { "action": "move", "direction": "down" },
    { "action": "move", "direction": "right" }
  ],
  "hintStops": [2, 4]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `goldPath` | array | **yes** | Sequence of actions forming the intended solution. |
| `hintStops` | array of integers | no | Action counts for each hint level. Strictly increasing. Max: 3 in v0. |

### Gold Path Entry

Each entry is an action with its parameters:

```json
{ "action": "move", "direction": "right" }
{ "action": "diagonal_swap", "direction": "up_right" }
{ "action": "rotate", "rotation": "clockwise" }
{ "action": "flood" }
```

### Hint System

- Hint stops indicate how many gold path actions to replay for each hint level.
- Example: `"hintStops": [2, 5, 8]` means hint 1 replays 2 actions, hint 2 replays 5, hint 3 replays 8.
- Hints are time-gated by the platform (not the DSL). The DSL only defines the content.

### Validation Rules

1. `hintStops` must be strictly increasing: `stops[i] < stops[i+1]`.
2. Every stop must be `<= goldPath.length`.
3. Maximum 3 hint stops in v0.
4. Each gold path action must be a valid action type for this game.
5. Replaying the gold path from the initial state must reach a goal state.

---

## Metadata

Optional level metadata for tooling, search, and display.

```json
"metadata": {
  "description": "Learn how metal crates create bridges over water.",
  "difficulty": 2,
  "tags": ["water", "crate", "bridge"],
  "authorNotes": "The intended aha moment is realizing the crate must be pushed into water before crossing."
}
```

---

## Complete Example — Flag Level

```json
{
  "id": "fw_004",
  "title": "Water and Metal",

  "board": {
    "size": [5, 5],
    "layers": {
      "ground": [
        ["empty", "empty", "empty", "empty", "empty"],
        ["empty", "empty", "water", "empty", "empty"],
        ["empty", "empty", "water", "empty", "empty"],
        ["empty", "empty", "empty", "empty", "empty"],
        ["empty", "empty", "empty", "empty", "empty"]
      ],
      "objects": [
        [null, null, null, null, null],
        [null, "metal_crate", null, null, null],
        [null, null, null, null, null],
        [null, null, null, null, null],
        [null, null, null, null, null]
      ],
      "markers": [
        [null, null, null, null, null],
        [null, null, null, null, null],
        [null, null, null, null, null],
        [null, null, null, null, "flag"],
        [null, null, null, null, null]
      ]
    }
  },

  "state": {
    "avatar": {
      "enabled": true,
      "position": [0, 1],
      "facing": "right",
      "inventory": { "slot": null }
    },
    "variables": {}
  },

  "goals": [
    { "id": "reach_flag", "type": "reach_target", "config": { "targetKind": "flag" } }
  ],

  "solution": {
    "goldPath": [
      { "action": "move", "direction": "right" },
      { "action": "move", "direction": "right" },
      { "action": "move", "direction": "down" },
      { "action": "move", "direction": "down" },
      { "action": "move", "direction": "right" },
      { "action": "move", "direction": "right" }
    ],
    "hintStops": [2, 4]
  },

  "metadata": {
    "description": "Push the metal crate into water to create a bridge.",
    "difficulty": 2
  }
}
```

## Complete Example — Number Slide Level

```json
{
  "id": "nc_002",
  "title": "First Merge",

  "board": {
    "size": [4, 4],
    "layers": {
      "ground": [
        ["empty", "empty", "empty", "empty"],
        ["empty", "empty", "empty", "empty"],
        ["empty", "empty", "empty", "empty"],
        ["empty", "empty", "empty", "empty"]
      ],
      "objects": {
        "format": "sparse",
        "entries": [
          { "position": [0, 0], "kind": "number", "value": 2 },
          { "position": [2, 0], "kind": "number", "value": 2 },
          { "position": [1, 2], "kind": "number", "value": 3 }
        ]
      }
    }
  },

  "state": {
    "avatar": { "enabled": false },
    "variables": {}
  },

  "goals": [
    { "id": "sequence", "type": "sequence_match", "config": {
        "sequence": [4, 3],
        "matchBy": "exists_on_board",
        "consumeOnMatch": true
    }}
  ],

  "loseConditions": [
    { "type": "max_actions", "config": { "limit": 5 } }
  ],

  "solution": {
    "goldPath": [
      { "action": "move", "direction": "right" },
      { "action": "move", "direction": "down" }
    ],
    "hintStops": [1]
  }
}
```
