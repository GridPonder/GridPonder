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
        file_input = meta.get("input_mode", "text")
        key = f"{model_id}|{file_mode}|{'anon' if file_anon else 'named'}|{file_input}"
        if key not in data:
            data[key] = {
                "meta": meta,
                "levels": [],
                "inference_mode": file_mode,
                "anon": file_anon,
                "input_mode": file_input,
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
            "behaviour": _empty_behaviour(),
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
        "behaviour": _compute_behaviour(valid),
    }


# ── Game Analysis (behavioural metrics) ──────────────────────────────────

def _empty_behaviour() -> dict[str, Any]:
    return {
        "recovery_rate": None,
        "rejection_rate": None,
        "mean_resets_per_level": None,
        "voluntary_giveup_rate": None,
        "memory_use_rate": None,
        "median_memory_chars": None,
        "repeated_state_rate": None,
    }


def _extract_memory_from_response(response_text: str) -> str | None:
    """Best-effort extraction of the model's memory string from a raw response."""
    if not response_text:
        return None
    # Find the first balanced JSON object and look for a "memory" key.
    s = response_text
    start = s.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            c = s[i]
            if esc:
                esc = False
                continue
            if c == "\\":
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(s[start:i + 1])
                        if isinstance(obj, dict) and "memory" in obj:
                            mem = obj["memory"]
                            return mem if isinstance(mem, str) else None
                    except json.JSONDecodeError:
                        pass
                    break
        start = s.find("{", start + 1)
    return None


def _compute_behaviour(valid_levels: list[dict]) -> dict[str, Any]:
    # Recovery: P(attempt N+1 succeeds | attempt N failed).
    failures_with_followup = 0
    recoveries = 0
    for l in valid_levels:
        attempts = l.get("attempts", 1) or 1
        if attempts > 1:
            failures_with_followup += attempts - 1
            if l.get("success"):
                recoveries += 1

    # Rejection rate.
    rej_total = sum(int(l.get("rejections") or 0) for l in valid_levels)
    call_total = sum(int(l.get("llm_calls") or 0) for l in valid_levels)

    # Reset rate (mean resets per level — already correct per old data).
    resets_per_level = [int(l.get("resets") or 0) for l in valid_levels]

    # Voluntary give-up rate: only available if levels have voluntary_resets.
    vr_levels = [l for l in valid_levels if "voluntary_resets" in l]
    vol_rate = (
        sum(1 for l in vr_levels if int(l.get("voluntary_resets") or 0) > 0) / len(vr_levels)
        if vr_levels else None
    )

    # Repeated states: only available if levels have repeated_states.
    rs_levels = [l for l in valid_levels if l.get("repeated_states") is not None]
    rep_rate = None
    if rs_levels:
        rs_total = sum(int(l.get("repeated_states") or 0) for l in rs_levels)
        actions_total = sum(int(l.get("actions_total") or 0) for l in rs_levels)
        rep_rate = rs_total / actions_total if actions_total > 0 else None

    # Memory write rate: fraction of LLM calls in which the model wrote a
    # non-empty memory string. For won levels the final winning call is
    # discarded — its memory update is redundant since the game is over.
    mem_writes = 0
    mem_calls = 0
    mem_lengths: list[int] = []
    for l in valid_levels:
        log = l.get("llm_log") or []
        relevant = log[:-1] if l.get("success") and log else log
        for entry in relevant:
            mem_calls += 1
            mem = _extract_memory_from_response(entry.get("response", ""))
            if mem:
                mem_writes += 1
                mem_lengths.append(len(mem))

    return {
        "recovery_rate": (recoveries / failures_with_followup) if failures_with_followup else None,
        "rejection_rate": (rej_total / call_total) if call_total else None,
        "mean_resets_per_level": (sum(resets_per_level) / len(resets_per_level)) if resets_per_level else None,
        "voluntary_giveup_rate": vol_rate,
        "memory_use_rate": (mem_writes / mem_calls) if mem_calls else None,
        "median_memory_chars": int(statistics.median(mem_lengths)) if mem_lengths else None,
        "repeated_state_rate": rep_rate,
    }


def build_leaderboard(data: dict[str, dict]) -> dict:
    models_out: list[dict] = []
    # Compact columnar per-level rows (used by the analytic charts).
    level_cols = ["model_id", "pack_id", "level_id", "gold_path_length", "success", "inference_mode", "anon", "playable_cells", "input_mode"]
    level_rows: list[list[Any]] = []

    for key, entry in data.items():
        meta = entry["meta"]
        levels = entry["levels"]
        inference_mode = entry["inference_mode"]
        anon = bool(entry.get("anon", False))
        input_mode = entry.get("input_mode", "text")

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
            "input_mode": input_mode,
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
                input_mode,
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
