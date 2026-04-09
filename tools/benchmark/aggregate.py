#!/usr/bin/env python3
"""Aggregate benchmark JSONL results into leaderboard.json.

Reads all .jsonl files under results/runs/, computes per-model and
per-pack statistics, and writes leaderboard.json (consumed by the
Astro website at build time).

Usage:
  python aggregate.py
  python aggregate.py --results-dir /path/to/runs/
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).parent.resolve()
RESULTS_DIR = SCRIPT_DIR / "results" / "runs"
LEADERBOARD_FILE = SCRIPT_DIR / "leaderboard.json"
MODELS_FILE = SCRIPT_DIR / "models.yaml"


def load_results(results_dir: Path) -> dict[str, dict]:
    """Load all JSONL files. Returns {full_model_id: {meta, levels: [...]}}.

    If a (model, pack, level) appears multiple times across files (repeated
    runs), all results are kept and averaged.
    """
    data: dict[str, dict] = {}

    for jsonl_file in sorted(results_dir.glob("*.jsonl")):
        meta: dict | None = None
        levels: list[dict] = []

        with open(jsonl_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") == "run_meta":
                    meta = record
                elif record.get("type") == "level":
                    levels.append(record)

        if meta is None or not levels:
            continue

        model_id = meta["model_id"]
        if model_id not in data:
            data[model_id] = {"meta": meta, "levels": []}
        data[model_id]["levels"].extend(levels)

    return data


def compute_stats(levels: list[dict]) -> dict[str, Any]:
    """Compute aggregate stats for a list of level results."""
    valid = [l for l in levels if "error" not in l]
    if not valid:
        return {"success_rate": 0.0, "avg_efficiency": None, "p50_latency_ms": None, "levels_run": 0}

    successes = [l for l in valid if l.get("success")]
    efficiencies = [l["efficiency"] for l in successes if l.get("efficiency") is not None]
    latencies = [l["latency_ms"]["median"] for l in valid if l.get("latency_ms")]

    return {
        "levels_run": len(valid),
        "success_rate": len(successes) / len(valid),
        "avg_efficiency": statistics.mean(efficiencies) if efficiencies else None,
        "p50_latency_ms": statistics.median(latencies) if latencies else None,
    }


def build_leaderboard(data: dict[str, dict]) -> dict:
    models_out: list[dict] = []

    for model_id, entry in data.items():
        meta = entry["meta"]
        levels = entry["levels"]

        # Group levels by pack.
        by_pack: dict[str, list[dict]] = defaultdict(list)
        for l in levels:
            by_pack[l["pack_id"]].append(l)

        pack_stats = {
            pack_id: compute_stats(pack_levels)
            for pack_id, pack_levels in by_pack.items()
        }

        overall = compute_stats(levels)

        models_out.append({
            "id": model_id,
            "display_name": meta.get("display_name", model_id),
            "local": meta.get("local", True),
            "reasoning": meta.get("reasoning", False),
            "overall": overall,
            "by_pack": pack_stats,
        })

    # Sort by overall success rate descending, then by efficiency descending.
    def sort_key(m: dict):
        sr = m["overall"].get("success_rate") or 0.0
        eff = m["overall"].get("avg_efficiency") or 0.0
        return (-sr, -eff)

    models_out.sort(key=sort_key)

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "models": models_out,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate benchmark results → leaderboard.json")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=RESULTS_DIR,
        help=f"Directory containing .jsonl run files (default: {RESULTS_DIR})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=LEADERBOARD_FILE,
        help=f"Output file (default: {LEADERBOARD_FILE})",
    )
    args = parser.parse_args()

    if not args.results_dir.exists():
        print(f"No results directory found at {args.results_dir}. Nothing to aggregate.")
        return

    data = load_results(args.results_dir)
    if not data:
        print("No valid JSONL results found.")
        return

    leaderboard = build_leaderboard(data)
    args.output.write_text(json.dumps(leaderboard, indent=2) + "\n")

    total_levels = sum(len(e["levels"]) for e in data.values())
    print(f"Aggregated {total_levels} level result(s) across {len(data)} model variant(s).")
    print(f"Written: {args.output}")


if __name__ == "__main__":
    main()
