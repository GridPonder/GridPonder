from __future__ import annotations

from run_queue import (
    _assert_resume_compatible,
    _parse_provider_workers,
    build_work_items,
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


def test_provider_worker_parser() -> None:
    assert _parse_provider_workers(["provider-a=10", "provider-b=7"]) == {
        "provider-a": 10,
        "provider-b": 7,
    }


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
        "source": source,
    }
    changed = {**base, "model_specs": [{"model_id": "frontier-xhigh", "model": "v2"}]}
    try:
        _assert_resume_compatible(base, changed)
    except SystemExit as exc:
        assert "model_specs" in str(exc)
    else:
        raise AssertionError("changed connector model should block resume")


if __name__ == "__main__":
    test_standard_matrix_has_eleven_configurations()
    test_provider_worker_parser()
    test_model_specs_capture_connector_and_params()
    test_resume_rejects_changed_model_spec()
    print("4 passed")
