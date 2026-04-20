# Twinseed levels

Verification commands use `tools/solver/solve.py` from the repo root.
For the A* commands you need the Cython extension built first:

```
cd tools/solver/games/twinseed_cython && python setup.py build_ext --inplace
```

---

## tw_001 — First Roots (3 moves)

Mechanic introduction: push one basket onto the single garden plot.

```
python3 tools/solver/solve.py packs/twinseed/levels/tw_001.json
```

BFS confirms unique optimal solution at depth 3. MC difficulty: ~2 bits.

---

## tw_002 — The Alcove (11 moves)

First use of the clone mechanic. The basket is in an alcove that becomes
unreachable after the first push unless the clone is placed first.

```
python3 tools/solver/solve.py packs/twinseed/levels/tw_002.json
```

BFS confirms unique optimal solution at depth 11. MC difficulty: ~10 bits.

---

## tw_003 — Garden Gauntlet (30 moves)

Two baskets. Order and clone placement both matter.

```
python3 tools/solver/solve.py packs/twinseed/levels/tw_003.json --mode astar --max-depth 35 --timeout 60
```

A* confirms optimal at 30 moves. MC difficulty: >12 bits (0 random solves in 5 000 trials).

---

## tw_004 — Three Side-by-Side (56 moves)

Three plots arranged side by side at the bottom; baskets and void cells force
a precise sequence. The clone is used twice: once to reach an otherwise
inaccessible corridor, and once to save moves by teleporting back across the board.

Optimal solution proved by A* with the Cython backend (takes ~60 s):

```
python3 tools/solver/solve.py packs/twinseed/levels/tw_004.json --mode astar --max-depth 60 --timeout 120
```

Without the Cython extension the same search takes ~67 minutes. Without an
admissible heuristic (pure BFS at depth 56) the search is completely
intractable regardless of speed.

---

## tw_005 — The Shortcut (23 moves)

Clone required. Optimal proved by A* (fast solver, ~15 s).

```
python3 tools/solver/solve.py packs/twinseed/levels/tw_005.json --mode astar --max-depth 30 --timeout 60
```

---

## tw_006 — The Return (24 moves)

Clone required. Optimal proved by A* (fast solver, ~37 s).

```
python3 tools/solver/solve.py packs/twinseed/levels/tw_006.json --mode astar --max-depth 30 --timeout 60
```

---

## tw_007 — Four Anchors (36 moves)

Clone required four times. Optimal proved by A* (fast solver, ~16 s).

```
python3 tools/solver/solve.py packs/twinseed/levels/tw_007.json --mode astar --max-depth 45 --timeout 60
```

---

## tw_008 — Stoneseed (25 moves)

Introduces the pickaxe: the path to both plots is blocked by rocks, so the
avatar must grab the pickaxe before tackling either basket. Clone required
three times to stage positions around the rock wall.

```
python3 tools/solver/solve.py packs/twinseed/levels/tw_008.json --mode astar --max-depth 30 --timeout 60
```
