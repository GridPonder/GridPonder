#!/usr/bin/env python3
"""
Benchmark: original twinseed engine vs Python fast solver vs Cython fast solver.

Measures states/second explored by A* on tw_004_seed for a fixed duration.

Usage:
    python benchmark_tw.py [path/to/level.json] [--duration N]

By default uses packs/twinseed/levels/tw_004_seed.json, duration=10s per backend.
"""

from __future__ import annotations

import argparse
import heapq
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import games.twinseed as tw
import games.twinseed_fast as tw_fast
import engine_adapter as ea


# ---------------------------------------------------------------------------
# Shared A* inner loop (no timeout, fixed duration, returns states/sec)
# ---------------------------------------------------------------------------

def _astar_bench(initial, info, apply_fn, heuristic_fn, actions, duration_s):
    """Run A* for duration_s seconds; return (states_explored, elapsed)."""
    def h(state):
        v = heuristic_fn(state, info)
        return v

    start = time.monotonic()
    visited = {initial: 0}
    h0 = h(initial)
    counter = 0
    heap = [(h0, 0, counter, initial)]
    states = 0

    while heap:
        if time.monotonic() - start > duration_s:
            break
        f, g, _, state = heapq.heappop(heap)
        if visited[state] < g:
            continue
        states += 1
        for action in actions:
            new_state, won, _ = apply_fn(state, action, info)
            new_g = g + 1
            prev = visited.get(new_state)
            if prev is not None and prev <= new_g:
                continue
            new_h = h(new_state)
            if new_h == float("inf"):
                continue
            visited[new_state] = new_g
            counter += 1
            heapq.heappush(heap, (new_g + new_h, new_g, counter, new_state))

    elapsed = time.monotonic() - start
    return states, elapsed


# ---------------------------------------------------------------------------
# Correctness check: replay gold path
# ---------------------------------------------------------------------------

def _verify_fast(level_json, level_path):
    """Verify twinseed_fast produces same results as original engine on gold path."""
    gold = ea.gold_path_actions(level_json)
    if not gold:
        print("  (no gold path to verify)")
        return True

    initial_orig, info_orig = tw.load(level_json)
    initial_fast, info_fast = tw_fast.load(level_json)

    ok = True
    state_orig = initial_orig
    state_fast = initial_fast
    for i, action in enumerate(gold):
        ns_orig, won_orig, _ = tw.apply(state_orig, action, info_orig)
        ns_fast, won_fast, _ = tw_fast.apply(state_fast, action, info_fast)
        if won_orig != won_fast:
            print(f"  ✗ Step {i+1} '{action}': won_orig={won_orig} won_fast={won_fast}")
            ok = False
        state_orig = ns_orig
        state_fast = ns_fast

    if ok:
        print(f"  ✓ Gold path verified ({len(gold)} steps, ends won={won_orig})")
    return ok


# ---------------------------------------------------------------------------
# Cython wrapper (flat neighbor list)
# ---------------------------------------------------------------------------

def _make_cy_fns(info_fast):
    """Return (apply_fn, heuristic_fn) using Cython. None if not available."""
    from games.twinseed_cython import apply_cy, heuristic_and_prune_cy, CYTHON_AVAILABLE
    if not CYTHON_AVAILABLE:
        return None, None

    neighbors_flat = list(info_fast.neighbors_flat)
    cells_len  = info_fast.cells_len
    cost_table = info_fast.cost_table
    width      = info_fast.width

    def cy_apply(state, action, info):
        action_idx = tw_fast._DIR_OF.get(action, 4)
        ns, won = apply_cy(state, action_idx, neighbors_flat, cells_len)
        return ns, won, []

    def cy_h(state, info):
        h, prune = heuristic_and_prune_cy(state, cost_table, cells_len, width)
        return h if not prune else float("inf")

    return cy_apply, cy_h


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Benchmark twinseed solver backends.")
    parser.add_argument(
        "level", nargs="?",
        default=str(Path(__file__).parent.parent.parent /
                    "packs/twinseed/levels/tw_004_seed.json"),
        help="Path to level JSON (default: tw_004_seed)",
    )
    parser.add_argument("--duration", type=float, default=10.0,
                        help="Seconds per backend (default: 10)")
    parser.add_argument("--skip-verify", action="store_true",
                        help="Skip gold-path correctness check")
    args = parser.parse_args()

    level_path = Path(args.level)
    with open(level_path) as f:
        level_json = json.load(f)

    level_id = level_json.get("id", level_path.stem)
    print(f"Benchmark: {level_id}  ({args.duration:.0f}s per backend)")
    print()

    # --- Verify correctness ---
    if not args.skip_verify:
        print("Verifying twinseed_fast against original engine …")
        ok = _verify_fast(level_json, level_path)
        print()
        if not ok:
            print("ERROR: fast solver produces different results — benchmark aborted.")
            sys.exit(1)

    results = {}

    # --- Backend 1: Original engine ---
    print(f"[1/3] Original engine (engine_adapter + Python TurnEngine) …")
    initial_orig, info_orig = tw.load(level_json)

    class _mod_orig:
        ACTIONS = tw.ACTIONS
        apply = staticmethod(tw.apply)

    states_orig, elapsed_orig = _astar_bench(
        initial_orig, info_orig,
        tw.apply, tw.heuristic, tw.ACTIONS, args.duration
    )
    sps_orig = states_orig / elapsed_orig
    results["original"] = (states_orig, elapsed_orig, sps_orig)
    print(f"    {states_orig:,} states  in {elapsed_orig:.2f}s  →  {sps_orig:,.0f} states/sec")
    print()

    # --- Backend 2: Python fast solver ---
    print(f"[2/3] Python fast solver (bytes state, no engine) …")
    initial_fast, info_fast = tw_fast.load(level_json)
    states_fast, elapsed_fast = _astar_bench(
        initial_fast, info_fast,
        tw_fast.apply, tw_fast.heuristic, tw_fast.ACTIONS, args.duration
    )
    sps_fast = states_fast / elapsed_fast
    results["python_fast"] = (states_fast, elapsed_fast, sps_fast)
    print(f"    {states_fast:,} states  in {elapsed_fast:.2f}s  →  {sps_fast:,.0f} states/sec")
    speedup_py = sps_fast / sps_orig
    print(f"    Speedup vs original: {speedup_py:.1f}×")
    print()

    # --- Backend 3: Cython (apply only, Python heuristic) ---
    print(f"[3/4] Cython apply + Python heuristic …")
    try:
        from games.twinseed_cython import CYTHON_AVAILABLE
        if not CYTHON_AVAILABLE:
            raise ImportError("not built")
        cy_apply, cy_h = _make_cy_fns(info_fast)
        if cy_apply is None:
            raise ImportError("apply_cy returned None")
        states_cy, elapsed_cy = _astar_bench(
            initial_fast, info_fast,
            cy_apply, tw_fast.heuristic, tw_fast.ACTIONS, args.duration
        )
        sps_cy = states_cy / elapsed_cy
        results["cython_apply"] = (states_cy, elapsed_cy, sps_cy)
        print(f"    {states_cy:,} states  in {elapsed_cy:.2f}s  →  {sps_cy:,.0f} states/sec")
        print(f"    Speedup vs original: {sps_cy/sps_orig:.1f}×  (vs Python fast: {sps_cy/sps_fast:.1f}×)")
    except ImportError as e:
        print(f"    Cython not available ({e}).")
        print(f"    Build with:")
        print(f"      cd tools/solver/games/twinseed_cython && python setup.py build_ext --inplace")
    print()

    # --- Backend 4: Cython (apply + heuristic/prune) ---
    print(f"[4/4] Cython apply + Cython heuristic/prune …")
    try:
        from games.twinseed_cython import CYTHON_AVAILABLE
        if not CYTHON_AVAILABLE:
            raise ImportError("not built")
        if cy_h is None:
            raise ImportError("heuristic_and_prune_cy not available")
        states_cy2, elapsed_cy2 = _astar_bench(
            initial_fast, info_fast,
            cy_apply, cy_h, tw_fast.ACTIONS, args.duration
        )
        sps_cy2 = states_cy2 / elapsed_cy2
        results["cython_full"] = (states_cy2, elapsed_cy2, sps_cy2)
        print(f"    {states_cy2:,} states  in {elapsed_cy2:.2f}s  →  {sps_cy2:,.0f} states/sec")
        print(f"    Speedup vs original: {sps_cy2/sps_orig:.1f}×  (vs Python fast: {sps_cy2/sps_fast:.1f}×)")
    except (ImportError, NameError) as e:
        print(f"    Cython not available ({e}).")
    print()

    # --- Summary ---
    print("=" * 50)
    print("Summary")
    print("=" * 50)
    for name, (states, elapsed, sps) in results.items():
        print(f"  {name:15s}  {sps:>12,.0f} states/sec")
    if "original" in results and "python_fast" in results:
        print(f"\n  Python fast speedup:       {results['python_fast'][2] / results['original'][2]:.1f}×")
    if "original" in results and "cython_apply" in results:
        print(f"  Cython apply speedup:      {results['cython_apply'][2] / results['original'][2]:.1f}×")
    if "original" in results and "cython_full" in results:
        print(f"  Cython full speedup:       {results['cython_full'][2] / results['original'][2]:.1f}×")


if __name__ == "__main__":
    main()
