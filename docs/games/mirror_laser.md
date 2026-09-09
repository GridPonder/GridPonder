# Mirror Laser

## Game Description

A laser source sits fixed on the grid, quietly pointed nowhere. The player's
job is to route its beam to a target cell by placing angled mirrors in its
path. There is no avatar walking the board — the player acts on the grid
itself, tapping a cell to select it, pressing a direction button to fire the
selected source that way, and spending a small, strictly limited stock of two
mirror shapes to bend the beam around whatever stands in the way.

The twist that sets this apart from a simple "shoot in a straight line" toy is
that the beam is a **live simulation of the current board**, not a one-shot
animation. Every mirror placed or removed immediately changes where the beam
ends up, recomputed from scratch each turn. The player isn't aiming once —
they're building a light-path piece by piece and watching it react as they
work, closer to plumbing than archery.

Blockers add the second kind of constraint: cells the beam simply cannot
survive. Where a mirror redirects, a blocker (or the edge of the board)
absorbs the beam outright. Later levels combine tight mirror budgets with
blockers that remove the obvious route, forcing the player to find the one
sequence of bends that reaches the target instead of the many that don't.

## DSL Elements

**Layers**
- `ground` — always exactly one tile per cell: `floor` (walkable, where
  mirrors may be placed), `wall` (blocker), `target` (win cell),
  `mirror_backslash` / `mirror_forward_slash` (player-placed reflectors)
- `objects` — zero or one entity per cell: `laser_source` (has a `facing`
  param: `null` until first fired, then one of `up`/`down`/`left`/`right`)
- `markers` — zero or one entity per cell: `beam_path` (visual-only trace of
  the beam's current route, rewritten every turn)

**Entity kinds**
- `laser_source` — the fixed emitter; tagged `beam_source`; placeholder
  display is a red labelled tile
- `wall` — tagged `solid`; absorbs the beam with no redirect; placeholder grey
  tile
- `target` — tagged `goal_target`; the beam reaching this cell wins the
  level; placeholder green tile
- `mirror_backslash` (`\`) — tagged `reflector`; redirects
  up→left, down→right, left→up, right→down; player-placed, limited stock
- `mirror_forward_slash` (`/`) — tagged `reflector`; redirects
  up→right, down→left, left→down, right→up; player-placed, limited stock
- `beam_path` — non-solid marker entity painted along the traced beam route
  for visual feedback only; no tags, no gameplay effect

**Actions**
- `tap_cell` (position) — select a cell. If it holds a `beam_source`, also
  arms that source for firing.
- `fire_up` / `fire_down` / `fire_left` / `fire_right` (no params) — set the
  currently armed source's `facing` to the matching direction. Four separate
  zero-param actions rather than one `direction`-parameterized action, because
  the reference app's control buttons only render zero-param actions (see the
  `beam` system's `fireActions` config below).
- `place_backslash` (no params) — place a `mirror_backslash` at the last
  selected cell, spending one from its budget.
- `place_forward_slash` (no params) — same, for `mirror_forward_slash`.

**Systems**
- `beam` (**new** — see below) — owns selection, firing, and per-turn beam
  tracing/reflection/win-signalling.
- `terrain_edit` ×2 (existing system, **one small backward-compatible
  addition**: an optional `positionVariable` config so a placement action can
  read its target cell from a runtime variable instead of its own `position`
  param — needed because `place_backslash`/`place_forward_slash` are
  zero-param buttons that act on whatever `tap_cell` last selected, not on a
  position of their own). One instance per mirror kind, each with its own
  `budgetVariable` and a `fromKind: "floor"` guard so a mirror can never
  overwrite a wall, target, or another mirror.

**New system: `beam`**

*Purpose:* Select a source entity by tapping it, aim it with a directional
action, and — every turn, unconditionally, like `sonar` — trace a ray from
each aimed source through the board: continuing straight through empty cells,
turning 90° at a `reflectors`-configured entity kind (via a plain
incoming-direction → outgoing-direction map, so any future reflector shape a
game defines just needs its own map), stopping at a blocking-tagged cell or
the board edge, and stopping (with a win flag) at a target-tagged cell.

*Phase:* `action_resolution` for `selectAction`/`fireAction` (they consume
player input); `npc_resolution` for the trace itself (recomputes every turn
from current board state, independent of which action fired — so placing or
implicitly removing a mirror updates the visible beam immediately).

*Config:* `fireActions` is left at its default (`fire_up`/`fire_down`/
`fire_left`/`fire_right` → the matching direction), so it doesn't need to be
listed explicitly:
```json
{
  "selectAction": "tap_cell",
  "sourceLayer": "objects",
  "sourceTags": ["beam_source"],
  "facingParam": "facing",
  "selectedCellVariable": "selectedCell",
  "selectedSourceVariable": "selectedSource",
  "blockingLayers": ["ground"],
  "blockingTags": ["solid"],
  "targetTags": ["goal_target"],
  "reflectors": {
    "mirror_backslash": {"up": "left", "down": "right", "left": "up", "right": "down"},
    "mirror_forward_slash": {"up": "right", "down": "left", "left": "down", "right": "up"}
  },
  "hitVariable": "beamHitTarget",
  "allReflectorsUsedVariable": "allReflectorsUsed",
  "pathLayer": "markers",
  "pathKind": "beam_path",
  "maxSteps": 200
}
```

*Reuse:* Game-agnostic — any line-based mechanic that bends off configurable
cell kinds: wires, sound/sonar-with-bounce, light puzzles, sightlines that
ricochet.

**Rules:** None needed for the core loop — the win condition reads the
`beam` system's `beamHitTarget`/`allReflectorsUsed` variables and each
`terrain_edit` instance's `budgetVariable` directly.

**Win condition:** four `variable_threshold` goals, all required simultaneously:
- `{"variable": "beamHitTarget", "target": 1, "comparison": "gte"}` — the beam
  reached the target.
- `{"variable": "backslashRemaining", "target": 0, "comparison": "lte"}` and
  `{"variable": "forwardSlashRemaining", "target": 0, "comparison": "lte"}` —
  every reflector the level handed out has actually been placed somewhere.
- `{"variable": "allReflectorsUsed", "target": 1, "comparison": "gte"}` —
  every placed reflector lies on the beam's traced path, i.e. none of them
  were dropped somewhere the beam never reaches.

Budget-exhaustion alone isn't enough: a player could place every reflector
but dump some off to the side of the intended route, satisfying "all placed"
while still winning via a cheaper path. `allReflectorsUsed` closes that by
checking placement against the trace directly, so the win condition really
does mean "reach the target using every reflector you were given, all of
them actually bending the beam" — not just "spend the inventory."

**UI:** `ui.showMoves: false` — the generic action counter includes
selection taps and doesn't read as a meaningful "moves" tally for this game.
`ui.readouts` shows live `\`/`/` stock instead (`backslashRemaining`,
`forwardSlashRemaining`), so the player always sees what they have left to
work with.

## Aha Moments

1. **The beam is live, not a one-shot.** Placing a second mirror after the
   first doesn't require "re-firing" — the whole path recomputes instantly.
   Players who expect to aim-and-forget realize they're sculpting a path in
   real time.
2. **Selection and aiming are separate from placement.** Tapping a cell either
   arms a source (if one sits there) or marks a placement target (if it's
   floor) — the same gesture, two meanings, disambiguated by what's under your
   finger.
3. **A blocker doesn't redirect — it just eats the beam.** Early players may
   expect every obstacle to be a mirror-like deflector; discovering that walls
   simply end the beam is what teaches the two-obstacle-type distinction.
4. **Mirror stock is the real puzzle, not mirror placement.** With enough
   mirrors any bent path is trivial; the design tension comes from having
   exactly enough of each type to reach the target and no slack for a wrong
   guess.
5. **Hitting the target isn't always enough.** The win condition requires
   every given reflector to be placed *and* on the beam's path — a cheaper
   route that reaches the target using fewer mirrors doesn't win, teaching
   the player that the full route matters, not just the destination.
   `ml_003` makes this explicit: a 2-mirror shortcut along the open bottom
   row does hit the target, but leaves 3 reflectors unplaced, so it isn't a
   win.
6. **Order can matter when budgets are asymmetric** — e.g. one `\` and two
   `/` force a specific bend sequence, since placing the `\` in the wrong
   spot uses the only copy you have.

## Level Design

### Progression arc

1. **Two bends** (`ml_001`, "First Light") — target is off-axis from the
   source; one wall closes the single-mirror shortcut, so exactly one `\`
   and one `/` are needed.
2. **Same-column detour** (`ml_002`, "Around the Wall") — source and target
   share a column, which would let a straight shot trivialize the level; a
   wall directly below the source blocks that, and a second wall spanning
   the bottom row blocks the cheaper 2-mirror shortcut, forcing all three
   given reflectors (1 `\` + 2 `/`) into a real detour.
3. **Corner to corner, exhaust the budget** (`ml_003`) — five reflectors,
   a five-bend intended route, and (new) the win condition itself now
   requires every given reflector to be placed *and* on the beam's path —
   so a level no longer needs a bespoke wall for every possible shortcut;
   the win condition rules them out generically. `ml_003` deliberately still
   has an open bottom row and a cheaper 2-mirror route through it, left in
   on purpose to demonstrate that the shortcut hits the target but still
   doesn't win.
4. *(Beyond this pack's current scope)* multiple sources, multiple targets,
   splitting reflectors — noted by the user as future extensions, not
   designed here.

### Design tips

- Keep level 1 at 1–2 placements total; the aha is "the beam updates live,"
  not "the puzzle is hard."
- From level 3 on, make sure the number of *plausible* mirror positions
  exceeds the mirror budget, so brute-force placement doesn't trivially win —
  a board with exactly as many candidate cells as mirrors has no puzzle in it.
- Hint stops belong right after the player fires the beam for the first time
  (seeing *where it currently ends up* is the critical piece of information
  for planning the next mirror) and before a budget-critical placement.

## Solver Heuristics

**State representation:** `(placed_mirrors: {position → kind}, remaining
budget per kind, source facing)`. With 1 source and ≤ 4–5 total mirrors across
both kinds on a small board, this state space is small.

**Precomputation:** none needed at level-1 scale — the trace itself is O(board
perimeter) per evaluation, cheap enough to run per node.

**Search:** plain BFS/DFS over `{tap_cell(pos), place_backslash,
place_forward_slash, fire_up, fire_down, fire_left, fire_right}` is expected
to suffice through the early levels given the tiny branching factor (board
cells for selection, plus 6 fixed actions). No custom solver adapter is
needed at all: since every action's param shape (`position`, no params) is
one the generic solver (`tools/solver/engine_adapter.py`) already builds a
flat action space for, `mirror_laser` levels solve via the plain generic DSL
path (`python solve.py <level>`) — confirmed working on `ml_001` (4-step gold
path found instantly). Once harder levels (asymmetric budgets, multiple
bends) are built and we have real branching-factor numbers, we'll revisit
whether an admissible heuristic (e.g. Manhattan distance from the beam's
current terminal cell to the nearest
unreached target, which never overestimates because a straight run costs
exactly that many beam-cells and any bend can only add distance) is worth
adding for A*.

**Dead-end pruning:** a placement that leaves fewer remaining mirrors of a
kind than the minimum bend count still required to reach any target (computed
by a cheap reachability check ignoring current mirrors) can be pruned early.
