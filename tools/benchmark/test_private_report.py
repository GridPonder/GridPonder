from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from private_report import load_run, render_html, summarize


def test_report_flags_missing_configuration_and_unknown_cost() -> None:
    with TemporaryDirectory() as raw_dir:
        results_dir = Path(raw_dir)
        run_meta = {
            "run_id": "fixture",
            "modes": ["single"],
            "anon_modes": [],
            "input_modes": ["text", "image"],
            "model_variants": ["frontier-xhigh"],
            "levels_by_pack": {"pack": ["one", "two"]},
            "source": {
                "repository": {"sha": "abc", "dirty": False},
                "packs_digest": "sha256:fixture",
                "python": {"version": "3.12"},
            },
            "scheduler_history": [
                {
                    "type": "shared_executor_with_group_semaphores",
                    "provider_workers": {"provider": 10},
                    "source_sha": "abc",
                    "active_from": "2026-08-13T00:00:00+00:00",
                },
                {
                    "type": "independent_model_executors",
                    "workers_by_model": {"frontier-xhigh": 10},
                    "source_sha": "def",
                    "active_from": "2026-08-14T00:00:00+00:00",
                    "reason": "independent queues",
                },
            ],
        }
        (results_dir / "meta.json").write_text(json.dumps(run_meta))
        records = [
            {
                "type": "run_meta",
                "model_id": "frontier-xhigh",
                "display_name": "Frontier",
                "model": "frontier",
                "model_params": {"reasoning_effort": "xhigh"},
                "inference_mode": "single",
                "anon": False,
                "input_mode": "text",
            },
            {
                "type": "level",
                "pack_id": "pack",
                "level_id": "one",
                "success": True,
                "aggregate_score": 1.0,
                "llm_calls": 1,
                "cost_usd": None,
            },
            {
                "type": "level",
                "pack_id": "pack",
                "level_id": "two",
                "success": False,
                "aggregate_score": 0.0,
                "llm_calls": 1,
                "cost_usd": None,
            },
        ]
        (results_dir / "frontier_single.jsonl").write_text(
            "\n".join(json.dumps(record) for record in records) + "\n"
        )

        loaded_meta, datasets = load_run(results_dir)
        summary = summarize(loaded_meta, datasets)
        report = render_html(summary)

    assert summary["configuration_count"] == 1
    assert summary["expected_configuration_count"] == 2
    assert summary["expected_level_runs"] == 4
    assert summary["unknown_cost_levels"] == 2
    assert summary["cost_usd"] is None
    assert summary["complete"] is False
    assert summary["missing_configurations"] == [
        "frontier-xhigh: image · single"
    ]
    assert "INCOMPLETE" in report
    assert "n/a" in report
    assert "independent_model_executors" in report
    assert "independent queues" in report


if __name__ == "__main__":
    test_report_flags_missing_configuration_and_unknown_cost()
    print("1 passed")
