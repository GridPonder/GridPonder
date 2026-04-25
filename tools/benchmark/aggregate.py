#!/usr/bin/env python3
"""Aggregate benchmark JSONL results into leaderboard.json.

Reads all .jsonl files under results/run/*/, computes per-model and
per-pack statistics, and writes leaderboard.json (consumed by the
Astro website at build time).

Results are grouped by (model_id, inference_mode) so that different
modes produce separate leaderboard entries. Use --mode to restrict
output to one mode (default: single).

Usage:
  python aggregate.py
  python aggregate.py --mode flex-n
  python aggregate.py --results-dir /path/to/run/
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
RESULTS_DIR = SCRIPT_DIR / "results" / "run"
LEADERBOARD_FILE = SCRIPT_DIR / "leaderboard.json"
MODELS_FILE = SCRIPT_DIR / "models.yaml"
PACKS_DIR = SCRIPT_DIR.parent.parent / "packs"

# Lazy import: only used when building level_results.
import sys
sys.path.insert(0, str(SCRIPT_DIR.parent.parent))
from engines.python.level_metrics import playable_cell_count

_level_metrics_cache: dict[tuple[str, str], dict[str, Any]] = {}


def level_metrics(pack_id: str, level_id: str) -> dict[str, Any]:
    """Return derived metrics for a level (cached). Empty dict if unreadable."""
    key = (pack_id, level_id)
    if key in _level_metrics_cache:
        return _level_metrics_cache[key]
    path = PACKS_DIR / pack_id / "levels" / f"{level_id}.json"
    metrics: dict[str, Any] = {}
    if path.exists():
        try:
            d = json.loads(path.read_text())
            metrics["playable_cells"] = playable_cell_count(d)
        except (json.JSONDecodeError, OSError):
            pass
    _level_metrics_cache[key] = metrics
    return metrics


def load_results(results_dir: Path, mode_filter: str | None = None) -> dict[str, dict]:
    """Load all JSONL files. Returns {key: {meta, levels: [...]}}.

    Key is "{model_id}|{inference_mode}" so different modes stay separate.
    mode_filter restricts to a single inference mode if given.
    Missing inference_mode is treated as "single" for backwards compatibility.
    """
    data: dict[str, dict] = {}

    for jsonl_file in sorted(results_dir.glob("**/*.jsonl")):
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

        file_mode = meta.get("inference_mode", "single")
        if mode_filter is not None and file_mode != mode_filter:
            continue

        model_id = meta["model_id"]
        file_anon = meta.get("anon", False)
        key = f"{model_id}|{file_mode}|{'anon' if file_anon else 'named'}"
        if key not in data:
            data[key] = {
                "meta": meta,
                "levels": [],
                "inference_mode": file_mode,
                "anon": file_anon,
            }
        data[key]["levels"].extend(levels)

    return data


def compute_stats(levels: list[dict]) -> dict[str, Any]:
    """Compute aggregate stats for a list of level results."""
    valid = [l for l in levels if "error" not in l]
    if not valid:
        return {
            "success_rate": 0.0,
            "avg_efficiency": None,
            "avg_efficiency_flex": None,
            "avg_aggregate_score": 0.0,
            "p50_latency_ms": None,
            "avg_cost_usd": None,
            "levels_run": 0,
        }

    successes = [l for l in valid if l.get("success")]
    efficiencies = [l["efficiency"] for l in successes if l.get("efficiency") is not None]
    flex_efficiencies = [l["efficiency_flex"] for l in successes if l.get("efficiency_flex") is not None]
    latencies = [l["latency_ms"]["median"] for l in valid if l.get("latency_ms")]
    costs = [l["cost_usd"] for l in valid if l.get("cost_usd") is not None]

    # Aggregate score: 0.5 * success(0/1) + 0.5 * best_efficiency.
    # Computed per-level so failed levels contribute 0 (not excluded).
    agg_scores = []
    for l in valid:
        eff = l.get("efficiency_flex") or l.get("efficiency") or 0.0
        agg_scores.append(0.5 * float(l.get("success", False)) + 0.5 * eff)

    return {
        "levels_run": len(valid),
        "success_rate": len(successes) / len(valid),
        "avg_efficiency": statistics.mean(efficiencies) if efficiencies else None,
        "avg_efficiency_flex": statistics.mean(flex_efficiencies) if flex_efficiencies else None,
        "avg_aggregate_score": statistics.mean(agg_scores) if agg_scores else 0.0,
        "p50_latency_ms": statistics.median(latencies) if latencies else None,
        "avg_cost_usd": statistics.mean(costs) if costs else None,
    }


def build_leaderboard(data: dict[str, dict]) -> dict:
    models_out: list[dict] = []
    # Compact columnar per-level rows (used by the analytic charts).
    level_cols = ["model_id", "pack_id", "level_id", "gold_path_length", "success", "inference_mode", "anon", "playable_cells"]
    level_rows: list[list[Any]] = []

    for key, entry in data.items():
        meta = entry["meta"]
        levels = entry["levels"]
        inference_mode = entry["inference_mode"]
        anon = bool(entry.get("anon", False))

        by_pack: dict[str, list[dict]] = defaultdict(list)
        for l in levels:
            by_pack[l["pack_id"]].append(l)

        pack_stats = {
            pack_id: compute_stats(pack_levels)
            for pack_id, pack_levels in by_pack.items()
        }

        overall = compute_stats(levels)

        models_out.append({
            "id": meta["model_id"],
            "display_name": meta.get("display_name", meta["model_id"]),
            "local": meta.get("local", True),
            "reasoning": meta.get("reasoning", False),
            "inference_mode": inference_mode,
            "anon": anon,
            "overall": overall,
            "by_pack": pack_stats,
        })

        for l in levels:
            if "error" in l or l.get("gold_path_length") is None:
                continue
            metrics = level_metrics(l["pack_id"], l["level_id"])
            level_rows.append([
                meta["model_id"],
                l["pack_id"],
                l["level_id"],
                int(l["gold_path_length"]),
                bool(l.get("success", False)),
                inference_mode,
                anon,
                metrics.get("playable_cells"),
            ])

    # Sort by aggregate score descending, then success rate, then efficiency.
    def sort_key(m: dict) -> tuple:
        overall = m["overall"]
        return (
            -(overall.get("avg_aggregate_score") or 0.0),
            -(overall.get("success_rate") or 0.0),
            -(overall.get("avg_efficiency") or 0.0),
        )

    models_out.sort(key=sort_key)

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "models": models_out,
        "level_results_columns": level_cols,
        "level_results": level_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate benchmark results → leaderboard.json")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=RESULTS_DIR,
        help=f"Directory containing run subdirectories (default: {RESULTS_DIR})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=LEADERBOARD_FILE,
        help=f"Output file (default: {LEADERBOARD_FILE})",
    )
    parser.add_argument(
        "--mode",
        default=None,
        help="Filter to a single inference mode (default: include all modes)",
    )
    args = parser.parse_args()

    if not args.results_dir.exists():
        print(f"No results directory found at {args.results_dir}. Nothing to aggregate.")
        return

    data = load_results(args.results_dir, mode_filter=args.mode)
    if not data:
        print("No valid JSONL results found.")
        return

    leaderboard = build_leaderboard(data)
    args.output.write_text(json.dumps(leaderboard, indent=2) + "\n")

    total_levels = sum(len(e["levels"]) for e in data.values())
    print(f"Aggregated {total_levels} level result(s) across {len(data)} model/mode variant(s).")
    print(f"Written: {args.output}")


if __name__ == "__main__":
    main()
