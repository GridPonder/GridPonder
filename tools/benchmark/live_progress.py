#!/usr/bin/env python3
"""Atomic live-progress snapshots for benchmark work items."""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROGRESS_SCHEMA_VERSION = 1


def _safe_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "unknown"


def progress_path(
    results_dir: Path,
    output_key: str,
    pack_id: str,
    level_id: str,
) -> Path:
    filename = f"{_safe_component(pack_id)}__{_safe_component(level_id)}.json"
    return results_dir / "progress" / _safe_component(output_key) / filename


def write_progress_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    """Atomically replace one work item's latest progress snapshot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": PROGRESS_SCHEMA_VERSION,
        **snapshot,
    }
    tmp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def load_progress_snapshots(results_dir: Path) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for path in sorted((results_dir / "progress").glob("*/*.json")):
        try:
            snapshot = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        snapshot["_path"] = str(path)
        snapshots.append(snapshot)
    return snapshots


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def estimate_to_limit_seconds(
    snapshot: dict[str, Any],
    *,
    now: datetime | None = None,
) -> float | None:
    """Project remaining wall time at the observed action throughput."""
    actions = int(snapshot.get("actions_total") or 0)
    action_limit = int(snapshot.get("action_limit") or 0)
    if actions <= 0 or action_limit <= actions:
        return 0.0 if action_limit and action_limit <= actions else None

    started_at = parse_timestamp(snapshot.get("started_at"))
    if started_at is None:
        return None
    current = now or datetime.now(timezone.utc)
    elapsed_seconds = max(0.0, (current - started_at).total_seconds())
    if elapsed_seconds <= 0:
        return None

    actions_per_second = actions / elapsed_seconds
    return (action_limit - actions) / actions_per_second


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    seconds = max(0, round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"
