from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from study_report import build_study_report


def _episode(
    episode_id: str,
    pack_id: str,
    level_id: str,
    level_index: int,
    condition: str,
) -> dict:
    return {
        "episode_id": episode_id,
        "study_id": "study",
        "panels": ["curriculum"],
        "cells": ["text-single"],
        "priority": 1,
        "model_role": "frontier",
        "model_id": "model-x",
        "condition": condition,
        "pack_id": pack_id,
        "level_id": level_id,
        "level_index": level_index,
        "scope": "headline",
        "inference_mode": "single",
        "input_mode": "text",
        "anon": False,
        "max_n": None,
        "repeat_index": 0,
        "instruction_policy": "authored-v1",
        "session_key": (
            f"sha256:{pack_id}" if condition == "curriculum" else None
        ),
    }


def _record(episode: dict, success: bool) -> dict:
    return {
        "type": "level",
        **episode,
        "success": success,
        "actions_total": 2,
        "llm_calls": 2,
        "efficiency": 0.5 if success else None,
        "cost_usd": 0.1,
        "initial_prompt_digest": f"prompt-{episode['pack_id']}-{episode['level_id']}",
        "notebook_after_chars": (
            10 if episode["condition"] == "curriculum" else None
        ),
        "reflection_calls": 1 if episode["condition"] == "curriculum" else 0,
        "reflection": (
            {"cost_usd": 0.01}
            if episode["condition"] == "curriculum"
            else None
        ),
    }


def test_report_uses_matched_curriculum_pairs_and_excludes_first_level() -> None:
    episodes = []
    records = []
    outcomes = {
        ("game_a", "level_1", "independent"): True,
        ("game_a", "level_1", "curriculum"): True,
        ("game_a", "level_2", "independent"): False,
        ("game_a", "level_2", "curriculum"): True,
        ("game_b", "level_1", "independent"): True,
        ("game_b", "level_1", "curriculum"): True,
        ("game_b", "level_2", "independent"): False,
        ("game_b", "level_2", "curriculum"): False,
    }
    for pack_id in ("game_a", "game_b"):
        for level_index, level_id in enumerate(("level_1", "level_2")):
            for condition in ("independent", "curriculum"):
                episode = _episode(
                    f"{pack_id}-{level_id}-{condition}",
                    pack_id,
                    level_id,
                    level_index,
                    condition,
                )
                episodes.append(episode)
                records.append(
                    _record(
                        episode,
                        outcomes[(pack_id, level_id, condition)],
                    )
                )

    with TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "meta.json").write_text(
            json.dumps(
                {
                    "run_id": "run",
                    "source": {},
                    "scheduler": {},
                    "launch_history": [],
                }
            )
        )
        (root / "resolved-manifest.json").write_text(
            json.dumps(
                {
                    "study_id": "study",
                    "manifest_digest": "sha256:manifest",
                    "instruction_policy": "authored-v1",
                    "selected_panels": ["curriculum"],
                    "headline_games": ["game_a", "game_b"],
                    "diagnostic_games": ["game_a"],
                    "reliability_levels": [],
                    "models": {
                        "frontier": {
                            "variant_id": "model-x",
                            "display_name": "Model X",
                            "family": "test",
                            "tier": "frontier",
                            "reference": True,
                        }
                    },
                    "episodes": episodes,
                }
            )
        )
        with (root / "results.jsonl").open("w") as handle:
            handle.write(json.dumps({"type": "run_meta"}) + "\n")
            for record in records:
                handle.write(json.dumps(record) + "\n")

        report = build_study_report(root)

    assert report["completion"]["complete"] == 8
    assert report["completion"]["remaining"] == 0
    row = report["views"]["curriculum"]["rows"][0]
    assert row["paired_n"] == 2
    assert row["baseline_accuracy"] == 0
    assert row["comparison_accuracy"] == 0.5
    assert row["delta"] == 0.5
    diagnostics = report["views"]["curriculum"]["diagnostics"]
    assert diagnostics["first_level_prompt_parity_checked"] == 2
    assert diagnostics["first_level_prompt_parity_failures"] == []


if __name__ == "__main__":
    test_report_uses_matched_curriculum_pairs_and_excludes_first_level()
    print("1 passed")
