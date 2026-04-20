#!/usr/bin/env python3
"""
mutate_and_test.py — generate level variations by mutation + solver validation.

Takes a seed level JSON, applies random structural mutations (repositioning
entities within sparse layers, swapping cells in dense layers), evaluates
each candidate with the solver, and returns the N best passing candidates.

All mutations are DSL-generic: they operate on the board.layers structure
directly without any game-specific knowledge.  Game-specific validity (e.g.
box_builder fragment pairing) is verified before evaluation.

Usage:
    python3 tools/solver/mutate_and_test.py <level.json> [options]

Criterion formats (--criterion, repeatable, all must pass):
    solution_length:min=N:max=M
    event_count:event=boxes_merged:min=N:max=M
    mc_difficulty:min=D:max=D

Constraint filters (--require-constraint / --forbid-constraint, repeatable):
    JSON constraint dicts passed to the solver; a candidate passes only when:
      --require-constraint: a solution EXISTS under this constraint
      --forbid-constraint:  NO solution exists under this constraint
    Same format as solve.py --constraint.

Examples:
    # 10 box_builder variants with 25-45 move solutions, MC > 8 bits:
    python3 tools/solver/mutate_and_test.py packs/box_builder/levels/bb_016.json \\
        --candidates 10 --mutations 3 --mode astar --max-depth 45 --timeout 180 \\
        --criterion solution_length:min=25:max=45 \\
        --mc-trials 5000 --criterion mc_difficulty:min=8.0 \\
        --output-dir /tmp/bb_variants/

    # Variants requiring at least 2 box merges:
    python3 tools/solver/mutate_and_test.py packs/box_builder/levels/bb_012.json \\
        --criterion event_count:event=boxes_merged:min=2 \\
        --mode astar --max-depth 35 --workers 4

    # Variants where rock at some position MUST be broken (non-obvious rock theme):
    python3 tools/solver/mutate_and_test.py packs/box_builder/levels/bb_017.json \\
        --forbid-constraint '{"type":"must_not","event":"object_removed","kind":"rock"}' \\
        --mode astar --max-depth 35

    # Deep levels (30+ moves): twophase is much faster than astar.
    # Phase 1 (BFS up to min-1 moves) rules out short solutions — complete proof.
    # Phase 2 (A*) finds a solution >= min quickly via the heuristic, confirming solvability.
    python3 tools/solver/mutate_and_test.py packs/carrot_quest/levels/fw_ice_013.json \\
        --mode twophase --max-depth 45 --timeout 60 \\
        --criterion solution_length:min=25:max=45 \\
        --mc-trials 5000 --criterion mc_difficulty:min=8.0
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import multiprocessing
import random
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_SOLVER_DIR = Path(__file__).parent
_REPO_ROOT = _SOLVER_DIR.parent.parent  # platform/
sys.path.insert(0, str(_SOLVER_DIR))
# Also add the repo root so the parent process can unpickle engine types (Pos, etc.)
# that appear in event dicts returned by worker subprocesses.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from game_configs import GAME_CONFIGS


# ---------------------------------------------------------------------------
# Game detection
# ---------------------------------------------------------------------------

def _detect_game(path: Path) -> str:
    for part in path.parts:
        if part == "number_cells":
            return "number_crunch"
        if part == "rotate_flip":
            return "rotate_flip"
        if part == "box_builder":
            return "box_builder"
        if part == "flood_colors":
            return "flood_colors"
        if part == "carrot_quest":
            return "carrot_quest"
        if part == "twinseed":
            return "twinseed"
    raise ValueError(
        f"Cannot detect game from path: {path}\n"
        "  Ensure the path contains the pack folder name (e.g. box_builder)."
    )


# ---------------------------------------------------------------------------
# DSL layer helpers
# ---------------------------------------------------------------------------

def _get_walkable_cells(level_json: Dict) -> Set[Tuple[int, int]]:
    """Return the set of (x, y) cells that are not void."""
    board = level_json["board"]
    cols, rows = board["size"]
    layers = board["layers"]
    ground = layers.get("ground")

    if ground is None:
        return {(x, y) for x in range(cols) for y in range(rows)}

    if isinstance(ground, list):
        walkable: Set[Tuple[int, int]] = set()
        for y, row in enumerate(ground):
            for x, kind in enumerate(row):
                if kind != "void":
                    walkable.add((x, y))
        return walkable

    if isinstance(ground, dict):
        # Sparse ground layer (uncommon)
        all_cells = {(x, y) for x in range(cols) for y in range(rows)}
        void_cells = {
            (e["position"][0], e["position"][1])
            for e in ground.get("entries", [])
            if e.get("kind") == "void"
        }
        return all_cells - void_cells

    return {(x, y) for x in range(cols) for y in range(rows)}


def _sparse_positions(layer_data: Dict) -> Set[Tuple[int, int]]:
    return {(e["position"][0], e["position"][1]) for e in layer_data.get("entries", [])}


# ---------------------------------------------------------------------------
# Mutation primitives
# ---------------------------------------------------------------------------

def _mutate_sparse(
    layer_data: Dict,
    mutable_kinds: Optional[List[str]],
    walkable: Set[Tuple[int, int]],
    rng: random.Random,
) -> Optional[Dict]:
    """Move a random entry to a different empty walkable cell."""
    entries = layer_data.get("entries", [])
    if not entries:
        return None

    if mutable_kinds is not None:
        candidate_indices = [i for i, e in enumerate(entries) if e["kind"] in mutable_kinds]
    else:
        candidate_indices = list(range(len(entries)))

    if not candidate_indices:
        return None

    idx = rng.choice(candidate_indices)
    current_pos = (entries[idx]["position"][0], entries[idx]["position"][1])

    # Positions occupied by OTHER entries in this layer
    other_occupied = {
        (e["position"][0], e["position"][1])
        for i, e in enumerate(entries) if i != idx
    }
    available = list(walkable - other_occupied - {current_pos})
    if not available:
        return None

    new_pos = rng.choice(available)
    new_entries = []
    for i, e in enumerate(entries):
        if i == idx:
            moved = dict(e)
            moved["position"] = list(new_pos)
            new_entries.append(moved)
        else:
            new_entries.append(e)

    return {"format": "sparse", "entries": new_entries}


def _mutate_dense(
    layer_data: List,
    mutable_kinds: Optional[List[str]],
    rng: random.Random,
) -> Optional[List]:
    """Swap two random cells with different values in a dense layer."""
    if not layer_data:
        return None
    rows_count = len(layer_data)
    cols_count = len(layer_data[0])

    if mutable_kinds is not None:
        cells = [
            (x, y)
            for y in range(rows_count)
            for x in range(cols_count)
            if layer_data[y][x] in mutable_kinds
        ]
    else:
        cells = [(x, y) for y in range(rows_count) for x in range(cols_count)]

    if len(cells) < 2:
        return None

    for _ in range(30):
        (x1, y1), (x2, y2) = rng.sample(cells, 2)
        if layer_data[y1][x1] != layer_data[y2][x2]:
            new_grid = [list(row) for row in layer_data]
            new_grid[y1][x1], new_grid[y2][x2] = new_grid[y2][x2], new_grid[y1][x1]
            return new_grid

    return None  # All sampled pairs had the same value


# ---------------------------------------------------------------------------
# Top-level mutation
# ---------------------------------------------------------------------------

def _mutate(
    level_json: Dict,
    config: Dict,
    rng: random.Random,
    n_mutations: int,
) -> Optional[Dict]:
    """
    Deep-copy level_json and apply n_mutations random DSL-level mutations.

    Mutations only reposition entities; kinds and parameters (e.g. fragment
    sides) are preserved.  Returns None if no mutations could be applied.
    """
    result = copy.deepcopy(level_json)
    result.pop("solution", None)
    result.pop("metadata", None)

    layers = result["board"]["layers"]
    walkable = _get_walkable_cells(result)

    applied = 0
    # Allow extra attempts in case some mutations fail (e.g. no available cell)
    for _ in range(n_mutations * 6):
        if applied >= n_mutations:
            break

        # Build menu of possible operations from the game config
        ops: List[Tuple[str, str, Dict]] = []
        for layer_name, lcfg in config["mutable_layers"].items():
            layer_data = layers.get(layer_name)
            if layer_data is None:
                continue
            if isinstance(layer_data, dict) and layer_data.get("format") == "sparse":
                ops.append(("sparse", layer_name, lcfg))
            elif isinstance(layer_data, list):
                ops.append(("dense", layer_name, lcfg))

        if config.get("mutable_avatar"):
            avatar = result.get("state", {}).get("avatar", {})
            if avatar.get("enabled", True):
                ops.append(("avatar", "", {}))

        if not ops:
            return None

        op_type, layer_name, lcfg = rng.choice(ops)

        if op_type == "sparse":
            new_layer = _mutate_sparse(
                layers[layer_name],
                lcfg.get("mutable_kinds"),
                walkable,
                rng,
            )
            if new_layer is not None:
                layers[layer_name] = new_layer
                if layer_name == "ground":
                    walkable = _get_walkable_cells(result)  # shape changed (sparse void move)
                applied += 1

        elif op_type == "dense":
            new_layer = _mutate_dense(
                layers[layer_name],
                lcfg.get("mutable_kinds"),
                rng,
            )
            if new_layer is not None:
                layers[layer_name] = new_layer
                if layer_name == "ground":
                    walkable = _get_walkable_cells(result)  # recompute after shape change
                applied += 1

        elif op_type == "avatar":
            state = result["state"]
            ax, ay = state["avatar"]["position"]
            current_pos = (ax, ay)
            # Avoid placing avatar on a cell occupied by any sparse-layer object
            all_objects: Set[Tuple[int, int]] = set()
            for lname, ldata in layers.items():
                if isinstance(ldata, dict) and ldata.get("format") == "sparse":
                    all_objects |= _sparse_positions(ldata)
            available = list(walkable - all_objects - {current_pos})
            if available:
                new_pos = rng.choice(available)
                result["state"]["avatar"]["position"] = list(new_pos)
                applied += 1

    return result if applied > 0 else None


# ---------------------------------------------------------------------------
# Structural validity
# ---------------------------------------------------------------------------

def _bb_valid(level_json: Dict) -> bool:
    """
    Box Builder: use the A* heuristic as a validity gate.

    The heuristic returns inf when no valid fragment grouping exists (e.g.
    after a mutation creates a set of fragments that cannot OR to 15).
    Calling it on the initial state is fast (< 1 ms for typical levels).
    """
    try:
        import games.box_builder as bb
        initial, info = bb.load(level_json)
        return bb.heuristic(initial, info) != float("inf")
    except Exception:
        return False


def _twinseed_valid(level_json: Dict) -> bool:
    """Twinseed: reject levels with
       (a) a seed_basket already on a garden_plot, or
       (b) any object sitting on a void cell (unreachable, purely cosmetic clutter).
    """
    layers = level_json["board"]["layers"]
    ground = layers.get("ground", {})
    objects = layers.get("objects", {})
    plots = {
        (e["position"][0], e["position"][1])
        for e in ground.get("entries", [])
        if e.get("kind") == "garden_plot"
    }
    voids = {
        (e["position"][0], e["position"][1])
        for e in ground.get("entries", [])
        if e.get("kind") == "void"
    }
    for e in objects.get("entries", []):
        pos = (e["position"][0], e["position"][1])
        if pos in voids:
            return False
        if e.get("kind") == "seed_basket" and pos in plots:
            return False
    return True


def _is_structurally_valid(level_json: Dict, game: str) -> bool:
    """
    Return True iff the mutated level passes basic structural checks:
    - All sparse entries within board bounds
    - No two entries at the same position in the same sparse layer
    - Avatar (if enabled) on a walkable cell
    - Game-specific check (box_builder fragment pairing)
    """
    board = level_json["board"]
    cols, rows = board["size"]
    layers = board["layers"]

    for layer_data in layers.values():
        if not (isinstance(layer_data, dict) and layer_data.get("format") == "sparse"):
            continue
        positions = []
        for entry in layer_data.get("entries", []):
            x, y = entry["position"]
            if not (0 <= x < cols and 0 <= y < rows):
                return False
            positions.append((x, y))
        if len(positions) != len(set(positions)):
            return False  # Overlap within layer

    avatar = level_json.get("state", {}).get("avatar", {})
    if avatar.get("enabled", True) and "position" in avatar:
        ax, ay = avatar["position"]
        if (ax, ay) not in _get_walkable_cells(level_json):
            return False

    if game == "box_builder":
        return _bb_valid(level_json)
    if game == "twinseed":
        return _twinseed_valid(level_json)

    return True


# ---------------------------------------------------------------------------
# Evaluation worker  (module-level — required for multiprocessing spawn)
# ---------------------------------------------------------------------------

def _evaluate_worker(task: Dict[str, Any]) -> Dict[str, Any]:
    """
    Solve one candidate level and return metrics.  Runs in a subprocess.

    The task dict must contain only picklable types (JSON-compatible).
    Returns a result dict with keys: ok, solution_length, solution_path,
    events, mc_bits, solve_rate, timed_out, candidate_idx.
    """
    import sys, math
    from pathlib import Path
    from collections import deque

    solver_dir = task["solver_dir"]
    if solver_dir not in sys.path:
        sys.path.insert(0, solver_dir)

    level_json = task["level_json"]
    game = task["game"]
    mode = task["mode"]
    max_depth = task["max_depth"]
    timeout = task["timeout"]
    mc_trials = task["mc_trials"]
    mc_steps = task["mc_steps"]
    candidate_idx = task["candidate_idx"]

    require_constraints: List[Dict] = task.get("require_constraints", [])
    forbid_constraints: List[Dict] = task.get("forbid_constraints", [])

    base = {"ok": False, "solution_length": None, "solution_path": None,
            "events": [], "mc_bits": None, "solve_rate": None,
            "timed_out": False, "candidate_idx": candidate_idx,
            "constraints_ok": True}

    use_cython = bool(task.get("cython"))

    # Load game module
    try:
        if game == "box_builder":
            import games.box_builder as module
        elif game == "rotate_flip":
            import games.rotate_flip as module
        elif game == "number_crunch":
            import games.number_crunch as module
        elif game == "carrot_quest":
            import games.carrot_quest as module
        elif game == "twinseed":
            if use_cython:
                import games.twinseed_cy as module
            else:
                import games.twinseed as module
        else:
            base["error"] = f"No solver for game '{game}'"
            return base
        initial, info = module.load(level_json)
    except Exception as e:
        base["error"] = str(e)
        return base

    solution_path: Optional[List[str]] = None
    all_events: List[Dict] = []

    try:
        if mode == "astar":
            from search.astar import astar
            sol = astar(initial, info, module, timeout, [], max_depth=max_depth)
            if sol.timed_out:
                base["timed_out"] = True
                base["ok"] = True
                return base
            if sol.path:
                solution_path = sol.path
                all_events = [e for step_evts in sol.events for e in step_evts]

        elif mode == "twophase":
            # Two-phase check for deep levels:
            #
            # Phase 1 — BFS up to (min_length - 1): rule out short solutions.
            #   If BFS finds any solution here, the candidate is too easy.
            #
            # Phase 2 — A* (BFS fallback when no heuristic): confirm the level IS
            #   solvable by finding any path ≥ min_length. A* races toward the goal
            #   via the heuristic, stopping at the first valid win. No optimality
            #   proof needed — Phase 1 already ruled out easy wins.
            #
            # Together these answer: "no trivial path exists AND a long path does."
            #
            # "min_length" is inferred from the solution_length:min=N criterion.
            # If absent, falls back to plain BFS (same as before).
            import time as _time

            # Extract min_length from task criteria (passed via task dict)
            min_length: int = task.get("twophase_min", 0)
            phase1_cap = max(0, min_length - 1)
            deadline = _time.monotonic() + timeout

            # --- Phase 1: BFS exhaustion up to phase1_cap ---
            too_easy = False
            if phase1_cap > 0:
                bfs_queue: deque = deque([(initial, [])])
                bfs_visited: Dict = {initial: 0}
                while bfs_queue:
                    if _time.monotonic() > deadline:
                        base["timed_out"] = True
                        base["ok"] = True
                        return base
                    bfs_state, bfs_path = bfs_queue.popleft()
                    bfs_depth = len(bfs_path)
                    if bfs_depth >= phase1_cap:
                        continue
                    for action in module.ACTIONS:
                        ns, won, _ = module.apply(bfs_state, action, info)
                        nd = bfs_depth + 1
                        if won:
                            too_easy = True
                            break
                        if module.can_prune(ns, info, nd, phase1_cap):
                            continue
                        prev = bfs_visited.get(ns)
                        if prev is not None and prev <= nd:
                            continue
                        bfs_visited[ns] = nd
                        bfs_queue.append((ns, bfs_path + [action]))
                    if too_easy:
                        break

            if too_easy:
                # Found a solution shorter than min_length — not interesting
                base["ok"] = True  # valid, just fails solution_length criterion
                return base

            # --- Phase 2: A* (or BFS fallback) to confirm solvability ---
            # Use A* when the module has a heuristic: the heuristic guides the
            # search toward the goal, finding a solution much faster than BFS on
            # deep levels. We accept the first win >= min_length and stop — no
            # optimality proof needed, just confirmation a long path exists.
            # Falls back to BFS for games without a heuristic.
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                base["timed_out"] = True
                base["ok"] = True
                return base

            found_path: Optional[List[str]] = None

            if hasattr(module, "heuristic"):
                # A* phase 2: custom loop with a min_length gate on wins.
                # Races toward the goal via the heuristic; stops at the first
                # win >= min_length without proving optimality.
                import heapq as _heapq

                heuristic_fn = module.heuristic
                p2_visited: Dict = {initial: (0, None, None)}
                h0 = heuristic_fn(initial, info)
                _ctr = 0
                p2_heap: list = [(h0, 0, _ctr, initial)]

                while p2_heap:
                    if _time.monotonic() > deadline:
                        base["timed_out"] = True
                        base["ok"] = True
                        return base
                    _, _g, _, _state = _heapq.heappop(p2_heap)
                    cur_g = p2_visited[_state][0]
                    if cur_g < _g:
                        continue
                    if _g >= max_depth:
                        continue
                    for action in module.ACTIONS:
                        ns, won, _ = module.apply(_state, action, info)
                        nd = _g + 1
                        if won:
                            if nd >= min_length:
                                # Reconstruct path
                                path_rev = [action]
                                cur = _state
                                while p2_visited[cur][1] is not None:
                                    _, par, act = p2_visited[cur]
                                    path_rev.append(act)
                                    cur = par
                                path_rev.reverse()
                                found_path = path_rev
                                break
                            # win but too short — continue searching
                            continue
                        if nd >= max_depth:
                            continue
                        if module.can_prune(ns, info, nd, max_depth):
                            continue
                        prev = p2_visited.get(ns)
                        if prev is not None and prev[0] <= nd:
                            continue
                        nh = heuristic_fn(ns, info)
                        if nh == float("inf"):
                            continue
                        p2_visited[ns] = (nd, _state, action)
                        _ctr += 1
                        _heapq.heappush(p2_heap, (nd + nh, nd, _ctr, ns))
                    if found_path:
                        break
            else:
                # BFS fallback when no heuristic is available
                p2_queue: deque = deque([(initial, [])])
                p2_bfs_visited: Dict = {initial: 0}

                while p2_queue:
                    if _time.monotonic() > deadline:
                        base["timed_out"] = True
                        base["ok"] = True
                        return base
                    p2_state, p2_path = p2_queue.popleft()
                    p2_depth = len(p2_path)
                    if p2_depth >= max_depth:
                        continue
                    for action in module.ACTIONS:
                        ns, won, _ = module.apply(p2_state, action, info)
                        nd = p2_depth + 1
                        if won:
                            if nd >= min_length:
                                found_path = p2_path + [action]
                                break
                            continue
                        if module.can_prune(ns, info, nd, max_depth):
                            continue
                        prev = p2_bfs_visited.get(ns)
                        if prev is not None and prev <= nd:
                            continue
                        p2_bfs_visited[ns] = nd
                        p2_queue.append((ns, p2_path + [action]))
                    if found_path:
                        break

            if found_path is not None:
                solution_path = found_path
                state = initial
                for action in found_path:
                    state, _, step_evts = module.apply(state, action, info)
                    all_events.extend(step_evts)

        else:
            # BFS — finds shortest solution
            bfs_q: deque = deque([(initial, [])])
            bfs_vis: Dict = {initial: 0}
            shortest: Optional[int] = None
            best_path: Optional[List[str]] = None

            while bfs_q:
                state, path = bfs_q.popleft()
                depth = len(path)
                if shortest is not None and depth >= shortest:
                    continue
                if depth >= max_depth:
                    continue
                for action in module.ACTIONS:
                    new_state, won, _ = module.apply(state, action, info)
                    new_depth = depth + 1
                    new_path = path + [action]
                    if won:
                        if shortest is None:
                            best_path = new_path
                            shortest = new_depth
                        continue
                    if module.can_prune(new_state, info, new_depth, max_depth):
                        continue
                    prev = bfs_vis.get(new_state)
                    if prev is not None and prev <= new_depth:
                        continue
                    bfs_vis[new_state] = new_depth
                    bfs_q.append((new_state, new_path))

            if best_path is not None:
                solution_path = best_path
                # Replay path to collect events
                state = initial
                for action in best_path:
                    state, _, step_evts = module.apply(state, action, info)
                    all_events.extend(step_evts)

    except Exception as e:
        base["error"] = str(e)
        return base

    # --- Extract events via engine-adapter replay (Cython apply returns []) ---
    if solution_path and use_cython and game == "twinseed":
        try:
            import games.twinseed as _tw_slow
            _init_slow, _info_slow = _tw_slow.load(level_json)
            _state = _init_slow
            all_events = []
            for action in solution_path:
                _state, _, step_evts = _tw_slow.apply(_state, action, _info_slow)
                all_events.extend(step_evts)
        except Exception:
            all_events = []

    # --- Constraint filter checks ---
    # Each require_constraint must have a solution; each forbid_constraint must not.
    constraints_ok = True
    if solution_path and (require_constraints or forbid_constraints):
        try:
            from search.astar import astar as _astar
            # forbid_constraints: solve WITH the constraint — must find no solution
            for fc in forbid_constraints:
                sol_fc = _astar(initial, info, module, timeout, [fc],
                                max_depth=max_depth)
                if sol_fc.timed_out or sol_fc.path:
                    constraints_ok = False
                    break
            # require_constraints: solve WITH the constraint — must find a solution
            if constraints_ok:
                for rc in require_constraints:
                    sol_rc = _astar(initial, info, module, timeout, [rc],
                                    max_depth=max_depth)
                    if sol_rc.timed_out or not sol_rc.path:
                        constraints_ok = False
                        break
        except Exception:
            constraints_ok = False

    # Compute interaction score from events
    _IRREVERSIBLE_W = {"object_removed", "bridge_created", "ground_transformed"}
    _REVERSIBLE_W   = {"object_pushed", "inventory_changed"}
    interaction_score = 0
    for e in all_events:
        etype = e.get("type", "")
        if etype in _IRREVERSIBLE_W:
            interaction_score += 3
        elif etype in _REVERSIBLE_W:
            interaction_score += 2
        elif etype == "avatar_entered":
            interaction_score += 1

    result = {
        "ok": True,
        "solution_length": len(solution_path) if solution_path else None,
        "solution_path": solution_path,
        "events": all_events,
        "interaction_score": interaction_score,
        "mc_bits": None,
        "solve_rate": None,
        "timed_out": False,
        "candidate_idx": candidate_idx,
        "constraints_ok": constraints_ok,
    }

    if solution_path and mc_trials > 0:
        try:
            import random as _random
            steps = mc_steps or max(100, 3 * len(solution_path))
            rng_mc = _random.Random(42)
            actions = module.ACTIONS
            n_actions = len(actions)
            successes = 0
            for _ in range(mc_trials):
                state = initial
                for _ in range(steps):
                    action = actions[rng_mc.randrange(n_actions)]
                    state, won, _ = module.apply(state, action, info)
                    if won:
                        successes += 1
                        break
            sr = successes / mc_trials
            result["solve_rate"] = sr
            result["mc_bits"] = -math.log2(sr) if sr > 0 else float("inf")
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Criteria
# ---------------------------------------------------------------------------

def _parse_criteria(specs: List[str]) -> List[Dict[str, str]]:
    """
    Parse criterion specs into dicts.

    Examples:
      "solution_length:min=30:max=45"  →  {ctype: solution_length, min: 30, max: 45}
      "event_count:event=boxes_merged:min=2"  →  {ctype: event_count, event: ..., min: 2}
      "mc_difficulty:min=8.0"  →  {ctype: mc_difficulty, min: 8.0}
    """
    criteria = []
    for spec in specs:
        parts = spec.split(":")
        ctype = parts[0]
        params: Dict[str, str] = {}
        for part in parts[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                params[k] = v
        criteria.append({"ctype": ctype, **params})
    return criteria


def _needs_mc(criteria: List[Dict]) -> bool:
    return any(c["ctype"] == "mc_difficulty" for c in criteria)


def _check_criteria(result: Dict, criteria: List[Dict]) -> bool:
    if not result.get("ok") or result.get("timed_out"):
        return False
    if result.get("solution_length") is None:
        return False
    if not result.get("constraints_ok", True):
        return False

    for crit in criteria:
        ctype = crit["ctype"]

        if ctype == "solution_length":
            length = result["solution_length"]
            if "min" in crit and length < int(crit["min"]):
                return False
            if "max" in crit and length > int(crit["max"]):
                return False

        elif ctype == "event_count":
            event_type = crit.get("event", "")
            count = sum(1 for e in result.get("events", []) if e.get("type") == event_type)
            if "min" in crit and count < int(crit["min"]):
                return False
            if "max" in crit and count > int(crit["max"]):
                return False

        elif ctype == "mc_difficulty":
            bits = result.get("mc_bits")
            if bits is None:
                return False
            if "min" in crit and bits < float(crit["min"]):
                return False
            if "max" in crit and bits > float(crit["max"]):
                return False

    return True


# ---------------------------------------------------------------------------
# Interaction scoring
# ---------------------------------------------------------------------------

# Irreversible events (3 pts each).
_IRREVERSIBLE_EVENTS: set = {
    "object_removed",      # rock broken (pickaxe), wood burned (torch)
    "bridge_created",      # crate-into-water
    "ground_transformed",  # torch melts ice / pickaxe breaks ice
}


def score_solution(events: List[Dict]) -> int:
    """
    Score a solution by its event richness.

    Scoring rules:
      - avatar_entered           : 1 point  (plain move or ice slide step)
      - reversible action        : 2 points (object_pushed, inventory_changed)
      - irreversible action      : 3 points (object_removed, bridge_created,
                                             ground_transformed)
      - all other event types    : 0 points
    """
    score = 0
    for e in events:
        etype = e.get("type", "")
        if etype in _IRREVERSIBLE_EVENTS:
            score += 3
        elif etype in {"object_pushed", "inventory_changed"}:
            score += 2
        elif etype == "avatar_entered":
            score += 1
    return score


# ---------------------------------------------------------------------------
# Gold path formatting (for saved candidates)
# ---------------------------------------------------------------------------

def _path_to_gold(path: List[str], game: str) -> List[Dict]:
    """Convert a flat action list to the DSL goldPath format."""
    if game == "box_builder":
        return [{"action": "move", "direction": d} for d in path]
    if game == "rotate_flip":
        gold = []
        for a in path:
            if a.startswith("move_"):
                gold.append({"action": "move", "direction": a[4:]})
            else:
                gold.append({"action": a})
        return gold
    if game == "number_crunch":
        return [{"direction": d} for d in path]
    if game in ("carrot_quest", "twinseed"):
        gold = []
        for a in path:
            if a.startswith("move_"):
                gold.append(a[5:])  # shorthand: "left", "right", etc.
            else:
                gold.append(a)  # shorthand: "clone", etc.
        return gold
    # Fallback
    return [{"action": a} for a in path]


def _hint_stops(path_length: int) -> List[int]:
    """Return a reasonable hint stop at ~1/3 of the gold path."""
    if path_length <= 2:
        return []
    stop = max(1, path_length // 3)
    return [stop]


# ---------------------------------------------------------------------------
# Distribution summary (debugging aid when no candidates pass)
# ---------------------------------------------------------------------------

def _print_distribution(results: List[Dict]) -> None:
    ok = [r for r in results if r.get("ok") and not r.get("timed_out")]
    solved = [r for r in ok if r.get("solution_length") is not None]
    timed_out = sum(1 for r in results if r.get("timed_out"))
    failed = sum(1 for r in results if not r.get("ok"))

    print(f"  Breakdown: {len(solved)} solved / {timed_out} timed-out / {failed} error "
          f"/ {len(ok) - len(solved)} no-solution")

    if solved:
        lengths = sorted(r["solution_length"] for r in solved)
        print(f"  Solution lengths: min={min(lengths)}, "
              f"median={lengths[len(lengths) // 2]}, max={max(lengths)}")
        bits_list = sorted(r["mc_bits"] for r in solved if r.get("mc_bits") is not None)
        if bits_list:
            print(f"  MC difficulty bits: min={min(bits_list):.1f}, "
                  f"max={max(bits_list):.1f}")


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def _run(args: argparse.Namespace) -> None:
    path = Path(args.level)
    with open(path) as f:
        seed_json: Dict = json.load(f)

    game = _detect_game(path)
    config = GAME_CONFIGS.get(game)
    if config is None:
        print(f"Error: no mutation config for game '{game}'", file=sys.stderr)
        sys.exit(1)
    if config.get("game_module") is None:
        print(f"Error: game '{game}' has no solver — cannot evaluate candidates",
              file=sys.stderr)
        sys.exit(1)

    criteria = _parse_criteria(args.criterion)
    mc_trials = args.mc_trials
    if _needs_mc(criteria) and mc_trials == 0:
        mc_trials = 1000
        print(f"Note: mc_difficulty criterion active — auto-enabling --mc-trials {mc_trials}")

    mode = args.mode
    if mode == "astar" and not config.get("has_heuristic"):
        print(f"Note: '{game}' has no A* heuristic — using BFS")
        mode = "bfs"

    # For twophase mode, extract min_length from solution_length criterion
    twophase_min = 0
    if mode == "twophase":
        for c in criteria:
            if c["ctype"] == "solution_length" and "min" in c:
                twophase_min = int(c["min"])
                break
        if twophase_min == 0:
            print("Note: twophase mode works best with --criterion solution_length:min=N; "
                  "no min found, Phase 1 BFS will be skipped.")

    seed_id = seed_json.get("id", path.stem)
    print(f"Seed: {seed_id}  ({game})")
    mode_detail = f"twophase (min={twophase_min})" if mode == "twophase" else mode
    print(f"Mode: {mode_detail},  max-depth={args.max_depth},  timeout={args.timeout}s")
    print(f"Mutations/candidate: {args.mutations},  workers: {args.workers}")
    if args.criterion:
        print(f"Criteria: {args.criterion}")
    if getattr(args, "require_constraint", []):
        print(f"Require constraints: {args.require_constraint}")
    if getattr(args, "forbid_constraint", []):
        print(f"Forbid constraints: {args.forbid_constraint}")
    print()

    rng = random.Random(args.seed)
    solver_dir = str(Path(__file__).parent)

    # --- Phase 1: Generate structurally-valid mutations (fast, serial) ---
    print(f"Generating candidates from {args.attempts} mutation attempts...",
          end=" ", flush=True)
    candidates: List[Dict] = []
    rejected_count = 0
    for _ in range(args.attempts):
        mutated = _mutate(seed_json, config, rng, args.mutations)
        if mutated is None:
            rejected_count += 1
            continue
        if not _is_structurally_valid(mutated, game):
            rejected_count += 1
            continue
        candidates.append(mutated)

    print(f"{len(candidates)} valid  ({rejected_count} rejected)")

    if not candidates:
        print("No valid candidates generated.  Try increasing --attempts or --mutations.")
        return

    # --- Phase 2: Evaluate candidates in parallel ---
    require_constraints = [json.loads(s) for s in getattr(args, "require_constraint", [])]
    forbid_constraints = [json.loads(s) for s in getattr(args, "forbid_constraint", [])]

    tasks = [
        {
            "level_json": c,
            "game": game,
            "mode": mode,
            "max_depth": args.max_depth,
            "timeout": args.timeout,
            "mc_trials": mc_trials,
            "mc_steps": args.mc_steps,
            "candidate_idx": i,
            "solver_dir": solver_dir,
            "require_constraints": require_constraints,
            "forbid_constraints": forbid_constraints,
            "twophase_min": twophase_min,
            "cython": args.cython,
        }
        for i, c in enumerate(candidates)
    ]

    n_workers = min(args.workers, len(tasks))
    print(f"Evaluating {len(tasks)} candidates ({n_workers} workers)...",
          end=" ", flush=True)
    t0 = time.monotonic()

    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=n_workers) as pool:
        results = pool.map(_evaluate_worker, tasks)

    elapsed = time.monotonic() - t0
    print(f"done in {elapsed:.1f}s")
    print()

    # --- Phase 3: Filter and rank ---
    n_solved = sum(1 for r in results
                   if r.get("ok") and r.get("solution_length") is not None)
    n_timed_out = sum(1 for r in results if r.get("timed_out"))

    required_actions: List[str] = list(getattr(args, "must_contain_action", []))

    def _passes_action_filter(r: Dict) -> bool:
        if not required_actions:
            return True
        path = r.get("solution_path") or []
        return all(any(a == req or a == f"move_{req}" for a in path)
                   for req in required_actions)

    passing = [
        (candidates[r["candidate_idx"]], r)
        for r in results
        if _check_criteria(r, criteria) and _passes_action_filter(r)
    ]

    print(f"Solved: {n_solved}/{len(candidates)}  "
          f"Timed-out: {n_timed_out}  "
          f"Passing criteria: {len(passing)}")
    print()

    if not passing:
        print("No candidates passed all criteria.")
        _print_distribution(results)
        return

    # Sort: highest interaction score first; tiebreak by MC bits (harder), then shorter
    def _sort_key(item: Tuple[Dict, Dict]) -> Tuple[int, float, int]:
        _, res = item
        score = res.get("interaction_score") or 0
        bits = res.get("mc_bits") or 0.0
        length = res.get("solution_length") or 0
        return (-score, -bits, length)

    passing.sort(key=_sort_key)
    top = passing[:args.candidates]

    # --- Phase 4: Report ---
    print(f"Top {len(top)} candidates (sorted by interaction score):")
    print()
    header = f"  {'#':>3}  {'score':>6}  {'moves':>5}  {'mc_bits':>8}  notes"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for rank, (level_json, res) in enumerate(top, 1):
        length = res.get("solution_length", "?")
        bits = res.get("mc_bits")
        iscore = res.get("interaction_score") or 0
        events = res.get("events", [])
        merges = sum(1 for e in events if e.get("type") == "boxes_merged")
        rocks_broken = sum(1 for e in events if e.get("type") == "object_removed"
                           and e.get("kind") == "rock")
        pushes = sum(1 for e in events if e.get("type") == "object_pushed")
        pickups = sum(1 for e in events if e.get("type") == "inventory_changed")
        transforms = sum(1 for e in events if e.get("type") == "ground_transformed")

        bits_str = f"{bits:.1f}" if bits is not None else "—"
        notes = []
        if merges:
            notes.append(f"merges={merges}")
        if rocks_broken:
            notes.append(f"rocks={rocks_broken}")
        if pushes:
            notes.append(f"pushes={pushes}")
        if pickups:
            notes.append(f"pickups={pickups}")
        if transforms:
            notes.append(f"transforms={transforms}")

        print(f"  {rank:>3}  {iscore:>6}  {length:>5}  {bits_str:>8}  "
              f"{', '.join(notes)}")

    print()

    # --- Phase 5: Save ---
    if args.output_dir:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        for rank, (level_json, res) in enumerate(top, 1):
            out_json = copy.deepcopy(level_json)
            out_json["id"] = f"{seed_id}_mut_{rank:03d}"
            out_json["title"] = f"[Mutation {rank}] {seed_json.get('title', seed_id)}"

            # Embed solved gold path so the candidate is ready to register
            sol_path = res.get("solution_path")
            if sol_path:
                gold = _path_to_gold(sol_path, game)
                hint_stops = _hint_stops(len(sol_path))
                solution_block: Dict[str, Any] = {"goldPath": gold}
                if hint_stops:
                    solution_block["hintStops"] = hint_stops
                out_json["solution"] = solution_block

            out_json["metadata"] = {
                "source": seed_id,
                "mutation_rank": rank,
                "solution_length": res.get("solution_length"),
                "interaction_score": res.get("interaction_score"),
                "mc_bits": round(res.get("mc_bits") or 0.0, 2),
                "solve_rate": res.get("solve_rate"),
            }

            out_path = out_dir / f"{seed_id}_mut_{rank:03d}.json"
            with open(out_path, "w") as f:
                json.dump(out_json, f, indent=2)

        print(f"Saved {len(top)} candidate(s) to {out_dir}/")
        print()

    print("Done.  Next steps:")
    print("  1. Inspect candidates and pick the most interesting one.")
    print("  2. Review and adjust the goldPath (solver finds optimal, "
          "not necessarily most pedagogical).")
    print("  3. Add hintStops before critical decision points.")
    print("  4. Update the title and register in game.json.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate level variations by mutation + solver validation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("level", help="Seed level JSON file")
    parser.add_argument(
        "--candidates", type=int, default=10, metavar="N",
        help="Number of passing candidates to collect (default: 10)",
    )
    parser.add_argument(
        "--mutations", type=int, default=2, metavar="K",
        help="Mutations to apply per candidate (default: 2)",
    )
    parser.add_argument(
        "--attempts", type=int, default=0, metavar="N",
        help="Max mutation attempts (default: 20 × --candidates)",
    )
    parser.add_argument(
        "--mode", choices=["bfs", "astar", "twophase"], default="astar",
        help=(
            "Search algorithm (default: astar). "
            "'twophase': fast mode for deep levels — BFS up to (min-1) rules out "
            "short solutions, then BFS confirms the level is solvable (any path ≥ min). "
            "Skips A*'s expensive optimality proof. "
            "Best used with --criterion solution_length:min=N."
        ),
    )
    parser.add_argument(
        "--max-depth", type=int, default=40, metavar="N",
        help="Max search depth per candidate (default: 40)",
    )
    parser.add_argument(
        "--timeout", type=float, default=180.0, metavar="S",
        help="A* wall-clock timeout per candidate in seconds (default: 180)",
    )
    parser.add_argument(
        "--mc-trials", type=int, default=0, metavar="N",
        help="Monte Carlo trials per candidate (default: 0 = off)",
    )
    parser.add_argument(
        "--mc-steps", type=int, default=0, metavar="N",
        help="Max steps per MC trial (default: 3 × solution length)",
    )
    parser.add_argument(
        "--criterion", action="append", default=[], metavar="SPEC",
        help=(
            "Filter criterion (repeatable; all must pass). Formats:\n"
            "  solution_length:min=N:max=M\n"
            "  event_count:event=TYPE:min=N:max=M\n"
            "  mc_difficulty:min=D:max=D"
        ),
    )
    parser.add_argument(
        "--require-constraint", action="append", default=[], metavar="JSON",
        dest="require_constraint",
        help=(
            "Constraint JSON (repeatable). Candidate passes only if a solution "
            "EXISTS when this constraint is active (i.e. the constrained path is "
            "still achievable). Same format as solve.py --constraint."
        ),
    )
    parser.add_argument(
        "--forbid-constraint", action="append", default=[], metavar="JSON",
        dest="forbid_constraint",
        help=(
            "Constraint JSON (repeatable). Candidate passes only if NO solution "
            "exists when this constraint is active (i.e. the event is required). "
            "Same format as solve.py --constraint."
        ),
    )
    parser.add_argument(
        "--workers", type=int, default=8, metavar="N",
        help="Parallel worker processes (default: 8)",
    )
    parser.add_argument(
        "--cython", action="store_true",
        help="Twinseed only: use the Cython fast A* backend. Requires the "
             "extension in tools/solver/games/twinseed_cython to be built.",
    )
    parser.add_argument(
        "--must-contain-action", action="append", default=[], metavar="ACTION",
        help="Post-solve filter (repeatable): drop candidates whose gold "
             "path does not contain this action (e.g. 'clone').",
    )
    parser.add_argument(
        "--output-dir", metavar="DIR",
        help="Directory to save passing level JSONs",
    )
    parser.add_argument(
        "--seed", type=int, default=42, metavar="N",
        help="Random seed for reproducibility (default: 42)",
    )
    args = parser.parse_args()

    if args.attempts == 0:
        args.attempts = max(50, 20 * args.candidates)

    _run(args)


if __name__ == "__main__":
    main()
