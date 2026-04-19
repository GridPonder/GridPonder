# Carrot Quest

## Game Description

Pip the rabbit hasn't eaten in three days. Somewhere in each maze a carrot waits — and Pip won't stop until she reaches it. The path is never clear: rocks wall off corridors, wood blocks fill doorways, metal crates sit beside water-filled gaps, and the occasional portal punches a hole in the expected geometry.

The mechanic that makes Carrot Quest more than a navigation puzzle is the **single-slot inventory paired with a destructive environment**. Pip can carry at most one tool: a torch that burns wood without being consumed, or a pickaxe that breaks one rock and then vanishes. Every water cell threatens to erase whatever Pip is carrying. Picking up a second tool silently discards the first. These three constraints — limited carrying, consumable exceptions, and environment-as-threat — mean that route planning and pickup ordering are inseparable from the physical path-finding.

Later levels layer in portals and the metal-crate bridge mechanic: pushing a crate into water permanently converts that cell to solid ground. The crate is gone forever, so the placement choice is irreversible. Combined with the possibility that a portal jump may carry Pip backward in the maze rather than forward, the game builds a rich space of commitment puzzles on top of a deceptively simple movement model.

## DSL Elements

**Layers**
- `ground` — exactly one tile per cell: `empty` (walkable), `water` (liquid, walkable, destroys held item on entry), `bridge` (walkable; created dynamically when a `metal_crate` is pushed onto a water cell), `ice` (slippery, walkable; avatar and pushed objects slide until blocked)
- `objects` — zero or one entity per cell: `rock`, `wood`, `metal_crate`, `torch`, `pickaxe`, `portal`
- `markers` — zero or one `flag` per cell (goal target)

**Entity kinds**
- `rock` — solid, not pushable; tagged `breakable`. Pip cannot move it. Removed by a pickaxe.
- `wood` — solid, pushable (slides to adjacent empty cell), tagged `burnable`. With torch: burned (removed) in place instead of pushed.
- `metal_crate` — solid, pushable; tagged `sinkable`. Pushed onto a water cell → crate removed, water cell transformed to `bridge`.
- `torch` — tagged `pickup`; auto-collected when Pip steps onto it. NOT consumed on use against burnable objects.
- `pickaxe` — tagged `pickup`; auto-collected when Pip steps onto it. Consumed on first use against a breakable entity.
- `portal` — tagged `teleport`; paired by `channel` param. Teleports Pip to the partner portal cell when entered.
- `ice` — ground tile; tagged `slippery` + `walkable`. Does NOT destroy carried items (no `liquid` tag). On entry, Pip (and pushed objects on ice) continue sliding in the direction of travel until hitting a wall, a solid object, or a non-slippery cell. Torch melts ice → water (torch preserved). Pickaxe breaks ice → empty ground (pickaxe consumed).
- `flag` — goal marker in the `markers` layer; tagged `goal_target`.

**Actions**
- `move` with `direction` ∈ {up, down, left, right} — the only action

**Systems**
- `avatar_navigation` (`solidHandling: delegate`) — moves Pip, delegates solid-cell interactions to the push system
- `push_objects` (`pushableTags: [pushable]`; `toolInteractions`: torch→burnable removes object without consuming torch; pickaxe→breakable removes object and consumes pickaxe)
- `portals` (`matchKey: channel`) — teleports Pip to the partner portal when she steps onto either portal in a pair
- `ice_slide` (`slipperyTag: slippery`) — cascade-phase system; on each cascade pass, if Pip (or a pushed object) is on a `slippery` cell and the next cell in the direction of travel is unblocked and walkable, moves them one cell further and re-emits the entry event. Chains until blocked or off ice (up to `maxCascadeDepth` passes).

**Rules**
- `pickup_item` — on `avatar_entered`: if the objects layer at that cell has a `pickup`-tagged entity, move it into inventory and remove it from the board
- `water_clears_items` — on `avatar_entered`: if the ground layer is `liquid` AND Pip holds an item, clear inventory
- `crate_creates_bridge` — on `object_placed`: if the ground at the destination is `liquid` AND the placed object is `metal_crate`, destroy the crate and transform the ground cell to `bridge`
- `torch_melts_ice` (priority 10) — on `avatar_entered`: if the ground is `slippery` AND Pip holds the torch, transform the cell to `water`. Torch is not consumed.
- `pickaxe_breaks_ice` (priority 10) — on `avatar_entered`: if the ground is `slippery` AND Pip holds the pickaxe, transform the cell to `empty` and consume the pickaxe.

**Win condition**
- `reach_target`: Pip stands on a cell that has a `goal_target`-tagged entity in the markers layer

## What Makes This Game Interesting? (Aha moments)

**1. The torch is reusable.**
When Pip picks up the torch, it stays in inventory until water washes it away. A single torch can burn every wood block in the level. Players who expect a one-use item are surprised the first time they burn a second block and the torch is still there — and immediately start re-evaluating the whole level.

**2. Water is a soft timer on tool use.**
Crossing a water cell while holding any tool silently destroys it. Water cells are not impassable; they are a threat. The interesting decision is whether to route around water (longer path, tool preserved) or cross it (shorter path, tool gone). The answer changes depending on whether the tool is still needed for obstacles ahead.

**3. Metal crate creates a permanent bridge.**
Pushing a crate into water removes the crate and replaces the water cell with walkable ground forever. The crossing is free from that point on — but the crate is gone. Recognising that the crate is a bridge in disguise, not just an obstacle to move out of the way, is the aha moment that unlocks water-heavy levels.

**4. Wood can be pushed or burned — the choice is strategic.**
Without a torch, pushing wood repositions it to an adjacent empty cell. With a torch, pushing burns it in place and removes it entirely. These are two different outcomes that cannot be undone. Sometimes clearing a cell completely is necessary; other times relocating the wood block to a new position is the correct move. Burning is irreversible: the choice of which verb to apply matters.

**5. One pickaxe, one rock.**
The pickaxe vanishes on first use. In levels with multiple rocks, exactly one can be removed. The correct choice is the rock whose removal opens the only viable path; the others are irrelevant or traps for players who expend the pickaxe prematurely. Identifying the bottleneck rock before breaking anything is the central challenge.

**6. Inventory is a single silent slot.**
Pip holds at most one tool. Walking over a second pickup replaces the first without any warning. In levels that contain both a torch and a pickaxe, the order of collection is part of the solution. Picking up the wrong one first — or discovering the replacement rule at the cost of the tool Pip was about to need — is one of the most instructive early mistakes.

**7. Portals are bidirectional without preference.**
Either portal in a pair can be entered and it always teleports to the other. There is no "entrance" or "exit." The seemingly clever shortcut that takes Pip to the far side of the level is equally usable in reverse — and using it in reverse might be the only route that works, depending on what is set up around each portal mouth.

**9. Ice doesn't stop you where you want — it stops you where physics does.**
Stepping onto ice commits Pip to sliding until she hits something. She cannot stop mid-ice to pick up a tool, avoid a hazard, or choose a different direction. The aha moment is realising that the only way to land on a specific cell is to engineer a blocker at exactly the right position — a wall, a crate, or the edge of the ice patch itself.

**10. Crates become long-range launchers on ice.**
A crate pushed onto ice slides until it falls into water or hits an obstacle. Pip can sink a crate into a water cell that is too far away for a direct push — the ice turns an adjacent push into a precision long-range action. The aha moment is recognising that the ice strip between Pip and the water is not an obstacle to navigate around; it is the mechanism that makes the bridge possible.

**11. Torch melts ice into a new threat.**
A torch in inventory transforms any ice cell Pip enters into water. The ice is gone — the slide stops — but the cell is now dangerous. Players who expect the torch to make ice safe discover that it makes the cell worse. The correct use is deliberate: melt exactly the ice cell that is acting as an unwanted launch ramp, accepting that the resulting water is now a hazard to route around.

**8. Wood push order determines future reachability.**
When multiple wood blocks are present, burning or moving them in the wrong sequence can close off access to a pickup, block a corridor needed later, or remove a push angle that was the only way to position another piece. The ordering of interactions with wood is often as tightly constrained as the ordering of moves themselves. The correct approach is to read the full board before touching anything.

## Level Design

### Progression arc

Levels should introduce mechanics one at a time before combining them:

1. **Pure navigation and push** — a small open board with one or two wood blocks in the direct path; flag at the far end. No tools. Establishes that wood can be moved and that the goal is to reach the flag.
2. **Multi-push navigation** — rocks and wood form a partial maze; several wood pushes required in a specific order. Players learn that the order of pushes affects available paths.
3. **Torch introduction** — torch placed on the board, wood blocks between torch and flag. Pip must collect the torch and burn her way through. Keep the board narrow so there is no incentive to push instead.
4. **Metal crate and water** — a single water gap with one metal crate nearby. Players discover the bridge transformation. The level should make it obvious that the crate is the only way across; nothing else can cross the water gap.
5. **Dual-tool level** — both torch and pickaxe present. Players encounter the single-slot rule in practice: taking one means the other is unavailable unless they return for it. The board is designed so only one correct pickup sequence works.
6. **Water threatens tool** — water cells interleaved with the path to the flag. Players must route around water to preserve the torch. Routing around water costs extra moves; routing through it destroys the tool. The trade-off should be non-obvious on the first inspection.
7. **Portal introduction** — a simple portal pair with the flag surrounded by rocks and a pickaxe needed to break through. Players discover that the portal teleports Pip to the partner cell. The level should require using the portal as a shortcut rather than the obvious approach.
8. **Ice introduction** — a strip of ice with a crate nearby and water at the far end. Players discover that the crate slides across ice into the water, creating a bridge. A torch is present so players can also discover that entering ice while holding the torch melts it to water. The level should be solvable only via the crate-bridge route; the torch-melt route should open a new hazard rather than a shortcut.
9. **Full mechanic combination** — portals, torch, pickaxe, water, wood, and ice all present. The solution requires using every mechanic correctly and in the right order. Each earlier mechanic should be loadbearing; removing any one of them should make the level unsolvable.

### Design tips

- **Asymmetric tool placement creates commitment.** Put the torch past a water cell and the pickaxe before it, or vice versa. Players must commit to a route before knowing whether they can afford to cross. A single water cell in the right place does more design work than a large water region.
- **Burning the wrong wood block should be silently fatal.** If a player burns a block that was needed to direct a later push or to block a corridor, the level should not offer an obvious recovery. The unsolvability should become apparent on the next few moves, not immediately.
- **Use rocks to shape approach angles, not just block paths.** A rock that closes off the direct route forces a detour that may cross water — safe only with the right tool in hand, only at the right moment in the route.
- **Portal levels should have a plausible but incorrect reading.** The most memorable portal moments are when the player tries the portal as an exit but must use it as an entrance, or when using the portal early bypasses the pickup they still need. Design around both readings.
- **Ice is only interesting when the landing cell matters.** A strip of ice that deposits Pip in a cell she could have walked to anyway is decoration. The design earns ice when exactly one landing position lets Pip proceed — every other blocker arrangement either misses the goal or overshoots into a hazard.
- **Use ice to make crate placement long-range but still precise.** An ice strip between a pushable crate and a water cell forces the player to approach the crate from exactly the right direction. Approaching from the wrong side slides the crate away from the water or into a wall, leaving no bridge.
- **Place hint stops immediately before irreversible actions.** Burning a wood block, expending the pickaxe, and pushing a crate into water are the three irreversible moves in the game. `hintStops` in the gold path should land at the index just before each such commitment, not after.
- **Harder levels should resist flat search.** A level solvable by BFS over raw position-space is too shallow. Build in clear subgoals (collect tool, clear obstacle, create bridge) where the dependency ordering is non-obvious. Use `--mode twophase` in `mutate_and_test.py` to screen candidates cheaply (rules out short paths + confirms solvability), then run A* only on the highest-scoring finalists to prove optimality and extract the gold path.

## Solver

The solver adapter lives in `tools/solver/games/carrot_quest.py`. It is a thin
wrapper around the shared Python engine (`engines/python/`) via
`engine_adapter.py`; all game simulation is handled by the engine, and the
adapter adds only the game-specific precomputed heuristic for A*.

### State representation

The engine's `GameState` is the canonical state. For BFS/A* deduplication its
`to_key()` method produces a hashable tuple covering:
- All board layers (ground, objects, markers), using a sparse index so only
  non-default cells are hashed — O(changed cells), not O(W×H).
- Avatar position, facing, and inventory item.
- Game variables (turn count etc.).

This means ice cells that have been melted or broken, bridges that have been
created, and objects that have been removed are all automatically reflected in
the state key without any manual tracking.

### Admissible heuristic

**What went wrong before:** an earlier heuristic treated every ice cell as
costing one action per cell traversed, ignoring that a single `move` action
slides Pip across an entire ice strip. This overestimated the cost of
ice-heavy paths, making the heuristic inadmissible and causing A* to return
non-optimal solutions.

**Current approach — precomputed backwards BFS on the ice-slide graph:**

At load time, run a reverse BFS from the flag position across the
*obstacle-free* board (no objects, no rocks, no wood — they can only block
paths, never shorten them). Crucially, ice-slide physics are modelled: one
action slides Pip until she hits a wall, a void, or a non-ice cell. Every
intermediate cell along a potential slide is also marked reachable at the same
action cost as the landing cell (because an object that doesn't exist yet could
stop the slide earlier, making the cell reachable in no more steps).

Portals are traversed at unit cost (one action = enter portal, land at partner).

The result is a table `h_table: (x, y) → float` giving the minimum number of
actions to reach the flag from each cell under ideal conditions. Lookup is O(1)
during search.

**Admissibility argument:**

- Objects are ignored → actual path can only be equal or longer. ✓
- Ice is modelled using the *initial* configuration. Ice only disappears during
  play (torch melts → water; pickaxe breaks → empty). Fewer ice cells means
  shorter slides, which means more actions required per unit distance. So the
  precomputed table with maximum ice is always a lower bound on the actual
  cost. ✓
- Intermediate slide cells are costed equal to the landing cell. A real object
  could stop the slide at an intermediate, which costs the same one action, so
  this is still a lower bound. ✓

Cells absent from the h_table are unreachable even in the obstacle-free graph
(walled off by voids or board edges); for these, `heuristic()` returns `inf`,
which prunes provably dead states from the A* open set.

**Practical performance:**

On current levels (≤ 9×9 board, gold paths up to 34 moves) the precomputed
heuristic makes A* viable for moderate-length paths. Very deep levels
(fw_ice_013: 34 moves, ~4.2M states in BFS) are at the edge of tractability
for any Python-based search — BFS is faster per state but explores more states;
A* explores fewer but has higher per-state overhead. For such levels, the
twophase screening strategy (see below) is preferred over proving exact
optimality.

### Level validation strategy

Use these three tools in sequence; do not skip straight to A*:

**Step 1 — Rule out shorter solutions (BFS exhaustion):**
```bash
python3 tools/solver/solve.py packs/carrot_quest/levels/<id>.json \
  --mode bfs --max-depth <gold_len - 1>
```
BFS is *complete* up to `max-depth`: "no solution found" is a hard proof that
no shorter path exists. This is the only tool that can rule out shorter
solutions unconditionally. For gold paths ≤ ~20 moves this runs in seconds to
minutes.

**Step 2 — Confirm solvability for candidate screening (twophase):**

When evaluating many candidates from `mutate_and_test.py`, use `--mode
twophase`:
- Phase 1: BFS exhausts the state space up to `min_length − 1`, proving no
  short solution exists.
- Phase 2: BFS finds *any* win ≥ `min_length` without a depth cap, confirming
  the level is solvable.

No optimality is needed at screening time — that comes later. `twophase` is
significantly cheaper than A* when the goal is filtering a large candidate set:
it stops as soon as one valid long solution is found, and Phase 1 can short-
circuit immediately if the BFS finds no short solution quickly.

```bash
python3 tools/solver/mutate_and_test.py packs/carrot_quest/levels/<seed>.json \
  --mode twophase \
  --criterion solution_length:min=<min>:max=<max> \
  --mc-trials 5000 --criterion mc_difficulty:min=8.0 \
  --candidates 10 --output-dir /tmp/cq_variants/
```

**Step 3 — Prove optimality and find the gold path (A*):**

Only run A* on candidates that passed twophase screening and scored well on
Monte Carlo difficulty:
```bash
python3 tools/solver/solve.py packs/carrot_quest/levels/<id>.json \
  --mode astar --max-depth <gold_len + 8> --timeout 120
```
A* with the admissible heuristic confirms `OPTIMAL` when the gold path is
globally shortest, and produces the gold path itself. If A* times out (very
deep levels), Steps 1 + 2 are sufficient — optimality is a nice-to-have for
deep levels, not a blocker.

### Memory and depth limits

BFS state space grows sharply with board size and gold path depth. Observed
for fw_ice_013 (9×9 board, 34 moves): ~4.2M unique states expanded, ~5.8M in
the visited set, ~6 GB RAM. The visited dict uses key tuples (not full
GameState objects) to avoid catastrophic swap growth. Even so, levels with gold
paths > ~25 moves on 9×9 boards take hours of BFS and are better validated via
twophase + Monte Carlo than via full BFS exhaustion.
