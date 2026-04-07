# GridPonder Game Rules Reference

Use this file when analysing screenshots to understand expected game state.

## Avatar (Rabbit)

- Starts at `startAvatar` position facing a given direction.
- Moves one cell per swipe in the swiped direction.
- Cannot move into rocks (unless holding a pickaxe).
- Cannot move outside the grid boundary.
- Can hold at most one equipment item at a time.
- Picking up a new equipment item replaces the old one.

## Cell Types

| Type | Sprite | Behaviour |
|------|--------|-----------|
| `empty` | blank | Avatar moves freely |
| `rock` | grey boulder | Blocks movement; destroyed by pickaxe (one use) |
| `wood` | brown log | Blocks movement; burned by torch (one use, wood disappears) |
| `flag` | orange carrot | Goal cell — avatar stepping on it wins the level |
| `water` | water | Avatar can enter but loses all equipment on exit |
| `torch` | torch | Picked up as equipment; burns adjacent wood on move into it |
| `pickaxe` | crossed tools | Picked up as equipment; destroys one rock on move into it |
| `metal_crate` | crate | Can be pushed by avatar; not flammable; sinks in water to form a bridge |
| `portal` (color) | glowing circle | Avatar entering a portal exits from the matching-color portal |
| `spirit` (color) | ghost | NPC; follows colour-coded behaviour rules each turn |
| `colored` (color) | coloured tile | Used as NPC target tiles |

## Equipment Mechanics

- **Torch**: Picked up by walking onto it. On the next move into a `wood` cell,
  the wood is burned (removed) and the torch is consumed. The avatar then
  occupies the cleared cell.
- **Pickaxe**: Picked up by walking onto it. On the next move into a `rock`
  cell, the rock is destroyed and the pickaxe is consumed. The avatar then
  occupies the cleared cell.
- **Metal crate + water**: Pushing a metal crate into water replaces the water
  cell with a "sunken crate" bridge tile. The avatar can walk over it without
  losing equipment.

## Win / Loss

- **Win**: Avatar moves onto the `flag` (carrot) cell → level complete screen.
- **No lose condition** in current levels (no enemies or death tiles).

## Universe-Specific Notes

### Flag Universe (fw_, pw_, sw_)
- Core mechanic: navigate the avatar to the carrot.
- Worlds: Flag World, Portal World, Spirit World.

### Number Universe (nc_, ds_)
- Avatar is outside the grid; swipes slide all numbered tiles on the grid.
- Tiles merge when they collide (like 2048).
- Goal: create/collect specific numbers in sequence.

### Transformation Universe (rf_, fl_)
- `rotate_flip`: Swipes rotate or flip sections of the grid.
- `flood`: Avatar flood-fills connected same-colour regions.

### Meta Universe (mw_)
- Rule tiles on the grid can be tapped/moved to change game mechanics.
- Inspired by "Baba Is You".

## Layout of the Game Screen

```
┌─────────────────────────────────┐
│  Goal panel  │  Rules panel     │  ~25% of screen height
├─────────────────────────────────┤
│                                 │
│         Main grid               │  ~55% — avatar + tiles
│                                 │
├─────────────────────────────────┤
│   Hint   │  Undo  │  Exit       │  ~20% — control panel
└─────────────────────────────────┘
```

- Goal panel: shows the objective text (e.g. "reach the carrot").
- Rules panel: shows level-specific rule cards (equipment descriptions, etc.).
- Hint button highlights blue with dots when hints become available.
