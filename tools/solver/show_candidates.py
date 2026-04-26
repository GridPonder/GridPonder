#!/usr/bin/env python3
"""
show_candidates.py — list passing candidates written by mutate_and_test.py.

Reads all _pass_NNNN.json files from an output directory and prints a ranked
summary table, sorted by interaction score descending.  Safe to run while
mutate_and_test.py is still evaluating candidates.

Usage:
    python3 tools/solver/show_candidates.py <output-dir> [--top N]
"""
import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="List passing candidates from a mutate_and_test run.")
    parser.add_argument("output_dir", help="Directory containing _pass_NNNN.json files")
    parser.add_argument("--top", type=int, default=0, metavar="N",
                        help="Show only top N by score (default: all)")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    files = sorted(out_dir.glob("*_pass_*.json"))
    if not files:
        print(f"No _pass_ files found in {out_dir}")
        return

    rows = []
    for f in files:
        try:
            d = json.load(open(f))
            m = d.get("metadata", {})
            sol = d.get("solution", {})
            gold = sol.get("goldPath", [])
            clone_count = sum(1 for a in gold if a == "clone")
            rows.append({
                "file": f.name,
                "score": m.get("interaction_score") or 0,
                "moves": m.get("solution_length") or len(gold),
                "mc_bits": m.get("mc_bits"),
                "clone_uses": clone_count,
                "pass_n": m.get("pass_n", 0),
            })
        except Exception as e:
            print(f"  Warning: could not read {f.name}: {e}")

    rows.sort(key=lambda r: (-r["score"], -(r["mc_bits"] or 0.0), r["moves"]))
    if args.top:
        rows = rows[:args.top]

    print(f"Candidates in {out_dir}  ({len(files)} total)")
    print()
    header = f"  {'#':>4}  {'score':>6}  {'moves':>5}  {'mc_bits':>8}  {'clones':>6}  file"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for rank, r in enumerate(rows, 1):
        bits_str = f"{r['mc_bits']:.1f}" if r["mc_bits"] else "—"
        print(f"  {rank:>4}  {r['score']:>6}  {r['moves']:>5}  {bits_str:>8}"
              f"  {r['clone_uses']:>6}  {r['file']}")
    print()


if __name__ == "__main__":
    main()
