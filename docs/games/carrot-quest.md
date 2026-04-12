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
- **Harder levels should resist flat search.** A level solvable by BFS over raw position-space is too shallow. Build in clear subgoals (collect tool, clear obstacle, create bridge) where the dependency ordering is non-obvious. Levels where A* with a good heuristic terminates quickly but plain BFS would explode are the right difficulty target from level 5 onward.

## Solver Heuristics

**State representation:**
`(avatar_x, avatar_y, frozenset(rock_positions), frozenset(wood_positions), frozenset(crate_positions), frozenset(pickup_positions: torch and pickaxe still on ground), frozenset(bridge_cells), frozenset(ice_cells), inventory)` where inventory ∈ {None, "torch", "pickaxe"}.

Note: ice cells are mutable state because the torch melts ice → water and the pickaxe breaks ice → empty. Initial ice positions are static (part of LevelInfo), but the current ice set must be tracked in the state hash once either tool is in play.

Static per-level data in LevelInfo (not part of the state hash): board dimensions, permanently impassable cells (borders), initial water cells, portal pairs, and flag position.

**Precomputation (once per level):**
- *Walkable-cell BFS from flag* — run reverse BFS from the flag cell treating all rocks, wood, and metal crates as walls, to establish the minimum distance from every free cell to the flag ignoring all tool use. Adds O(board_size) at load time; produces O(1) heuristic lookups for the Manhattan-fallback case.
- *Portal connectivity* — record each portal pair as an undirected teleport edge so BFS can traverse them at unit cost.
- No per-rock-subset tables are needed for current levels (at most two rocks per board); they become worth adding when rock counts reach three or more on large boards.

**Heuristic h(s):**

1. *BFS shortest path on current walkable cells* — run BFS from the avatar's current position to the flag treating all rocks, wood, and metal crates as walls, traversing existing bridge cells and portal edges freely. The result is admissible because any real solution must travel at least this many steps: clearing an obstacle requires additional moves before the open path exists, and the BFS ignores all of that cost. This is the preferred heuristic when per-node BFS is affordable (boards ≤ 10×10, state-space depth ≤ 40).

2. *Fallback: Manhattan distance* — `|avatar_x − flag_x| + |avatar_y − flag_y|`. Always O(1), always admissible. Use this on large boards when the per-node BFS becomes a bottleneck. Weaker guidance but zero overhead.

**Dead-end detection:**
- If the BFS in step 1 returns no path AND inventory is empty AND no pickaxe or torch remains anywhere on the board, return ∞. Flag is permanently unreachable: this is a provable dead end.
- If the BFS returns no path but a tool remains (in inventory or on the board), do NOT prune — a future rock-break or wood-burn may open the path. Use Manhattan distance as h(s) in these intermediate states to preserve admissibility.
- If the only route to a remaining pickup leads through a water cell (which would destroy the held tool needed to clear an obstacle beyond), and no dry route to the pickup exists, return ∞. This check is worth implementing once the solver is in use on levels with both water and multiple pickups.

**Tiebreaking:**
Among states with equal `f = g + h`, prefer states with fewer remaining obstacles (`|rocks| + |wood| + |crates|`). This biases the search toward states that have made irreversible clearing progress without affecting admissibility.

**Practical note on current levels:**
The eight existing levels reach at most 31 moves on an 8×7 board. For these, plain BFS over the full state space terminates in milliseconds, and the heuristic quality has no measurable effect on wall-clock time. The heuristic design above targets future levels in the 30–50 move range on larger boards, where A* with BFS-on-current-board guidance cuts the state space by an order of magnitude compared to uninformed search.
