from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from run_queue import (
    _assert_resume_compatible,
    _parse_provider_workers,
    _resolve_model_workers,
    _unsupported_source_migration_paths,
    all_pack_levels,
    build_work_items,
    independent_model_futures,
    model_run_specs,
)


def test_standard_matrix_has_eleven_configurations() -> None:
    model = {
        "id": "frontier",
        "display_name": "Frontier",
        "model": "frontier",
        "connector": "fake",
        "concurrency_group": "provider-a",
        "local": False,
        "variants": [{"suffix": "-xhigh", "reasoning": True}],
    }
    items = build_work_items(
        [(model, model["variants"][0])],
        {"pack": ["level"]},
        ["single", "flex-n", "full"],
        ["single", "flex-n"],
        ["text", "image", "text+image"],
        None,
    )

    assert len(items) == 11
    assert len({item.output_key for item in items}) == 11
    assert sum(item.anon for item in items) == 2
    assert all(item.input_mode == "text" for item in items if item.anon)


def test_pack_discovery_can_exclude_fixture_pack() -> None:
    with TemporaryDirectory() as temp:
        root = Path(temp)
        for pack_id in ("production", "fixture"):
            pack = root / pack_id
            pack.mkdir()
            (pack / "game.json").write_text(
                json.dumps(
                    {
                        "levelSequence": [
                            {"type": "level", "ref": f"{pack_id}_001"},
                        ]
                    }
                )
            )
        assert all_pack_levels(root, frozenset({"fixture"})) == {
            "production": ["production_001"],
        }


def test_provider_worker_parser() -> None:
    assert _parse_provider_workers(["provider-a=10", "provider-b=7"]) == {
        "provider-a": 10,
        "provider-b": 7,
    }


def test_model_worker_resolution_is_per_model() -> None:
    specs = [
        {"model_id": "frontier-a", "concurrency_group": "provider"},
        {"model_id": "frontier-b", "concurrency_group": "provider"},
    ]
    assert _resolve_model_workers(
        specs,
        workers_per_model=10,
        model_overrides={"frontier-b": 7},
    ) == {
        "frontier-a": 10,
        "frontier-b": 7,
    }


def test_model_queues_do_not_block_each_other() -> None:
    @dataclass
    class Item:
        full_variant_id: str
        name: str

    release_a = threading.Event()
    model_b_started = threading.Event()
    items = [
        Item("model-a", "a-blocked"),
        Item("model-a", "a-queued"),
        Item("model-b", "b"),
    ]

    def execute(item):
        if item.name == "a-blocked":
            release_a.wait(timeout=2)
        if item.name == "b":
            model_b_started.set()
        return item, {"success": True}

    try:
        with independent_model_futures(
            items,
            execute,
            {"model-a": 1, "model-b": 1},
        ) as futures:
            assert model_b_started.wait(timeout=1)
            release_a.set()
            assert all(future.result()[1]["success"] for future in futures)
    finally:
        release_a.set()


def test_model_specs_capture_connector_and_params() -> None:
    model = {
        "id": "frontier",
        "model": "provider-model-v1",
        "connector": "local",
        "concurrency_group": "provider-a",
        "pricing": {
            "input_per_million": 2.0,
            "output_per_million": 8.0,
        },
    }
    variant = {
        "suffix": "-xhigh",
        "params": {"reasoning_effort": "xhigh"},
    }
    assert model_run_specs([(model, variant)]) == [
        {
            "model_id": "frontier-xhigh",
            "connector": "local",
            "model": "provider-model-v1",
            "concurrency_group": "provider-a",
            "params": {"reasoning_effort": "xhigh"},
            "pricing": {
                "input_per_million": 2.0,
                "output_per_million": 8.0,
            },
        }
    ]


def test_resume_rejects_changed_model_spec() -> None:
    source = {
        "packs_digest": "sha256:one",
        "repository": {"sha": "abc", "dirty": False},
    }
    base = {
        "modes": ["single"],
        "anon_modes": [],
        "input_modes": ["text"],
        "model_variants": ["frontier-xhigh"],
        "model_specs": [{"model_id": "frontier-xhigh", "model": "v1"}],
        "action_timeout": 120,
        "attempt_multiplier": 2,
        "total_multiplier": 3,
        "flex_max_n": None,
        "flex_penalty": 0.5,
        "runner": "python",
        "levels_by_pack": {"pack": ["level"]},
        "excluded_packs": [],
        "source": source,
    }
    changed = {**base, "model_specs": [{"model_id": "frontier-xhigh", "model": "v2"}]}
    try:
        _assert_resume_compatible(base, changed)
    except SystemExit as exc:
        assert "model_specs" in str(exc)
    else:
        raise AssertionError("changed connector model should block resume")


def test_resume_allows_explicit_clean_source_migration() -> None:
    old_source = {
        "packs_digest": "sha256:one",
        "repository": {"sha": "abc", "dirty": False},
    }
    new_source = {
        "packs_digest": "sha256:one",
        "repository": {"sha": "def", "dirty": False},
    }
    base = {
        "modes": ["single"],
        "anon_modes": [],
        "input_modes": ["text"],
        "model_variants": ["frontier-xhigh"],
        "model_specs": [{"model_id": "frontier-xhigh", "model": "v1"}],
        "action_timeout": 120,
        "attempt_multiplier": 2,
        "total_multiplier": 3,
        "flex_max_n": None,
        "flex_penalty": 0.5,
        "runner": "python",
        "levels_by_pack": {"pack": ["level"]},
        "excluded_packs": [],
        "source": old_source,
    }
    current = {**base, "source": new_source}
    _assert_resume_compatible(base, current, allow_source_change=True)


def test_source_migration_rejects_unrelated_paths() -> None:
    assert _unsupported_source_migration_paths(
        [
            "engines/python/_models.py",
            "tools/benchmark/run_queue.py",
            "packs/example/game.json",
        ]
    ) == ["packs/example/game.json"]


if __name__ == "__main__":
    test_standard_matrix_has_eleven_configurations()
    test_pack_discovery_can_exclude_fixture_pack()
    test_provider_worker_parser()
    test_model_worker_resolution_is_per_model()
    test_model_queues_do_not_block_each_other()
    test_model_specs_capture_connector_and_params()
    test_resume_rejects_changed_model_spec()
    test_resume_allows_explicit_clean_source_migration()
    test_source_migration_rejects_unrelated_paths()
    print("9 passed")
