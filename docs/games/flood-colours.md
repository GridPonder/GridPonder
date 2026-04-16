# Flood Colours

## Game Description

Flood Colours is a classic flood-fill puzzle. The board is a rectangular grid of coloured tiles; one region — the top-left corner by default — begins as the "flooded" area. On each turn the player picks a colour. Every tile of that colour adjacent to the current flooded region immediately joins it, turning flooded themselves. Their newly flooded neighbours are now part of the boundary, so a single well-chosen colour can absorb a large connected swathe of the board at once.

The goal is to flood the entire board — no coloured tile left un-flooded — within a fixed move limit. The board can always eventually be flooded given enough moves; the challenge is the limit. Playing under it requires planning the expansion sequence rather than choosing colours by feel.

There is no avatar. The player acts only through colour selection, and every selection reshapes the flooded region's boundary in ways that cascade forward through the rest of the game.

## DSL Elements

**Layers**
- `ground` — always `empty`; the playing field is entirely in the objects layer
- `objects` — zero or one entity per cell: colour tiles — `cell_red`, `cell_blue`, `cell_yellow`, `cell_orange`, `cell_purple`, `cell_teal`; plus `cell_flooded` (the expanding owned region)

**Entity kinds**
- Colour tiles (`cell_red`, `cell_blue`, `cell_yellow`, `cell_orange`, `cell_purple`, `cell_teal`) — passive tiles; they become `cell_flooded` when the matching flood action is chosen and they are adjacent to the current flooded region
- `cell_flooded` — the player's owned region; grows with each action; the level is won when every non-flooded cell has been absorbed

**Actions**
- `flood_red`, `flood_blue`, `flood_yellow`, `flood_orange`, `flood_purple`, `flood_teal` — one action per colour; no direction, no avatar movement; selects the colour to flood next

**Systems**
- One `flood_fill` system per colour — when the matching action is taken, converts all tiles of that colour that are orthogonally adjacent (directly or transitively through same-colour chains) to the current flooded region into `cell_flooded`; the flooded region then includes those new cells and their boundaries become the new frontier

**Move limit**
Each level specifies a move limit. Actions beyond the limit are vetoed by the engine. A level is lost if the board is not fully flooded before the limit is exhausted.

**Win condition**
- `all_cleared` for every non-flooded colour kind — the level is won when no tile of any colour kind remains on the board (all cells are `cell_flooded`)

## What Makes This Game Interesting? (Aha moments)

**1. One good move can absorb a huge section of the board.**
Picking a colour that is connected in a large region adjacent to the flooded boundary absorbs every tile in that region simultaneously, not just the immediate neighbours. Recognising which colour choice will trigger the largest chain absorption — rather than picking the colour that is simply most common on the board — is the central skill.

**2. The boundary is what matters, not the total distribution.**
A player who counts colour tiles across the whole board and picks the most frequent colour will make mediocre choices. What matters is which colours are represented along the current flooded boundary. Two tiles of a colour adjacent to the frontier are worth more than twenty tiles of the same colour in an isolated cluster.

**3. Wasted moves are invisible.**
Choosing a colour that has no tiles adjacent to the flooded region does nothing to the board — the move is consumed and nothing changes. The engine does not warn the player. Early levels can be used to make this consequence obvious; later levels rely on the player having internalised it.

**4. Grabbing a small patch early can unlock a large cluster behind it.**
The optimal sequence is often counterintuitive because the correct first move may only absorb one or two tiles — but those tiles are the only ones adjacent to a large same-colour mass that becomes the next available expansion. Players who always pick the biggest immediate gain miss the strategic setup.

## Level Design

### Progression arc

1. **Small board, few colours, generous limit** — a 5×5 grid with three colours and a move limit several steps above the optimal solution length. Players discover the mechanic and learn that colour selection controls expansion. The generous limit means they do not need to plan carefully.
2. **Tighter limit** — same board size, same colour count, but the limit is closer to optimal. Players begin to learn that not every colour choice is equal.
3. **Larger board** — a 8×8 or larger grid with four colours. The frontier becomes complex enough that the boundary-first mental model starts to matter.
4. **More colours** — five or six colours on a medium board. More colour options make each decision less obvious; the player cannot rely on a single dominant colour and must sequence more carefully.
5. **Near-optimal required** — the move limit matches or is one above the optimal solution. Only well-planned sequences succeed. Players who play by feel will reliably run out of moves.

### Design tips

- **The tightness of the limit is the single most important difficulty lever.** A limit equal to the optimal solution length makes every move load-bearing. A limit two above optimal allows one mistake. Choose the gap deliberately.
- **Place colour clusters so the boundary-first strategy is non-obvious.** If the largest adjacent region is always the correct next move, the game plays itself. The most interesting levels require choosing a colour that absorbs a small boundary patch in order to unlock a large cluster that is not yet adjacent.
- **Avoid isolated single-tile patches of rare colours.** A tile of a colour that appears nowhere else on the board is just a tax the player must pay at some point. It adds moves to the optimal solution without adding strategic interest. Use rare colours in clusters that create meaningful boundary decisions.
- **Use colour distribution to control where the frontier grows.** Long chains of a single colour that wrap around the board make certain flood actions dramatically more powerful than they appear. Designing these into the board gives the solver (and observant players) opportunities to find non-obvious optimal sequences.

## Solver Heuristics

BFS over `(frozenset of (cell, colour) pairs representing non-flooded tiles, moves_remaining)` terminates quickly at current board sizes (≤ 15×15, ≤ 6 colours). The branching factor is at most 6 (one action per colour); shallow solution depths keep the tree manageable.

A useful ordering heuristic for BFS: prefer states where the number of distinct colour-connected components adjacent to the current flooded region is smaller — fewer distinct neighbours means the frontier is more consolidated and closer to completion. This is not admissible in the A* sense but serves well as a BFS priority.

If larger boards require more guidance, a weak admissible heuristic is the number of distinct colour-connected components currently adjacent to the flooded region — each must be absorbed by at least one dedicated action. This underestimates because a single action can only absorb one colour, but it guides ordering without over-pruning. Plain BFS remains preferred for current level sizes.
