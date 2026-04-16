# Diagonal Swipes

## Game Description

Diagonal Swipes is a tile rearrangement puzzle built around a single, precisely constrained operation. A 2×2 floating cursor moves with Pip across the board. At any cursor position, the player can apply a **diagonal swap**: one action swaps the top-left and bottom-right tiles of the cursor region (`up_left`); the other swaps the top-right and bottom-left tiles (`up_right`). Only two tiles move per action — the other two are untouched.

The tiles being rearranged are numbered (`num_1` through `num_9`). What players are trying to achieve varies by level: some levels ask for a specific tile at a specific position (exact pattern match); others specify that rows or columns must reach a target sum; others require that a count of tiles satisfying some predicate — such as "exactly one tile per row with value ≥ 7" — holds across the whole board. The richer goal types mean that the target arrangement is not always unique, which is itself a source of puzzle depth.

Void cells constrain both movement and cursor operations. The full 2×2 cursor region must fit on non-void cells for an operation to be performed.

## DSL Elements

**Layers**
- `ground` — exactly one tile per cell: `empty` (walkable, default), `void` (impassable; cursor operations are rejected if any cell in the 2×2 region is void)
- `objects` — zero or one entity per cell: number tiles — `num_1` through `num_9`

**Entity kinds**
- Number tiles (`num_1`–`num_9`) — positional objects carrying an integer value; no behaviour of their own; the objects layer is the only mutable state

**Actions**
- `move` with `direction` ∈ {up, down, left, right} — moves Pip (and the cursor) one cell; void cells and board edges block movement
- `diagonal_swap` with `direction` ∈ {up_left, up_right} — swaps the two tiles on the specified diagonal of the current 2×2 cursor region; `up_left` swaps top-left ↔ bottom-right; `up_right` swaps top-right ↔ bottom-left

**Systems**
- `avatar_navigation` (`solidHandling: block`) — moves Pip; void cells and board edges are solid
- `overlay_cursor` — a 2×2 cursor anchored to Pip's position; defines the region affected by swap operations
- `region_transform` — applies the chosen `diagonal_swap` direction to the objects layer within the cursor region; rejects the operation if any cell in the region is void

**Win conditions (vary by level)**
- `board_match` (`exact_non_null`) — specific tiles must be in specific positions; every non-null position in the target layout must match exactly
- `sum_constraint` — one or more rows or columns must satisfy a numeric comparison on their tile sum (e.g. row 0 sum ≤ 5, row 2 sum ≥ 13)
- `count_constraint` — a count of tiles satisfying a predicate must match a required value (e.g. "exactly one tile per row with value ≥ 7")

## What Makes This Game Interesting? (Aha moments)

**1. The same cursor position offers two distinct swaps.**
At any valid cursor location, the player can choose which diagonal to swap. `up_left` and `up_right` each move a different pair of tiles while leaving the other pair in place. These are genuinely different operations with different effects, and choosing between them at a given position is the basic decision unit of the game.

**2. Each swap is its own inverse.**
Applying `up_left` twice returns the four tiles to their original positions. This makes exploration feel safe — nothing is permanently broken. But it also means that finding a solution requires directed planning rather than random reversal; a player who keeps undoing and re-doing the same swap makes no progress.

**3. Sum and count goals don't tell you which tile goes where.**
A `board_match` goal has a unique target: every tile has exactly one correct destination. A `sum_constraint` or `count_constraint` goal does not. Many arrangements may satisfy a sum requirement; the player must figure out which arrangements are reachable from the start state via diagonal swaps, not just which arrangements satisfy the goal. Finding any valid satisfying arrangement is the puzzle rather than recovering a specified one.

**4. Void cells make certain swaps geometrically impossible.**
A void cell removes not just Pip's ability to stand there, but all cursor positions whose 2×2 footprint overlaps it. On a board with well-placed void cells, large sections of the tile arrangement become inaccessible to any single operation — which tiles can be swapped with which other tiles is dictated by the board geometry, not just the player's choice of cursor position.

## Level Design

### Progression arc

1. **Single swap, board_match goal** — a 3×3 board with a target reachable in one diagonal swap. Players discover that `up_left` and `up_right` are distinct operations and that the cursor position determines what is affected.
2. **Two-swap solution** — a level where the correct target requires two swaps at different cursor positions. Players learn that repositioning Pip between operations is part of the solution.
3. **Cyclic dependencies** — a `board_match` level where the naive "fix one tile at a time" approach keeps displacing previously fixed tiles. The correct sequence must fix several tiles simultaneously rather than one at a time.
4. **sum_constraint introduction** — a level where the goal is a row or column sum condition rather than a specific arrangement. Players must infer what arrangement satisfies the goal and then work out how to reach it.
5. **count_constraint introduction** — the most abstract goal type; players must reason about which tiles need to be in which rows without a specific target position for any individual tile.
6. **Void geometry** — void cells introduced to constrain which swaps are geometrically available. The intended solution is the only sequence of swaps that can navigate around the void constraints.
7. **Combined mechanics** — larger board with void cells, a constraint-based goal, and a solution path that requires precise cursor navigation before any swap is productive.

### Design tips

- **For board_match levels, design cyclic dependencies deliberately.** The most satisfying arrangement is one where fixing tile A in place via a swap displaces tile B, which then displaces tile C, and so on — so the player must find the correct entry point in the cycle rather than solving greedily. Boards where any tile can be fixed independently of the others are too easy.
- **For constraint goals, ensure the solution space is small but non-trivial.** A sum constraint with many satisfying arrangements and a large number of swaps that reduce to those arrangements is too loose — the player can succeed by random exploration. A constraint with two or three satisfying arrangements that each require a precise swap sequence is the right difficulty level.
- **Void cells work best when they block the intuitive swap position.** Place void cells to eliminate the cursor position the player would naturally choose first. The forced detour — using a less obvious cursor position — should still lead cleanly to the solution; void cells should redirect, not frustrate.
- **Hint stops work best just before the non-obvious cursor reposition.** Because diagonal swaps are individually reversible, there is no single irreversible commitment moment. The critical juncture is instead the point where the player must navigate Pip to a counter-intuitive cursor position before the correct swap becomes available; a hint stop there gives the most useful guidance.

## Solver Heuristics

BFS over `(avatar_position, frozenset of (cell, tile_kind) pairs)` terminates quickly for current levels. The branching factor is small (4 moves + 2 swaps = 6 actions) and current boards are shallow enough that plain BFS finds solutions without heuristic guidance.

For `board_match` goals, a useful ordering heuristic is `h(s) = number of tiles not in their target position`. This underestimates the remaining work (each swap moves at most two tiles, so mismatched tiles require at least `ceil(mismatches / 2)` swaps), making it admissible for A* if needed.

For `sum_constraint` and `count_constraint` goals, no clean distance estimate exists because the target is a property of the final arrangement rather than a specific configuration. BFS without heuristic guidance is the right approach for these goal types. If a level's solution depth grows large enough to make BFS expensive, the practical approach is to enumerate satisfying target arrangements first (there are typically few) and then run `board_match`-style A* toward each one, taking the shortest result.
