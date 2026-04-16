# Number Crunch

## Game Description

Number Crunch is a 2048-style sliding puzzle stripped down to its strategic core. The board holds numbered tiles; one swipe slides every tile simultaneously in the chosen direction. When two tiles of the same value collide head-on, they merge into their sum and stop. The board then settles in its new configuration, ready for the next move.

What separates Number Crunch from vanilla 2048 is the **goal sequence**: instead of chasing a single high-value tile, each level specifies an ordered list of merge results the player must produce. Completing a level that requires `[4, 8, 16]` means producing a 4-tile first (via a merge), then an 8-tile (via a later merge), then a 16-tile — in exactly that order. Producing the right values out of order does not count; the sequence is a commitment and each step must be earned before the next one matters.

Later levels introduce two environment features. **Pipes** are ground tiles that physically block sliding tiles mid-board AND act as emitters: after each action, a pipe cell injects its next queued tile into the board if the cell above it is unoccupied. This gives the board a live quality — the full tile set is not known at the start. **Portals** teleport a sliding tile to a matched partner cell the instant it would land on the portal cell, redirecting the tile's final resting position to the other side of the board entirely.

## DSL Elements

**Layers**
- `ground` — exactly one tile per cell: `empty` (walkable, default), `void` (impassable; tiles cannot slide through or onto void cells), `pipe` (solid; stops sliding tiles AND participates in the queued_emitters system), `portal` (teleports a tile that would land on this cell to its partner portal cell)
- `objects` — zero or one entity per cell: `number` tiles, each carrying an integer `value` param

**Entity kinds**
- `number` — a slideable tile tagged `mergeable`; carries a `value` param; two `number` tiles with equal `value` that collide during a slide merge into a single tile with `value = a + b`

**Actions**
- `move` with `direction` ∈ {up, down, left, right} — slides ALL `mergeable` tiles on the board simultaneously in the chosen direction

**Systems**
- `slide_merge` — the core sliding engine; moves all `mergeable`-tagged objects in the action direction until each tile hits a board edge, a void cell, a pipe cell, or another tile; when two same-value tiles collide, merges them into a single tile with the summed value; applies at most one merge per tile per action (`mergeLimit: 1`)
- `queued_emitters` — runs after each action; for each pipe cell that has a tile remaining in its emission queue, if the emit target cell (directly above the pipe) is unoccupied, places the next queued tile there
- `tile_teleport` — when a sliding tile's final landing position is a portal cell, immediately relocates it to the partner portal cell

**Win condition**
- `sequence_match` goal — fires `on_merge` after each merge event and records the merged value; the player wins when the recorded sequence of merge results matches the required sequence exactly in order. The goal tracks how far through the sequence the player has progressed, so partial completion is preserved across moves.

## What Makes This Game Interesting? (Aha moments)

**1. Every swipe moves everything.**
There is no targeted movement. One swipe sets every tile in motion simultaneously. An action that positions two tiles for the desired merge will also reposition every other tile on the board, potentially ruining the setup for the merge after that. Planning must account for the full board, not just the two tiles of immediate interest.

**2. The sequence is ordered and unforgiving.**
A player who produces an 8 when the sequence calls for a 4 first has not made partial progress — they have advanced zero steps and the 8 tile now sits on a board that may no longer be able to produce a 4. The sequence forces players to engineer each merge result in turn rather than hunting opportunistically.

**3. Pipes change the board on a schedule the player controls indirectly.**
A pipe emits its next tile after every player action, regardless of what that action was. Choosing which action to take implicitly chooses when the next emission happens and what the board looks like when it arrives. A pipe tile showing up at the wrong moment can break a carefully prepared setup; an emission at the right moment creates a new merge opportunity.

**4. Portals redirect slides across the board.**
A tile approaching a portal does not land where its trajectory suggests — it reappears at the partner portal cell instead. This makes it possible to create collision paths that would be geometrically impossible on a straightforward board, but it also means that a slide intended for one part of the board can have unexpected consequences on the other side.

## Level Design

### Progression arc

1. **Single merge, minimal board** — a 2×2 or 2×3 grid, two tiles of the same value, a one-step required sequence. The player discovers the slide-and-merge mechanic and that the sequence goal tracks merge results.
2. **Two-step sequence** — a slightly larger board where the player must produce two merge results in order. The first merge changes the board layout, which must then support the second merge. Introduce the idea that earlier merges affect later possibilities.
3. **Wider board, multiple tiles** — a 4×4 or larger board with several tiles; the required sequence has two or three elements. Players now face the global-slide problem: fixing one part of the board disturbs another.
4. **Pipe introduction** — add one pipe cell with a short emission queue. The player must account for the injected tile as part of the sequence plan. Keep the emission queue predictable (one or two tiles) so the mechanic is learnable.
5. **Pipe-dependent solution** — a level where the only way to produce a required value is to merge an emitted tile with an existing one. The pipe is load-bearing, not cosmetic.
6. **Portal introduction** — a single portal pair on a board where a collision path that would solve the level only exists through the portal. The level should have a plausible-but-wrong non-portal reading so the player discovers the redirect by exploration.
7. **Combined mechanics** — pipes, portals, and a multi-step sequence on a board large enough that planning the full sequence is genuinely difficult.

### Design tips

- **Avoid sequences that can be produced in multiple orders.** If the player can produce `[4, 8]` or `[8, 4]` with the same moves in different order and both paths are viable, the sequence requirement loses its teeth. Design the board so only one ordering is reachable.
- **Pipes are most interesting when the emitted tile creates a merge the player cannot otherwise reach.** A pipe that injects a tile that is merely in the way is noise. A pipe that injects a tile into a position where it will merge on the next swipe — if the player set up the board correctly first — is a genuine mechanic.
- **Portal timing requires a clear landing zone.** The partner portal cell must be unoccupied when the teleporting tile arrives, or the tile cannot land. Design portal levels so the window of valid timing is non-trivial but achievable: the player must clear the destination before sliding the tile through.
- **The sequence length is the primary difficulty lever.** A four-step sequence on a 4×4 board is harder than a two-step sequence on a 6×6 board, even though the board is smaller. Prefer short sequences on the first few boards after each new mechanic is introduced.

## Solver Heuristics

BFS over `(frozenset of (position, value) pairs, sequence_index, queued_emitter_state)` terminates quickly for boards at current sizes. The state space is bounded by the number of tile arrangements times the sequence progress index.

A lightweight ordering heuristic: prefer states with a higher `sequence_index` (more of the required sequence already produced). This biases BFS toward states that have made committed forward progress without requiring a distance estimate.

No A* is needed for current levels. If boards grow large enough that BFS becomes expensive, the admissible heuristic `remaining_sequence_length` (number of sequence steps not yet produced) gives weak but correct guidance — it underestimates because each remaining step requires at least one action.
