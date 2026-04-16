# Colour Scrambler

## Game Description

Colour Scrambler is a tile rearrangement puzzle. A grid of coloured tiles sits in a fixed arrangement; a target pattern is shown alongside it. The player's job is to rearrange the live grid until it matches the target exactly. No tile is added or removed — only shuffled.

The shuffling mechanism is a **2×2 floating cursor**. Pip moves around the board and the cursor moves with her, always anchored to her position. Once positioned, Pip can apply two operations to the four tiles under the cursor: **rotate** spins them clockwise 90°, and **flip** mirrors them horizontally. Both operations move four tiles at once; there is no way to affect a single tile in isolation.

Void cells are both impassable terrain and operational blockers. Pip cannot walk onto a void cell, and any rotate or flip operation whose 2×2 region includes a void cell is rejected entirely. Void cells therefore shrink not just the walkable area but the set of positions where useful operations can be performed.

## DSL Elements

**Layers**
- `ground` — exactly one tile per cell: `empty` (walkable, default), `void` (impassable; cursor operations are rejected if any cell in the 2×2 region is void)
- `objects` — zero or one entity per cell: colour tiles — `cell_red`, `cell_blue`, `cell_green`, `cell_yellow`, `cell_purple`, `cell_lime`

**Entity kinds**
- Colour tiles (`cell_red`, `cell_blue`, `cell_green`, `cell_yellow`, `cell_purple`, `cell_lime`) — purely positional objects with no behaviour of their own; the objects layer is the only mutable state

**Actions**
- `move` with `direction` ∈ {up, down, left, right} — moves Pip (and the cursor) one cell in the chosen direction; void cells and board edges block movement
- `rotate` — rotates the four tiles in the 2×2 cursor region clockwise 90°
- `flip` — flips the four tiles in the 2×2 cursor region horizontally (left↔right)

**Systems**
- `avatar_navigation` (`solidHandling: block`) — moves Pip; void cells and board edges are solid
- `overlay_cursor` — a 2×2 cursor fixed relative to Pip's position; defines the region affected by `rotate` and `flip`
- `region_transform` — applies the chosen operation (`rotate` or `flip`) to the objects layer within the cursor region; rejects the operation if any cell in the region is void

**Win condition**
- `board_match` with `matchMode: exact_non_null` — the level is won when every non-null position in the target layout matches the tile currently on the live board at that position

## What Makes This Game Interesting? (Aha moments)

**1. Operations move four tiles, not one.**
Rotate and flip affect the entire 2×2 region under the cursor. Fixing one tile's position almost always displaces three others. Players who try to solve the board tile-by-tile discover quickly that each fix creates a new problem nearby; the right approach treats the cursor position and operation as a combined move affecting a neighbourhood.

**2. Getting the cursor to the right position is its own puzzle.**
The operation applied matters less than where the cursor is when it is applied. A sequence of moves to reposition Pip — without touching any colour tiles — is often the most important part of a solution. Players must plan not just which operations to apply but which positions to visit in what order.

**3. Void cells block operations, not just movement.**
A void cell in the top-right corner of the board doesn't just prevent Pip from standing there — it prevents any cursor position whose 2×2 region would include that cell from performing any operation. This can eliminate a large fraction of the board's useful cursor positions. The first time a player tries to operate and the game rejects it because of a void cell they hadn't noticed, the void cell becomes a first-class design element rather than just an obstacle.

**4. Every operation is reversible — individually.**
Four rotates returns to the starting arrangement; a flip undoes itself. But the correct intermediate states may require passing through arrangements that look worse than the start. Players who undo an operation the moment it doesn't immediately improve the board will never find solutions that require a detour through a "wrong-looking" intermediate.

## Level Design

### Progression arc

1. **Minimal board, one operation** — a 3×3 board with two or three colour tiles and a target reachable in a single rotate or flip. The player learns that the cursor exists, that it moves with Pip, and that rotate and flip are the two operation types.
2. **Two-operation solution** — a slightly larger arrangement where the correct target requires two operations, possibly at different cursor positions. Players learn that repositioning Pip between operations is necessary.
3. **Cursor path matters** — a level where the correct cursor positions are non-adjacent; Pip must navigate to the first position, operate, navigate to the second, and operate again. The operations cannot be applied at the same location.
4. **More tiles, more colour kinds** — a 4×4 board with four or more colour kinds. Players must manage multiple concurrent displacement effects.
5. **Void introduction** — one or two void cells positioned to block the "obvious" cursor positions. The intended solution requires a less intuitive approach path. Keep the board otherwise simple so the void mechanic is the point of challenge.
6. **Void as constraint engine** — larger board where void cells carve the board into a specific set of valid cursor positions, making the solution path feel maze-like in its cursor-positioning requirements.

### Design tips

- **Solutions feel satisfying when the cursor path is non-obvious.** If the player can find the correct sequence by placing the cursor on every valid position and trying both operations in turn, the level is too shallow. Harder levels should require the player to commit to a cursor path before it becomes clear whether it leads anywhere useful.
- **Avoid layouts where random operation-trying converges.** On a small board with a loose target, a player who tries every operation at every cursor position will solve it by accident. Use tighter targets, more colour kinds, or constrained cursor positions (via void cells) to ensure that only planned sequences succeed.
- **Void cells earn their place by blocking the intuitive position.** A void cell in a corner is decoration; a void cell that removes the position the player would naturally choose as the first operating spot forces a genuine rethink of the approach.
- **Consider reversibility when placing hint stops.** Because every operation can be undone, there are no irreversible moments in the traditional sense. Hint stops are most useful at the point where the correct cursor path diverges from the wrong-but-plausible path — typically before the first operation at a non-obvious cursor position.

## Solver Heuristics

BFS over `(avatar_position, frozenset of (cell, colour) pairs)` is appropriate. The state space is bounded by the number of distinct tile arrangements times the number of Pip positions; for boards at current sizes this is tractable without heuristic guidance.

A reasonable heuristic for ordered search: `h(s) = number of non-null target cells where the current tile does not match the target tile`. This is admissible because each mismatched cell requires at least one operation to fix, and each operation costs at least one action. It guides A* efficiently if BFS proves too slow on larger boards.

No complex precomputation is needed. The state hash is the full (position, tile layout) pair; no inventory or dynamic ground state is involved, keeping the state small.
