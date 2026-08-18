#!/usr/bin/env python3
"""Show live benchmark action counters and action-limit ETAs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_progress import (
    estimate_to_limit_seconds,
    format_duration,
    load_progress_snapshots,
    parse_timestamp,
)


def _completed_keys(results_dir: Path) -> set[tuple[str, str, str]]:
    completed: set[tuple[str, str, str]] = set()
    for path in results_dir.glob("*.jsonl"):
        output_key = path.stem
        with path.open() as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") != "level" or record.get("error"):
                    continue
                completed.add(
                    (output_key, record.get("pack_id", ""), record.get("level_id", ""))
                )
    return completed


def summarize_live(
    results_dir: Path,
    *,
    now: datetime | None = None,
    stale_after_seconds: float | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    meta_path = results_dir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
    completed = _completed_keys(results_dir)
    snapshots = load_progress_snapshots(results_dir)
    stale_after = stale_after_seconds
    if stale_after is None:
        stale_after = max(float(meta.get("action_timeout") or 0) + 300.0, 900.0)

    active: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    for snapshot in snapshots:
        key = (
            snapshot.get("output_key", ""),
            snapshot.get("pack_id", ""),
            snapshot.get("level_id", ""),
        )
        if key in completed or snapshot.get("status") == "completed":
            continue

        updated_at = parse_timestamp(snapshot.get("updated_at"))
        update_age = (
            max(0.0, (current - updated_at).total_seconds())
            if updated_at is not None
            else None
        )
        row = {
            **snapshot,
            "update_age_seconds": update_age,
            "eta_to_limit_seconds": estimate_to_limit_seconds(
                snapshot,
                now=current,
            ),
        }
        if (
            snapshot.get("status") == "running"
            and update_age is not None
            and update_age <= stale_after
        ):
            active.append(row)
        else:
            stale.append(row)

    active.sort(
        key=lambda row: (
            row.get("model_id", ""),
            row.get("output_key", ""),
            row.get("pack_id", ""),
            row.get("level_id", ""),
        )
    )
    stale.sort(key=lambda row: row.get("updated_at", ""), reverse=True)

    total = int(meta.get("total_work_items") or 0)
    remaining = max(0, total - len(completed)) if total else None
    tracked_remaining = len(active) + len(stale)
    queued_or_untracked = (
        max(0, remaining - tracked_remaining)
        if remaining is not None
        else None
    )
    active_etas = [
        row["eta_to_limit_seconds"]
        for row in active
        if row["eta_to_limit_seconds"] is not None
    ]
    overall_eta = (
        max(active_etas)
        if active
        and len(active_etas) == len(active)
        and queued_or_untracked == 0
        else None
    )

    return {
        "generated_at": current.isoformat(),
        "completed": len(completed),
        "total": total or None,
        "remaining": remaining,
        "active": active,
        "stale": stale,
        "queued_or_untracked": queued_or_untracked,
        "eta_to_action_limits_seconds": overall_eta,
        "stale_after_seconds": stale_after,
    }


def _print_table(summary: dict[str, Any]) -> None:
    total = summary["total"] or "?"
    print(
        f"Completed: {summary['completed']}/{total}  "
        f"Active: {len(summary['active'])}  "
        f"Queued/untracked: {summary['queued_or_untracked']}"
    )
    if summary["stale"]:
        print(f"Stale snapshots: {len(summary['stale'])}")
    print()
    print(
        f"{'Model/config':44} {'Level':18} {'Actions':>9} {'Calls':>5} "
        f"{'Phase':>18} {'Update':>8} {'ETA limit':>10}"
    )
    print("-" * 122)
    for row in summary["active"]:
        actions = f"{row.get('actions_total', '?')}/{row.get('action_limit', '?')}"
        level = f"{row.get('pack_id', '?')}/{row.get('level_id', '?')}"
        print(
            f"{row.get('output_key', '?')[:44]:44} "
            f"{level[:18]:18} "
            f"{actions:>9} "
            f"{row.get('llm_calls', 0):>5} "
            f"{row.get('phase', '?')[:18]:>18} "
            f"{format_duration(row.get('update_age_seconds')):>8} "
            f"{format_duration(row.get('eta_to_limit_seconds')):>10}"
        )
    print()
    eta = summary["eta_to_action_limits_seconds"]
    if eta is None:
        print("Overall action-limit ETA: unavailable")
    else:
        print(f"Overall action-limit ETA: {format_duration(eta)}")
    print("Action-limit ETA assumes current action throughput and no earlier win.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show live action counters for a benchmark run."
    )
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument(
        "--stale-after",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Mark snapshots stale after this many seconds without an update",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    summary = summarize_live(
        args.results_dir,
        stale_after_seconds=args.stale_after,
    )
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        _print_table(summary)


if __name__ == "__main__":
    main()
