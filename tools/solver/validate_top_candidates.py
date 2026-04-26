#!/usr/bin/env python3
"""
validate_top_candidates.py — re-validate the top-N pass_ candidates with the
fixed admissible heuristic. For each candidate, runs A* twice (with clone and
without clone) and reports the *true* optimal gold path lengths plus a new
interaction score derived from the optimal path's event trace.

Why: when the heuristic was inadmissible (returned ∞/1e300 for states with
n_baskets > n_plots) A* found a solution but not the optimum. Stored gold
paths and interaction scores from such runs cannot be trusted.

Usage:
    python3 tools/solver/validate_top_candidates.py \\
        --input-dir /Users/jlehmann/Programmierung/gridponder/platform/tmp/tw_ice_variants/ \\
        --top-n 80 \\
        --report-top 20 \\
        --workers 8 \\
        --timeout 300
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SOLVER_DIR = str(Path(__file__).resolve().parent)
if SOLVER_DIR not in sys.path:
    sys.path.insert(0, SOLVER_DIR)


# ---------------------------------------------------------------------------
# Old-score parsing (from saved candidate JSON via path replay)
# ---------------------------------------------------------------------------

_IRR_EVENTS = {"object_removed", "bridge_created", "ground_transformed"}
_REV_EVENTS = {"object_pushed", "inventory_changed"}


def _score_path(level_json: dict, path: List[str]) -> int:
    """Replay path through the (event-emitting) Python engine for scoring.

    Uses games.twinseed (slow but emits events). The fast/Cython engines do
    not produce event traces, so they cannot be used for interaction scoring.
    """
    import games.twinseed as tw
    state, info = tw.load(level_json)
    score = 0
    for action in path:
        state, _won, evts = tw.apply(state, action, info)
        for e in evts:
            t = e.get("type", "")
            if t in _IRR_EVENTS:
                score += 3
            elif t in _REV_EVENTS:
                score += 2
            elif t == "avatar_entered":
                score += 1
    score += 3 * sum(1 for a in path if a == "clone")
    return score


def _path_from_gold(level_json: dict) -> Optional[List[str]]:
    """Convert stored goldPath (DSL format) to a flat action list."""
    sol = level_json.get("solution", {}) or {}
    gp = sol.get("goldPath") or []
    actions: List[str] = []
    for entry in gp:
        if isinstance(entry, str):
            # Shorthand: "right", "down", "clone", ...
            if entry in ("up", "down", "left", "right"):
                actions.append(f"move_{entry}")
            else:
                actions.append(entry)
        elif isinstance(entry, dict):
            kind = entry.get("action")
            if kind == "move":
                actions.append(f"move_{entry.get('direction')}")
            elif kind:
                actions.append(kind)
    return actions or None


# ---------------------------------------------------------------------------
# Worker: run A* twice for a single candidate
# ---------------------------------------------------------------------------

def _evaluate_candidate(args: Tuple[str, float, int]) -> Dict:
    file_path, timeout_s, max_depth = args
    if SOLVER_DIR not in sys.path:
        sys.path.insert(0, SOLVER_DIR)

    import games.twinseed_cy as cy
    from search.astar import astar

    fname = Path(file_path).name
    out: Dict = {"file": fname}

    with open(file_path) as f:
        level = json.load(f)

    initial, info = cy.load(level)

    # --- A* with clone -----------------------------------------------------
    t0 = time.monotonic()
    sol_with = astar(initial, info, cy, timeout_s, [], max_depth=max_depth)
    out["with_clone_secs"] = round(time.monotonic() - t0, 1)
    out["with_clone_len"] = len(sol_with.path) if sol_with.path else None
    out["with_clone_path"] = sol_with.path
    out["with_clone_timeout"] = sol_with.timed_out
    out["with_clone_proven_unsolvable"] = (
        not sol_with.path and not sol_with.timed_out and sol_with.is_optimal
    )

    # --- A* without clone -------------------------------------------------
    orig_actions = list(cy.ACTIONS)
    cy.ACTIONS = [a for a in orig_actions if a != "clone"]
    try:
        t0 = time.monotonic()
        sol_no = astar(initial, info, cy, timeout_s, [], max_depth=max_depth)
        out["no_clone_secs"] = round(time.monotonic() - t0, 1)
    finally:
        cy.ACTIONS = orig_actions
    out["no_clone_len"] = len(sol_no.path) if sol_no.path else None
    out["no_clone_timeout"] = sol_no.timed_out
    out["no_clone_proven_unsolvable"] = (
        not sol_no.path and not sol_no.timed_out and sol_no.is_optimal
    )

    # --- New score from with-clone optimal path ---------------------------
    if sol_with.path:
        try:
            out["new_score"] = _score_path(level, sol_with.path)
        except Exception as e:
            out["new_score"] = None
            out["score_error"] = str(e)
    else:
        out["new_score"] = None

    # Clone count along optimal with-clone path
    if sol_with.path:
        out["clone_count"] = sum(1 for a in sol_with.path if a == "clone")
    else:
        out["clone_count"] = None

    return out


# ---------------------------------------------------------------------------
# Verdict formatting
# ---------------------------------------------------------------------------

def _verdict(r: Dict) -> str:
    """Short verdict string for the report."""
    wl = r.get("with_clone_len")
    nl = r.get("no_clone_len")
    if wl is None:
        if r.get("with_clone_timeout"):
            return "with-clone t/o"
        return "UNSOLVABLE even with clone"
    if r.get("no_clone_proven_unsolvable"):
        return f"clone REQUIRED (no-clone ∞)"
    if r.get("no_clone_timeout"):
        return f"clone REQUIRED (no-clone t/o)"
    if nl is None:
        return f"clone REQUIRED (?)"
    delta = nl - wl
    if delta == 0:
        return f"clone OPTIONAL (=0)"
    return f"clone OPTIONAL (+{delta})"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input-dir", required=True, help="Dir containing _pass_*.json files")
    ap.add_argument("--top-n", type=int, default=80,
                    help="How many candidates to validate (selected by old score)")
    ap.add_argument("--report-top", type=int, default=20,
                    help="How many to show in the final ranked table")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=300.0,
                    help="Per-search A* timeout (seconds)")
    ap.add_argument("--max-depth", type=int, default=80)
    ap.add_argument("--output-json", default=None,
                    help="Optional: write full results array to this path")
    args = ap.parse_args()

    in_dir = Path(args.input_dir).resolve()
    files = sorted(in_dir.glob("*_pass_*.json"))
    if not files:
        print(f"No _pass_*.json files in {in_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {len(files)} candidates and computing old scores…", flush=True)

    # Compute old score for each candidate by replaying its stored goldPath.
    scored: List[Tuple[int, str]] = []
    for f in files:
        try:
            with open(f) as fp:
                level = json.load(fp)
            path = _path_from_gold(level) or []
            old_score = _score_path(level, path) if path else 0
            scored.append((old_score, str(f)))
        except Exception as e:
            print(f"  ! {f.name}: {e}", file=sys.stderr)

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[: args.top_n]
    print(f"Selected top {len(selected)} by old score "
          f"(range {selected[-1][0]}…{selected[0][0]})", flush=True)
    print(f"Re-validating with fixed heuristic "
          f"(timeout={args.timeout}s, workers={args.workers}, max_depth={args.max_depth})…",
          flush=True)
    print()

    # Submit work in score order so highest-score finishes inform progress first.
    tasks = [(p, args.timeout, args.max_depth) for _old, p in selected]

    results: List[Dict] = []
    file_to_old: Dict[str, int] = {Path(p).name: s for s, p in selected}

    t_start = time.monotonic()
    completed = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_evaluate_candidate, t): t[0] for t in tasks}
        for fut in as_completed(futures):
            try:
                r = fut.result()
            except Exception as e:
                r = {"file": Path(futures[fut]).name, "error": str(e)}
            r["old_score"] = file_to_old.get(r.get("file", ""), None)
            results.append(r)
            completed += 1

            elapsed = time.monotonic() - t_start
            ws = (f"{r.get('with_clone_len')}" if r.get('with_clone_len') is not None
                  else ('t/o' if r.get('with_clone_timeout') else '∞'))
            ns = (f"{r.get('no_clone_len')}" if r.get('no_clone_len') is not None
                  else ('t/o' if r.get('no_clone_timeout') else '∞'))
            print(f"  [{completed:3d}/{len(tasks)} | {elapsed:6.0f}s] "
                  f"{r.get('file','?'):40s}  old={r.get('old_score'):>4}  "
                  f"new={(str(r.get('new_score')) if r.get('new_score') is not None else '-'):>4}  "
                  f"opt={ws:>4}  no-clone={ns:>4}  | {_verdict(r)}",
                  flush=True)

    # Final ranked table by NEW score
    def _sort_key(r):
        ns = r.get("new_score")
        return (-(ns if ns is not None else -1),
                r.get("with_clone_len") or 999)
    results.sort(key=_sort_key)

    print()
    print(f"=== Top {args.report_top} by NEW (true-optimal) score ===")
    print()
    hdr = (f"  {'#':>3}  {'newScore':>8}  {'oldScore':>8}  {'optMov':>6}  "
           f"{'noClone':>7}  {'clones':>6}  {'verdict':<30}  file")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for i, r in enumerate(results[: args.report_top], 1):
        ns = r.get("new_score")
        os_ = r.get("old_score")
        wl = r.get("with_clone_len")
        nl = r.get("no_clone_len")
        cc = r.get("clone_count")
        no_clone_str = (
            "∞" if r.get("no_clone_proven_unsolvable")
            else "t/o" if r.get("no_clone_timeout")
            else (str(nl) if nl is not None else "-")
        )
        print(f"  {i:>3}  {(ns if ns is not None else '-'):>8}  "
              f"{(os_ if os_ is not None else '-'):>8}  "
              f"{(wl if wl is not None else '-'):>6}  "
              f"{no_clone_str:>7}  {(cc if cc is not None else '-'):>6}  "
              f"{_verdict(r):<30}  {r.get('file','?')}")

    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(results, f, indent=2)
        print()
        print(f"Wrote full results to {args.output_json}")


if __name__ == "__main__":
    main()
