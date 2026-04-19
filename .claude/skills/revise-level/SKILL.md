---
name: revise-level
description: >
  Analyse, redesign, or complete a GridPonder level. Reads the level JSON,
  evaluates design quality (aha moment, difficulty, gold path validity, cheap
  alternatives), then proposes and writes a revised version. Use when a level
  is incomplete, too easy, too hard, lacks an aha moment, or has mechanical
  errors. Arguments: <level-id> [notes]
argument-hint: <level-id> [notes]
allowed-tools: Read, Edit, Write, Bash, Glob, Grep
---

Read `{base_dir}/level-design-principles.md` and the relevant
`docs/games/<pack-name>.md` before starting. For the correct level JSON format
and solver/difficulty guidance, refer to the create-level skill
(`{base_dir}/../create-level/SKILL.md`).

## 1. Parse arguments

`$ARGUMENTS` → level ID (required) + optional free-text notes on what to fix.

## 2. Read the level and its context

Locate `packs/<pack_id>/levels/<level_id>.json` using the prefix:

| Prefix | Pack |
|--------|------|
| fw\_, pw\_, sw\_ | carrot_quest |
| nc\_ | number_cells |
| ds\_ | diagonal_swipes |
| rf\_ | rotate_flip |
| fl\_ | flood_colors |
| bb\_ | box_builder |

Also read the pack's `game.json` and the **two levels immediately before** this
one in `levelSequence` for progression context.

## 3. Analyse the current level

Check internally (no need to write this out):
- Are all required fields present and valid?
- Is there a clear aha moment? Is it discoverable without guessing?
- Is the difficulty appropriate relative to the preceding levels?
- Does the goldPath actually reach the goal? (simulate mentally)
- Are there cheap alternative routes that bypass the intended approach?
- Does the level require subgoal reasoning, or can it be cracked by trying
  all move sequences up to a small depth?

If a solver exists in `tools/solver/games/` for this pack, run it to check
whether a shorter solution exists and whether the gold path is reasonably
constrained. Use this to identify design weaknesses, not to enforce strict
uniqueness (a few equivalent move orderings are fine).

## 4. Design the revision

State only (keep internal reasoning private):
- **What changes** — 1–2 sentences
- **The aha moment** — one sentence
- **Why cheap shortcuts are blocked**

## 5. Edit the level JSON

Edit `packs/<pack_id>/levels/<level_id>.json` in place. The format is the
same as described in the create-level skill. Ensure `solution.goldPath` and
`solution.hintStops` are updated to match the revised design.

## 6. Verify

Run the integration test using the test-level skill:
```
/test-level <level_id>
```

## 7. Report

3–5 bullets: what changed and why, the aha moment, any open questions.
