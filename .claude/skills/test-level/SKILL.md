---
name: test-level
description: >
  Run an integration test for a specific GridPonder level. Navigates to the
  level, executes gold-path moves (all or N), takes a screenshot after every
  move, then analyses the sequence. Use when debugging a level's visual
  layout, animations, equipment mechanics, or win conditions.
  Arguments: <level-id> [num-moves]  e.g. "fw_001 3" or "fw_005" (all moves).
argument-hint: <level-id> [num-moves]
allowed-tools: Read, Edit, Write, Bash, Glob, Grep
---

You are running a Flutter integration test against a specific GridPonder level.
The test launches the macOS app, navigates directly to the level, executes
swipe gestures for each gold-path move, and captures a screenshot after every
move. You then read the key screenshots and verify the game state is correct.

Before starting, read `${CLAUDE_SKILL_DIR}/game-rules.md` so you understand
the game mechanics needed to analyse screenshots correctly.

## 1. Parse arguments

`$ARGUMENTS` contains the level ID and optional move count, e.g. `fw_001 3`.
- `level_id` = first token (required)
- `num_moves` = second token (optional; omit to run ALL gold-path moves)

## 2. Look up the gold path

Each level is a standalone JSON file. Map the level ID prefix to its pack:

| Prefix | Pack folder |
|--------|-------------|
| `fw_`, `pw_`, `sw_` | `platform/packs/flag_adventure/levels/` |
| `nc_` | `platform/packs/number_cells/levels/` |
| `ds_` | `platform/packs/diagonal_swipes/levels/` |
| `rf_` | `platform/packs/rotate_flip/levels/` |
| `fl_` | `platform/packs/flood_colors/levels/` |
| `bb_` | `platform/packs/box_builder/levels/` |

Read `platform/packs/<pack>/levels/<level_id>.json`. The fields you need:

- `state.avatar.position` — starting `[x, y]` of the avatar
- `state.avatar.facing` — initial facing direction
- `board.size` — `[cols, rows]` grid dimensions
- `board.layers.objects.entries` — sparse list of `{position, kind}` objects
  (rocks, portals, pickaxe, torch, metal_crate, wood, etc.)
- `board.layers.markers.entries` — sparse list of goal markers (flag/carrot)
- `board.layers.ground.entries` — sparse list of non-empty ground tiles (water)
- `solution.goldPath` — array of `{"action": "move", "direction": "..."}`;
  take the first `num_moves` entries (or all if omitted)

Also note which pack this level belongs to — you'll need `kPackId` below.
Pack folder name = pack ID (e.g. `flag_adventure`, `number_cells`).

Convert each gold-path move to a drag offset for the test:
- `right` → `(100, 0)` · `left` → `(-100, 0)`
- `down`  → `(0, 100)` · `up`   → `(0, -100)`

## 3. Update the test file

Edit `platform/app/integration_test/app_test.dart`.
Replace the two configuration constants in the marked block at the top:

```dart
const String kPackId = '<pack_id>';   // e.g. 'flag_adventure'
const String kLevelId = '<level_id>'; // e.g. 'pw_001'
const List<(double, double)> kMoves = [
  // one entry per move with a direction comment, e.g.:
  (0, 100),    // down
  (100, 0),    // right — picks up pickaxe
  (100, 0),    // right — enters portal
  (-100, 0),   // left — breaks rock
  (-100, 0),   // left — reaches carrot
];
```

## 4. Run the test

```bash
cd platform/app && flutter test integration_test/app_test.dart -d macos 2>&1
```

The test will print one line per screenshot as it runs:
```
Screenshot step 00: /Users/.../Containers/com.gridponder.gridponderApp/Data/test/screenshots/gridponder_new_<pack>_<level>_step00.png
Screenshot step 01: /Users/.../Containers/com.gridponder.gridponderApp/Data/test/screenshots/gridponder_new_<pack>_<level>_step01.png
...
```

Step 00 is the initial state (before any moves). Steps 01–N are after each move.
Screenshots are written to the app's sandbox data directory (no permission prompt needed).
Parse the exact paths from the test output and read them directly from there.

If the test fails, report the error and stop — do not proceed to analysis.

## 6. Analyse the screenshots

**Strategy — be token-efficient. Do not read every screenshot.**

### 6a. Identify interesting steps

Before opening any images, decide which steps are worth examining:
- **Step 00** — always check: confirms the initial board layout is correct
- **Step where avatar picks up equipment** (torch, pickaxe) — verify item
  disappears from board and avatar sprite shows the held item
- **Step where equipment is used** (rock broken, wood burned) — verify the
  tile is removed and the axe/torch is consumed
- **Step after a portal teleport** — verify avatar appears at the exit portal,
  not the entry portal
- **Final step** — always check: confirm win screen ("Level Complete!") and
  avatar position

Skip all other steps — note them as "not analysed — no state change expected".

### 6b. For each interesting screenshot

Use the Read tool to open the image. Verify:
1. **Avatar position** — simulate the path manually from `state.avatar.position`
   and confirm the sprite is in the expected cell
2. **Equipment state** — held item shown on rabbit sprite / tile gone from board
3. **Tile changes** — broken rock removed, burned wood removed, portal still
   present (portals persist after use)
4. **Win condition** — final step should show the "Level Complete!" banner

### 6c. Report

Summarise:
- Which steps were verified and whether they were correct
- Any visual anomaly or unexpected state (wrong position, tile not removed, etc.)
- Whether the final screenshot confirms a legitimate win
- Any open questions for the user
