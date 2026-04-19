---
name: Twinseed level design — no seed-on-plot at start
description: Design rule: never place a seed basket on a garden plot at level start
type: feedback
---

Never place a seed basket on a garden plot at the start of a Twinseed level.

**Why:** Mechanically a basket sitting on a plot at game start would not trigger the `seeds_planted` rule (that fires on `object_placed`, not on load), but it is conceptually confusing — the player sees a seed already where it needs to go, which makes no narrative sense and undermines the push-to-plant mechanic.

**How to apply:** When reviewing mutate_and_test candidates or writing level JSON, reject any layout where a `seed_basket` object entry shares the same position as a `garden_plot` ground entry.
