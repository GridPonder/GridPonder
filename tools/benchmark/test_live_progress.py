from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import bench
from live_progress import (
    estimate_to_limit_seconds,
    load_progress_snapshots,
    progress_path,
    write_progress_snapshot,
)
from live_status import summarize_live


def test_atomic_snapshot_and_eta() -> None:
    now = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
    snapshot = {
        "status": "running",
        "phase": "waiting_for_model",
        "output_key": "frontier_single",
        "model_id": "frontier",
        "pack_id": "pack",
        "level_id": "one",
        "started_at": (now - timedelta(hours=1)).isoformat(),
        "updated_at": now.isoformat(),
        "actions_total": 30,
        "action_limit": 120,
        "llm_calls": 30,
    }

    with TemporaryDirectory() as raw_dir:
        results_dir = Path(raw_dir)
        path = progress_path(results_dir, "frontier_single", "pack", "one")
        write_progress_snapshot(path, snapshot)
        loaded = load_progress_snapshots(results_dir)

    assert len(loaded) == 1
    assert loaded[0]["actions_total"] == 30
    assert estimate_to_limit_seconds(snapshot, now=now) == 3 * 3600


def test_live_summary_ignores_completed_snapshot() -> None:
    now = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
    with TemporaryDirectory() as raw_dir:
        results_dir = Path(raw_dir)
        (results_dir / "meta.json").write_text(json.dumps({
            "total_work_items": 2,
            "action_timeout": 120,
        }))
        (results_dir / "frontier_single.jsonl").write_text(json.dumps({
            "type": "level",
            "pack_id": "pack",
            "level_id": "done",
            "success": False,
        }) + "\n")
        for level in ("done", "active"):
            write_progress_snapshot(
                progress_path(results_dir, "frontier_single", "pack", level),
                {
                    "status": "running",
                    "phase": "waiting_for_model",
                    "output_key": "frontier_single",
                    "model_id": "frontier",
                    "pack_id": "pack",
                    "level_id": level,
                    "started_at": (now - timedelta(hours=1)).isoformat(),
                    "updated_at": now.isoformat(),
                    "actions_total": 30,
                    "action_limit": 60,
                },
            )

        summary = summarize_live(results_dir, now=now)

    assert summary["completed"] == 1
    assert len(summary["active"]) == 1
    assert summary["active"][0]["level_id"] == "active"
    assert summary["queued_or_untracked"] == 0
    assert summary["eta_to_action_limits_seconds"] == 3600


def test_live_summary_marks_old_snapshot_stale() -> None:
    now = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
    with TemporaryDirectory() as raw_dir:
        results_dir = Path(raw_dir)
        (results_dir / "meta.json").write_text(json.dumps({
            "total_work_items": 1,
            "action_timeout": 120,
        }))
        write_progress_snapshot(
            progress_path(results_dir, "frontier_single", "pack", "one"),
            {
                "status": "running",
                "phase": "waiting_for_model",
                "output_key": "frontier_single",
                "model_id": "frontier",
                "pack_id": "pack",
                "level_id": "one",
                "started_at": (now - timedelta(hours=1)).isoformat(),
                "updated_at": (now - timedelta(minutes=20)).isoformat(),
                "actions_total": 30,
                "action_limit": 60,
            },
        )

        summary = summarize_live(results_dir, now=now)

    assert summary["active"] == []
    assert len(summary["stale"]) == 1
    assert summary["queued_or_untracked"] == 0


def test_run_level_reports_live_actions() -> None:
    original_call_llm = bench.call_llm

    def fake_call_llm(*args, **kwargs):
        return (
            '{"action":"give_up"}',
            10.0,
            10,
            0,
            5,
            0.01,
            "",
        )

    snapshots: list[dict] = []
    bench.call_llm = fake_call_llm
    try:
        result = bench.run_level(
            "box_builder",
            "bb_001",
            {
                "id": "fixture",
                "model": "fixture",
                "connector": "fake",
                "local": False,
            },
            {"suffix": "", "reasoning": False},
            attempt_multiplier=1,
            total_multiplier=1,
            action_timeout=5,
            mode="single",
            runner="python",
            packs_dir=Path(__file__).parent.parent.parent / "packs",
            progress_callback=snapshots.append,
        )
    finally:
        bench.call_llm = original_call_llm

    waiting = [s for s in snapshots if s["phase"] == "waiting_for_model"]
    assert waiting
    assert waiting[0]["actions_total"] == 0
    assert waiting[-1]["action_limit"] == result["gold_path_length"]
    assert snapshots[-1]["status"] == "completed"
    assert snapshots[-1]["actions_total"] == result["actions_total"]


if __name__ == "__main__":
    test_atomic_snapshot_and_eta()
    test_live_summary_ignores_completed_snapshot()
    test_live_summary_marks_old_snapshot_stale()
    test_run_level_reports_live_actions()
    print("4 passed")
