---
name: revise-level
description: >
  Analyse, redesign, or complete a GridPonder level. Reads the level JSON,
  simulates the mechanics mentally, evaluates design quality (especially the
  "aha moment"), then proposes and writes a revised or completed version.
  Use when a level is incomplete, too easy, too hard, lacks an aha moment,
  or has mechanical errors. Arguments: <level-id> [notes]
  e.g. "nc_003" or "nc_003 should introduce chain merges".
argument-hint: <level-id> [notes]
allowed-tools: Read, Edit, Write, Bash, Glob, Grep
---

You are redesigning a GridPonder level. Follow these steps carefully.

Before starting, read `${CLAUDE_SKILL_DIR}/level-design-principles.md` and
`${CLAUDE_SKILL_DIR}/../test-level/game-rules.md` for mechanics reference.

## 1. Parse arguments

`$ARGUMENTS` → level ID (required) + optional free-text design notes.

## 2. Read and understand the level

Identify the universe JSON file from the level ID prefix:
- `nc_`, `ds_` → `flutter/assets/levels/number.json`
- `fw_`, `pw_`, `sw_` → `flutter/assets/levels/flag.json`
- `rf_`, `fl_` → `flutter/assets/levels/transformation.json`
- `mw_` → `flutter/assets/levels/meta.json`

Also read the two levels **immediately before** this one in the same world
for progression context.

## 3. Analyse the current level

Do this analysis internally (do not write it out). Check:
- Are all required fields present and correct?
- Is there an aha moment? Is it discoverable?
- Is the difficulty appropriate relative to prior levels?
- Does the goldPath actually reach the goal? (simulate mentally)
- Are there cheap alternative solutions that bypass the intended approach?

## 3b. Run the solver (if available for this game)

For **number_cells** levels, the solver at `tools/solver/solve.py` can enumerate
all solutions and verify gold-path uniqueness. Run it before redesigning:

```bash
# From the repo root — finds shortest solutions (fast, BFS)
python3 tools/solver/solve.py packs/number_cells/levels/<level-id>.json

# Finds all solutions up to depth N (complete, DFS — use for final verification)
python3 tools/solver/solve.py packs/number_cells/levels/<level-id>.json \
    --max-depth <gold_path_length + 2> --all-solutions
```

Interpret the output:
- **⚠ WARNING shorter solution exists** → gold path is not the shortest; redesign
  the board to block the shorter route or accept a new gold path.
- **✗ NOT UNIQUE** → multiple solutions of equal length; add obstacles or numbers
  to funnel play toward a single path.
- **✓ UNIQUE** → design goal met; proceed to editing the level.

After editing the level JSON, re-run the solver on the revised version to
confirm the constraints are satisfied before moving on to step 7 (integration
test).

## 4. Simulate the gold path

Simulate the gold path mentally. Do **not** write out ASCII grid tables —
keep this internal reasoning. Just confirm in one sentence whether the path
is valid or state what goes wrong.

Merging rules (number universe):
- All tiles slide as far as possible in the swipe direction.
- Two tiles merge on collision: value = sum. Each tile merges at most once
  per swipe. Process rightmost-first for right swipes, etc.
- Rocks/voids block movement.

## 5. Design the revision

Think through the revised design internally. Do **not** write out step-by-step
grid traces or full solution narratives — keep that reasoning private.

State only:
- **What changes** (1–2 sentences)
- **The aha moment** (one sentence)
- **Why cheap shortcuts are blocked**

Keep the level simple enough to be solved in ≤ 8 moves for world level 3,
≤ 12 for later levels.

## 6. Write the revised level to the JSON

Edit the level entry in the JSON file. Ensure all of these fields are present
and correct:

```json
{
  "id": "...",
  "name": "...",
  "worldId": "...",
  "universeId": "...",
  "startGrid": { ... },
  "startAvatar": { "x": 0, "y": 0, "state": "idle", "facing": "right" },
  "availableActions": ["move"],
  "goldPath": [ ... ],
  "rules": { "merge": "numbers sum up", ... },
  "numberGoalSequence": [...],   ← or goalGrid / goal, per design
  "hintSteps": [...],
  "description": "...",
  "name": "..."
}
```

Use the Edit tool to replace the entire level entry.

## 7. Run the integration test to confirm

Update and run the test:

```bash
cd flutter && flutter test integration_test/app_test.dart -d macos 2>&1
```

Update `kLevelId` and `kMoves` in `integration_test/app_test.dart` before
running. Copy screenshots to `flutter/test/screenshots/` and analyse the
final state visually.

## 8. Report

Give a brief summary (3–5 bullet points max):
- What changed and why
- The aha moment in plain language
- Any open questions for the user

Keep the report concise — no grid traces, no step-by-step replays.
