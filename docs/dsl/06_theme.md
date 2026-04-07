# Gridponder DSL v0 — Theme & Controls Schema

## Purpose

`theme.json` defines the visual presentation and input bindings for a game: colors, board rendering, avatar appearance, text styling, and gesture-to-action mapping. Theme data is **non-normative** — it does not affect gameplay semantics. Engine implementations may override or extend theme settings for their platform.

Input bindings live here (rather than in `game.json`) because the same game actions need different physical inputs on different platforms — swipes on mobile, arrow keys on desktop/web, d-pad on gamepad. The game declares *what* actions exist (in `game.json`); the theme declares *how* the player triggers them.

A game pack includes one `theme.json` alongside `game.json`. If omitted, the engine applies sensible defaults.

---

## Top-Level Structure

```json
{
  "controls": { ... },
  "coverImage": "assets/cover.png",
  "primaryColor": "#4CAF50",
  "backgroundColor": "#1A1A2E",
  "boardStyle": { ... },
  "textStyle": { ... },
  "avatar": { ... }
}
```

---

## Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `controls` | object | no | Input bindings — gesture/key to action mapping. |
| `coverImage` | string | no | Path to cover art for the library screen. |
| `primaryColor` | string | no | Primary accent color (hex). |
| `backgroundColor` | string | no | Background color (hex). |
| `boardStyle` | object | no | Board rendering settings. |
| `textStyle` | object | no | Text rendering settings. |
| `avatar` | object | no | Avatar appearance settings. |

---

## Controls

Maps platform inputs to abstract game actions. The engine uses these bindings as defaults; platforms may override them.

```json
"controls": {
  "gestureMap": [
    { "gesture": "swipe_cardinal", "action": "move", "paramMapping": { "direction": "swipe_direction" } },
    { "gesture": "swipe_diagonal", "action": "diagonal_swap", "paramMapping": { "direction": "swipe_direction" } },
    { "gesture": "tap_cell", "action": "tap_cell", "paramMapping": { "position": "tap_position" } },
    { "gesture": "button", "buttonId": "rotate_cw", "action": "rotate", "params": { "rotation": "clockwise" } }
  ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `gestureMap` | array | **yes** | List of input-to-action bindings. |

Each gesture mapping:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `gesture` | string | **yes** | Input type: `swipe_cardinal`, `swipe_diagonal`, `tap_cell`, `button`. |
| `action` | string | **yes** | Action `id` to emit. Must match an entry in `game.json` `actions`. |
| `buttonId` | string | conditional | Required when `gesture` is `button`. UI control identifier. |
| `paramMapping` | object | no | Maps input parameters to action parameters dynamically. |
| `params` | object | no | Static parameters to include with the action. |

**Platform behavior:** On mobile, gestures are used directly. On web/desktop, the engine maps arrow keys to `swipe_cardinal` equivalents, and provides on-screen buttons for `button`-type actions. Games can provide platform-specific overrides (future extension).

---

## Board Style

```json
"boardStyle": {
  "cellSize": 64,
  "cellSpacing": 2,
  "borderRadius": 4,
  "gridLineColor": "#333333",
  "showGridLines": true
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `cellSize` | integer | `64` | Suggested cell size in logical pixels. |
| `cellSpacing` | integer | `2` | Gap between cells. |
| `borderRadius` | integer | `4` | Cell corner radius. |
| `gridLineColor` | string | `"#333333"` | Grid line color (hex). |
| `showGridLines` | boolean | `true` | Whether to show grid lines. |

---

## Text Style

```json
"textStyle": {
  "fontFamily": "default",
  "titleColor": "#FFFFFF",
  "bodyColor": "#CCCCCC"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `fontFamily` | string | `"default"` | Font family name or `"default"` for platform font. |
| `titleColor` | string | `"#FFFFFF"` | Title text color (hex). |
| `bodyColor` | string | `"#CCCCCC"` | Body text color (hex). |

---

## Avatar

The avatar section defines the character's appearance. It supports a simple single-sprite mode and a full **sprite map** for directional and animated avatars.

### Simple mode

```json
"avatar": {
  "sprite": "assets/sprites/rabbit.png",
  "visible": true
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sprite` | string | (engine default) | Fallback sprite. Used when no sprite map is provided, or as default for missing states. |
| `visible` | boolean | `true` | Whether avatar is rendered. Set to `false` for overlay-only games. |

### Sprite map mode

For games with directional movement, the avatar should use a **sprite map** keyed by `state` and `direction`. States are emitted by systems during gameplay (e.g., `avatar_navigation` sets `"moving"`, `push_objects` sets `"pushing"`).

```json
"avatar": {
  "visible": true,
  "sprites": {
    "idle": {
      "right": "assets/sprites/avatar/rabbit_looking_right.png",
      "left": "assets/sprites/avatar/rabbit_looking_slightly_left.png",
      "up": "assets/sprites/avatar/rabbit_idle_away_from_player.png",
      "down": "assets/sprites/avatar/rabbit_idle_facing_player.png"
    },
    "moving": {
      "right": {
        "frames": ["assets/sprites/avatar/rabbit_walking_right_1.png", "assets/sprites/avatar/rabbit_walking_right_2.png"],
        "duration": 400,
        "mode": "loop"
      },
      "left": { "mirror": "right" },
      "up": {
        "frames": ["assets/sprites/avatar/rabbit_walking_up_1.png", "assets/sprites/avatar/rabbit_walking_up_2.png"],
        "duration": 400,
        "mode": "loop"
      },
      "down": {
        "frames": ["assets/sprites/avatar/rabbit_walking_down_1.png", "assets/sprites/avatar/rabbit_walking_down_2.png"],
        "duration": 400,
        "mode": "loop"
      }
    },
    "pushing": {
      "right": {
        "frames": ["assets/sprites/avatar/rabbit_push_start.png", "assets/sprites/avatar/rabbit_push_right_middle.png", "assets/sprites/avatar/rabbit_push_right_end.png"],
        "duration": 300,
        "mode": "once"
      },
      "left": { "mirror": "right" },
      "up": { "mirror": "right" },
      "down": { "mirror": "right" }
    }
  }
}
```

#### Sprite map structure

| Level | Key | Value |
|-------|-----|-------|
| State | `"idle"`, `"moving"`, `"pushing"`, or custom | Direction map |
| Direction | `"up"`, `"down"`, `"left"`, `"right"` | Static sprite, animation, or mirror |

#### Direction values

Each direction entry is one of:

| Form | Description |
|------|-------------|
| `"path.png"` | Static sprite (string). |
| `{ "frames": [...], "duration": N, "mode": "..." }` | Animated sprite (same schema as entity animations). |
| `{ "mirror": "direction" }` | Reuse another direction's sprite/animation, horizontally flipped. Avoids duplicate assets. |

#### Resolution order

When the engine needs a sprite for state S and direction D:

1. Look up `sprites[S][D]`
2. If missing, fall back to `sprites["idle"][D]`
3. If missing, fall back to `sprite` (top-level fallback)
4. If missing, use engine default

Games without directional movement (e.g., `slide_merge`-only games) can use simple mode — no sprite map needed.

---

## Complete Example

```json
{
  "controls": {
    "gestureMap": [
      { "gesture": "swipe_cardinal", "action": "move", "paramMapping": { "direction": "swipe_direction" } }
    ]
  },
  "coverImage": "assets/cover.png",
  "primaryColor": "#4CAF50",
  "backgroundColor": "#1A1A2E",
  "boardStyle": {
    "cellSize": 64,
    "cellSpacing": 2,
    "showGridLines": true
  },
  "textStyle": {
    "fontFamily": "default",
    "titleColor": "#FFFFFF"
  },
  "avatar": {
    "visible": true,
    "sprites": {
      "idle": {
        "right": "assets/sprites/avatar/rabbit_looking_right.png",
        "left": "assets/sprites/avatar/rabbit_looking_slightly_left.png",
        "up": "assets/sprites/avatar/rabbit_idle_away_from_player.png",
        "down": "assets/sprites/avatar/rabbit_idle_facing_player.png"
      },
      "moving": {
        "right": {
          "frames": ["assets/sprites/avatar/rabbit_walking_right_1.png", "assets/sprites/avatar/rabbit_walking_right_2.png"],
          "duration": 400,
          "mode": "loop"
        },
        "left": { "mirror": "right" },
        "up": {
          "frames": ["assets/sprites/avatar/rabbit_walking_up_1.png", "assets/sprites/avatar/rabbit_walking_up_2.png"],
          "duration": 400,
          "mode": "loop"
        },
        "down": {
          "frames": ["assets/sprites/avatar/rabbit_walking_down_1.png", "assets/sprites/avatar/rabbit_walking_down_2.png"],
          "duration": 400,
          "mode": "loop"
        }
      },
      "pushing": {
        "right": {
          "frames": ["assets/sprites/avatar/rabbit_push_start.png", "assets/sprites/avatar/rabbit_push_right_middle.png", "assets/sprites/avatar/rabbit_push_right_end.png"],
          "duration": 300,
          "mode": "once"
        },
        "left": { "mirror": "right" }
      }
    }
  }
}
```
