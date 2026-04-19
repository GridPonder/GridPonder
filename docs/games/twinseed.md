# Twinseed

## Game Description

Pip the rabbit tends a hidden garden, but the carrot seeds are scattered across treacherous terrain. Each level presents a grid with one or more seed baskets that Pip must push onto marked garden plots — a classic box-pushing challenge with a twist rooted in Pip's own body.

At any moment Pip can perform the **clone** action, leaving a translucent twin of herself on her current cell. The twin is a fixed marker: Pip continues moving freely while the clone sits and waits. Triggering clone again instantly teleports Pip back to the twin's position and the marker disappears. At most one clone exists at a time. This mechanic is the heart of the game: the clone lets Pip "save" a position and return to it cheaply — which is critical for manoeuvring around baskets that she must push from multiple sides, for abandoning a dead-end corridor without backtracking step-by-step, and for reaching cells that become isolated after a push seals off the approach route.

Once a seed basket lands on a garden plot the seeds are planted immediately and the basket disappears, leaving a sprouting garden cell behind. Unlike standard Sokoban, baskets **cannot** be moved off a plot — the action is permanent. This makes basket-placement order the central strategic dimension: pushing the wrong basket onto the wrong plot can strand another basket with nowhere to go. The optional hazards from Carrot Quest — rocks (cleared by pickaxe), wood (cleared by torch), metal crates (form bridges over water), ice (avatar slides; torch melts, pickaxe breaks) — further constrain which cells are reachable and in what sequence.

## DSL Elements

**Layers**
- `ground` — exactly one per cell: `empty` (walkable), `void` (impassable), `garden_plot` (walkable, plot_target), `planted_garden` (walkable, planted), `water` (liquid, walkable), `bridge` (walkable), `ice` (slippery, walkable)
- `objects` — zero or one per cell: `seed_basket` (solid, pushable), `rock` (solid, breakable), `wood` (solid, pushable, burnable), `metal_crate` (solid, pushable), `torch` (pickup), `pickaxe` (pickup)
- `clone` — zero or one `rabbit_clone` marker (the twin position)

**Actions**
- `move` with `direction` ∈ {up, down, left, right}
- `clone` — places twin at current position, or teleports to it if one already exists

**Systems**
- `avatar_navigation` (solidHandling: delegate) — Pip movement
- `push_objects` — basket and crate pushing; torch burns wood; pickaxe breaks rocks
- `anchor_point` (markerKind: rabbit_clone, markerLayer: clone, action: clone) — the twin/clone mechanic
- `ice_slide` — avatar and objects slide on ice until hitting a solid

**Rules**
- `seeds_planted` — on `object_placed` on a `plot_target` cell by a `seed_basket`: transform ground to `planted_garden`, destroy the basket
- `pickup_item` — on `avatar_entered` a cell with a `pickup` object: move item to inventory, remove from board
- `water_clears_items` — on `avatar_entered` a `liquid` cell with inventory: clear inventory
- `torch_melts_ice` — on `avatar_entered` an ice cell while holding torch: transform ice → water
- `pickaxe_breaks_ice` — on `avatar_entered` an ice cell while holding pickaxe: transform ice → empty, consume pickaxe
- `crate_creates_bridge` — on metal_crate `object_placed` on a `liquid` cell: destroy crate, transform ground → bridge

**Win condition**
- `all_cleared` goal: no `garden_plot` entities remain in the ground layer (all have been transformed to `planted_garden`)

## What Makes This Game Interesting? (Aha moments)

1. **The clone lets you push from both sides without walking around.** Pushing a basket east moves it right, but to then push it north you need to be south of it. If the only path south is now blocked by the basket or geometry, the clone saves the spot before the decisive push, then teleports you around.

2. **Planting is irreversible — and order constrains order.** Planting one basket can transform the only plot available to another basket, or cut off the corridor leading to a second plot. The correct planting sequence is always forward-looking; greedy near-to-far planting usually fails.

3. **Clone position is itself a resource.** The clone occupies a cell. A basket cannot be pushed onto the clone cell (the solid check blocks it), and the avatar cannot pass a solid. Placing the clone in the wrong cell can trap you just as surely as a misplaced basket.

4. **Teleporting skips slides.** After teleporting to the clone, the `avatar_entered` event carries no direction, so ice_slide does not fire. A player on ice who teleports to a non-ice cell does not slide — a subtle shortcut that bypasses locks designed around forced sliding.

5. **Clone disappears on use.** After teleporting, the marker is gone. If the destination is needed again the player must walk back and re-clone. Forgetting this and treating clone as "free undo" is the single most common mistake in early levels.

6. **Rocks and wood gate timing.** A pickaxe or torch in the right position enables a shortcut, but consuming it early (to break the nearest obstacle) may leave the player unable to clear a second obstacle that guards a basket's exit route. The tool is a single-use one-time gate.

7. **Ice traps and the clone escape.** A basket pushed onto an ice cell slides until it hits a wall — possibly into a corner from which it cannot be pushed to a plot. Placing the clone before the push, then teleporting to recover position, is the only way to abort and retry without full reset.

8. **Blocked clone cell forces teleport now or never.** If a solid object (rock, basket, wood) moves onto the clone cell, teleporting is permanently blocked — the system skips the teleport if the destination is solid. Sometimes this is a pruned strategy; sometimes it is the level's only trap.

## Level Design

### Progression arc

1. **Pure push** — one basket, one adjacent plot, open grid. Introduce push-to-plant and the permanent lock-in. No clone needed.
2. **Two baskets, correct order** — two baskets, two plots arranged so planting in the wrong order blocks the second. Introduce why planting sequence matters.
3. **Clone for approach angle** — one basket that needs two sequential pushes in perpendicular directions; the corridor closes after the first push. Introduce clone as a position-save tool.
4. **Clone as shortcut** — open area but winding path; the clone cuts an otherwise long return trip. Show clone as travel optimisation.
5. **Three baskets, order + clone** — combine ordering constraint with clone-enabled approach. First level with a genuine two-insight aha moment.
6. **Rock gating** — pickaxe required to open path to one plot; must be collected before committing to the push sequence.
7. **Ice and clone escape** — a basket threatens to slide into a corner; clone must be placed before the push to allow recovery.
8. **Water + crate bridge** — metal crate over water opens the only route to a plot; must be placed in the right order relative to basket pushes.

### Design tips

- **Keep grids non-rectangular or with void cells.** Open, rectangular boards give too many approach angles and make levels trivial. Void cells and narrow corridors force specific push directions and make clone-position meaningful.
- **Hint stops go before the critical push.** The committing action in Twinseed is either planting a basket (irreversible) or making the push that closes off an approach angle. Place hints just before those moments.
- **Test by trying the wrong planting order first.** Build levels where the "obvious" greedy approach (plant the nearest basket first) fails and the correct order requires foresight. Solvers that find the greedy path easily are a signal to tighten the geometry.
- **Limit clone misuse with solid blocking.** If a level's intended solution uses a specific clone position, consider placing a rock or wood at other useful clone positions to prevent cheaper alternatives. Or arrange the board geometry so only the intended clone position is in range.

## Solver Heuristics

**State representation:**
`(avatar_position, frozenset{basket_positions}, inventory_item, clone_position_or_None)`. The garden plots are implicit in the level's ground layer, transformed out of the state as baskets are planted.

**Precomputation (once per level load):**
For each garden plot, run Dijkstra over the state space `(basket_position, last_push_direction_or_None)` to compute the minimum cost to push any basket onto that plot, where cost = `push_count + 2 × direction_changes`. This produces a `push_dist[plot][basket_pos]` table.

*Ice-aware (admissible):* A single push can slide a basket across multiple ice cells. The Dijkstra reverse-trace allows the basket to have originated at any intermediate ice cell (expanded reachability) — a real blocking object could have stopped the slide there. This strictly underestimates the push count when ice is present, preserving admissibility.

*Direction-change repositioning penalty:* After pushing in direction D, repositioning to push in a perpendicular direction D′ requires navigating around the basket — at least 2 extra moves even in open space (the avatar must go around one side). The clone action provides no shortcut: place + recall = 2 actions, the same as walking around. The Dijkstra state tracks `last_push_direction` and adds +2 when direction changes, making this a tight lower bound.

**Admissible heuristic (A\*):**
Use the precomputed table to compute an optimal-assignment lower bound:

- With N remaining baskets and M remaining plots, enumerate all N-permutations of plots and take the minimum total cost — exact optimal bipartite matching in O(N! × N).
- For N > 4, fall back to summing each basket's individual minimum cost across all remaining plots (still admissible, since baskets cannot share a plot in reality).
- Return `float('inf')` if any basket has `push_dist = ∞` to every remaining plot (provably dead state), or if baskets remain but no plots remain.

Admissibility argument: the table underestimates true push cost (ignores avatar position, other baskets, dynamic board state), and the assignment matching never overestimates (each basket must reach a distinct plot; the lower bound uses the cheapest possible assignment).

**Dead-end pruning:**
If any remaining basket has `push_dist = ∞` to every remaining plot in the precomputed table, prune immediately — the level is unsolvable from this state. This subsumes the old corner-check heuristic (a basket in a corner always has `push_dist = ∞` to every non-adjacent plot) and additionally catches ice-specific dead ends where a basket has slid to a position from which it cannot be pushed to any plot regardless of ice.

**Tiebreaking:**
Among states with equal f = g + h, prefer states with fewer remaining baskets (more planted). This biases search toward completing plants early, which reduces branching from basket pushes.
