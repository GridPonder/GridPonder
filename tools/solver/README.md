# GridPonder Puzzle Solver

BFS/DFS solver for GridPonder levels that enumerates all solutions up to a
given depth and reports uniqueness of the intended gold path.

## Usage

```bash
# Quickest: find the shortest solution(s) via BFS
python3 tools/solver/solve.py packs/number_cells/levels/nc_005.json

# Complete enumeration: find all solutions up to depth N (uses DFS)
python3 tools/solver/solve.py packs/number_cells/levels/nc_005.json \
    --max-depth 8 --all-solutions
```

## Currently supported games

| Pack folder    | Game           | Mechanics simulated                          |
|----------------|----------------|----------------------------------------------|
| `number_cells` | Number Crunch  | `slide_merge` + `queued_emitters` + `sequence_match` (on_merge) |

## Architecture

```
tools/solver/
├── solve.py          # CLI entry point + BFS/DFS engine
└── games/
    └── number_crunch.py   # NC state, simulator, pruning hints
```

The engine is generic: `solve.py` only knows about abstract `State` objects.
Each game module in `games/` implements:

- `load(level_json)` → `(initial_state, LevelInfo)`
- `apply(state, direction, info)` → `(new_state, won)`
- `can_prune(state, info, depth, max_depth)` → `bool`

Adding support for a new game means adding a new `games/<game>.py`.

## Search modes

| Mode | Algorithm | Deduplication | Use case |
|------|-----------|---------------|----------|
| default | BFS | yes (per state) | find the shortest solution quickly |
| `--all-solutions` | DFS | path-local only | enumerate every solution ≤ max-depth |

BFS deduplication is correct for finding shortest paths but silently drops
longer paths that pass through already-visited states. DFS with only
path-local cycle prevention finds all paths, at the cost of more nodes
expanded.

## Design decision: Python simulator vs. Dart engine

The simulator in `games/number_crunch.py` is a faithful Python translation
of the Dart engine's `SlideMergeSystem`, `QueuedEmittersSystem`, and
`GoalEvaluator` (sequence_match / on_merge). It intentionally duplicates
that logic rather than calling the Dart engine directly.

**Why not reuse the engine?**

The Dart engine has a well-designed `GridPonderAgent` interface
(`engine/lib/src/agent/`) with full JSON serialisation of game state, and a
`TurnEngine` that wraps the complete turn loop. A Dart-native solver
implementing `GridPonderAgent` would eliminate all duplication
(Option B). That is a viable long-term path.

We consciously chose **Option A (Python simulator)** because:

1. **Dev-loop speed**: zero startup overhead, no Dart toolchain required,
   runs inside a Claude Code agent invocation without any shell setup.
2. **Fast iteration**: level-design search scripts (e.g. brute-forcing
   two-tile placements) call the simulator thousands of times in a
   tight Python loop. Subprocess IPC per state transition would make
   this prohibitively slow.
3. **Low sync risk**: the mechanics being simulated (`slide_merge`,
   `queued_emitters`, `sequence_match`) are stable DSL primitives.
   Breaking changes to these would also require updating all existing
   level JSON files, making divergence obvious.

The simulator has been validated against all five Number Crunch gold paths.
If the Dart engine mechanics ever change significantly, update
`games/number_crunch.py` alongside `engine/lib/src/systems/` and re-run the
solver against all levels to confirm.
