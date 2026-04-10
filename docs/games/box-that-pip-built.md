# The Box That Pip Built

## Game Description

Pip the rabbit has stumbled upon a workshop floor scattered with box fragments. Each fragment is a partial crate: a piece of wood carrying one or more sides of a box. Pip must push these fragments together to assemble complete boxes and place each finished crate on a target square.

The twist that sets this apart from ordinary box-pushing games is the **side-based collision model**. A fragment only blocks movement on the sides it actually has. A fragment missing its left wall can be entered from the left; once Pip is inside, moving through an existing side carries the whole fragment along. This inside/outside duality is the game's core surprise: Pip isn't just a pusher — she can become part of the box.

Additional hazards make levels more interesting: rocks that block corridors (clearable with a pickaxe), void cells that shrink the playfield, and portals that can teleport both Pip and pushed fragments, opening up spatial shortcuts that work equally for player and cargo.

## DSL Elements

**Layers**
- `ground` — always exactly one tile per cell: `empty` (walkable), `void` (impassable chasm), `portal`
- `objects` — zero or one entity per cell: `box_fragment`, `rock`, `pickaxe`
- `markers` — zero or one `box_target` per cell (target overlays; persists under placed boxes)

**Entity kinds**
- `box_fragment` — the pushable object; has an integer `sides` param (bitmask: up=1, right=2, down=4, left=8; complete box=15); tagged `sided`
- `box_target` — a goal marker
- `rock` — solid and breakable; blocks Pip and fragments; can be destroyed with a pickaxe (plays `breaking` animation)
- `pickaxe` — pickup item; auto-collected when Pip walks over it; consumed on the first use against a `breakable` entity
- `portal` — teleporter paired by `channel` param; teleports Pip when she walks onto it, and teleports a pushed fragment when Pip pushes it onto the portal cell
- `void` — ground-layer cell that is fully impassable (no entering, no pushing into)

**Actions**
- `move` with `direction` ∈ {up, down, left, right} — the only action

**Systems**
- `sided_box` — handles all movement: pushing from outside (fragment moves if the side facing Pip exists), carrying from inside (Pip + fragment move together if Pip steps through an existing side), fragment merging (OR of `sides` bitmasks when two fragments land on the same cell), and pickaxe/rock interactions
- `portals` — teleports the avatar when it steps onto a portal cell, to the paired cell with matching `channel`

**Rules**
- `pickup_item` — on `avatar_entered`, if an object tagged `pickup` is at the cell, it is moved into Pip's inventory and removed from the board

**Win condition**
- `param_match` goal: every `box_target` in the markers layer must have a `box_fragment` with `sides=15` on the same cell in the objects layer

## What Makes This Game Interesting? (Aha moments)

**1. Fragments only block where they have a side.**
A fragment with `sides=3` (top+right) does not block entry from the left or bottom. Players quickly learn to read the fragment shape before moving — and to exploit gaps to manoeuvre around what looks like an obstacle.

**2. Entering a box changes how you push it.**
Once Pip is standing inside a partial box (having entered through an open side), any move that would take her through an existing side carries the fragment along. Discovering this mechanic — "wait, the box came with me!" — is the central aha moment of the early game.

**3. Merging is irreversible.**
When two fragments land on the same cell they fuse immediately into a single fragment with the bitwise OR of their sides. If you merge the wrong pair, or merge in the wrong order, you may create a shape that can't reach a target or that blocks a path. Levels are designed around this: the correct assembly order is the puzzle.

**4. You can only push a fragment from the direction it has a side.**
To push a fragment, Pip must approach it from a direction where a side exists — that side is what she pushes against. A fragment with only a top side can only be shunted by approaching from above. After a merge, the combined shape may be pushable from more or fewer directions than either piece alone, which can open or close approach angles unexpectedly.

**5. Inside a complete box, Pip is the driver.**
If Pip enters a partial box before the last fragment merges onto it, she may find herself inside a fully enclosed crate (sides=15) with no open exit. Every move then carries the entire box — she has become a driver, not a pusher. This is both a hazard to avoid and a technique to exploit when the target is far away.

**6. Tight geometry forces the order.**
Void cells and narrow corridors mean there is often only one direction from which a fragment can be approached or only one sequence in which two fragments can pass each other. Recognising which direction is the only viable push angle — before committing to earlier moves that would block it — is the core skill of harder levels.

**7. The right pairs aren't always the nearby ones.**
In later levels, fragments that are close together are the *wrong* pair to assemble — they don't complete a box. Pip must first separate them and guide each to its true partner across the board.

**8. Portals move both Pip and fragments.**
A portal teleports whoever or whatever steps onto it: Pip when she walks onto it, or a fragment when she pushes it onto the portal cell. This means a portal can shortcut a long delivery route — but it works in both directions, and the destination may already be occupied, making portal use a commitment that can cut both ways.

**9. Rocks as one-time gates.**
A pickaxe removes exactly one rock. On levels with multiple rocks, Pip must decide which rock is the bottleneck and approach it with the pickaxe in hand at the right moment in the sequence.

## Level Design

### Progression arc

Levels should introduce mechanics one at a time before combining them:

1. **Pure pushing** — a complete box, one target, open space. Establishes the basic interaction.
2. **Fragment assembly** — two, three or four complementary fragments must be pushed together onto a target. Introduces merging.
3. **Inside-carry** — Pip must enter a partial box and carry it to its destination or into another fragment. Keep the board minimal so the aha moment is clean.
4. **Navigation constraint** — the target sits between fragments, or fragments must pass each other. Requires going around rather than pushing straight.
5. **Void geometry** — void cells remove approach angles and funnel movement, forcing a specific push direction without explicit locks.
6. Multiple levels with those mechanics
7. **Pickaxe + rock** — a rock blocks the only viable path; the pickaxe is nearby but requires a detour to fetch first. Place the rock so the player is tempted to try pushing the hard way before realising the pickaxe is needed.
8. Again multiple levels with those mechanics
9. **Portal shortcuts** — a portal offers a shorter route for Pip or a fragment, but the destination may already be occupied, making portal use a commitment.
10. Again multiple levels with those mechanics

### Design tips

- **Medium and hard levels must resist flat search.** If a path to the solution is obvious, a BFS solver finds the solution trivially. We do not want levels that can easily be solved this way as they are (i) solvable for AI players by just coding a simple planning algorithm and (ii) often not interesting for humans. Levels solvable by A* with smart heuristics (but not BFS) or where subgoals need to be identified and solved individually are fine.
- **Use void or non-rectangular grids to constrain approach angles.** Removing cells is the lightest way to make a push direction impossible without adding new entity types. Wide open areas often do not work well for this game as it does not impose interesting constraints.
- **Hint stops should go before the critical merge.** Once a wrong merge is committed the level may be unsolvable; a hint just before the decisive merge is where it helps most.

## Solver Heuristics

**State representation:**
`(avatar_position, {fragment_id → (position, sides)}, inventory)`. The inventory can hold at most one item (or nothing). Fragment identities can be dropped once two fragments have merged (they become fungible after merging).

**Precomputation (once per level):**
- *Target distances* — run reverse-BFS from each target cell to all reachable cells. With ≤ 3 targets on a ≤ 10×10 grid this produces a few hundred entries. Rocks are dynamic (breakable), so precompute one distance table per rock-subset: with ≤ 2 rocks that is at most 4 tables per target. All distance lookups during search are then O(1) — select the table matching the current rock state and read the entry.
- *Level validation* — compute `total_sides = Σ popcount(sides)` across all fragments and `needed_sides = N × 4`. If `total_sides < needed_sides`, the level is malformed. The `total_sides == needed_sides` condition determines whether all fragments must be used, which enables stricter pruning (see below).

**Cached pairing (recompute on merge only):**
Merges are irreversible and infrequent relative to the total move count (a level with 9 fragments and 3 targets needs up to 6 merges across a 30+ move solution). Between merges, the set of valid pairings is stable. Enumerate all valid groups (subsets of fragments whose sides OR to exactly 15 with no overlap) once, and cache the result. Recompute only when a merge event produces a new fragment. This keeps the per-state cost low since most moves just reposition Pip or slide a fragment without triggering a merge.

**State heuristic h(s):**

1. *Dead-end check* — if the cached pairing list is empty (no valid partition of remaining fragments into N groups that each OR to 15), return ∞. This catches wrong merges early: two fragments that accidentally fuse into a shape that cannot be part of any valid group immediately prune the subtree. Additionally, if `total_sides == needed_sides`, check that Pip can reach every fragment and that every fragment has at least one empty adjacent cell; if `total_sides > needed_sides`, verify that at least one valid assignment has all its assigned fragments reachable and mobile.

2. *Assignment cost* — for each valid assignment of cached groups to targets, compute:
   - *Assembly cost* — the cost of bringing the group's fragments together. For a two-fragment group: the distance between them. For three fragments: cheapest merge tree (closest pair first, then the third). For four fragments (all sides scattered): two parallel merges, then merge the halves.
   - *Delivery cost* — distance from the group's centroid (or nearest member) to the assigned target cell. Looked up in O(1) from the precomputed tables.

3. *Return* `min` across all valid assignments of `Σ (assembly + delivery)` per group.

This is admissible — it underestimates because it ignores Pip's travel between groups, repositioning to change push direction, and interference between groups. All omissions produce a lower bound, which is what A* requires.

**Tiebreaking:**
Among states with equal `f = g + h`, prefer the state with the higher completion score (= `Σ popcount(sides)` of the best group assigned to each target). This biases the search toward states that have made irreversible assembly progress, without affecting admissibility.

**Simpler alternative:**
If the full assignment enumeration proves too expensive in practice, a cheaper heuristic is: for each target, find the nearest fragment by precomputed distance, ignoring pairing. This is O(targets × fragments) with O(1) lookups — very fast but weaker, since it doesn't account for pairing conflicts or assembly costs. It may be a reasonable starting point, with the full assignment heuristic as an upgrade if the search space turns out too large.
