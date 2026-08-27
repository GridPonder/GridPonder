from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from study_manifest import resolve_study


MODELS = [
    {
        "id": "model-a",
        "display_name": "Model A",
        "model": "fake/a",
        "connector": "fake",
        "local": False,
        "variants": [{"suffix": "-x", "reasoning": True}],
    },
    {
        "id": "model-b",
        "display_name": "Model B",
        "model": "fake/b",
        "connector": "fake",
        "local": False,
        "variants": [{"suffix": "-x", "reasoning": True}],
    },
]


def _write_pack(root: Path, pack_id: str, levels: list[str]) -> None:
    pack = root / pack_id
    pack.mkdir()
    (pack / "manifest.json").write_text(
        json.dumps(
            {
                "gameId": pack_id,
                "title": pack_id,
                "tags": ["spatial-planning"],
            }
        )
    )
    (pack / "game.json").write_text(
        json.dumps(
            {
                "levelSequence": [
                    {"type": "level", "ref": level} for level in levels
                ]
            }
        )
    )


def _manifest() -> dict:
    return {
        "schema_version": 1,
        "study_id": "test-study",
        "instruction_policy": "authored-v1",
        "corpus": {
            "headline_games": ["one", "two"],
            "diagnostic_games": ["one"],
            "reliability_levels": [{"pack": "one", "level": "one_1"}],
        },
        "models": {
            "roles": {
                "frontier": {
                    "variant_id": "model-a-x",
                    "family": "a",
                    "tier": "frontier",
                    "reference": True,
                },
                "efficient": {
                    "variant_id": "model-b-x",
                    "family": "b",
                    "tier": "efficient",
                    "reference": False,
                },
            }
        },
        "panels": {
            "capability": {
                "model_roles": ["frontier", "efficient"],
                "cells": [
                    {
                        "id": "headline",
                        "scope": "headline",
                        "mode": "single",
                        "input_mode": "text",
                    }
                ],
            },
            "curriculum": {
                "model_roles": ["frontier"],
                "conditions": ["independent", "curriculum"],
                "cells": [
                    {
                        "id": "learn",
                        "scope": "headline",
                        "mode": "single",
                        "input_mode": "text",
                    }
                ],
            },
            "reliability": {
                "model_roles": ["frontier"],
                "repeats": 3,
                "cells": [
                    {
                        "id": "repeat",
                        "scope": "reliability",
                        "mode": "single",
                        "input_mode": "text",
                    }
                ],
            },
        },
    }


def _resolved(mutator=None):
    temp = TemporaryDirectory()
    root = Path(temp.name)
    packs = root / "packs"
    packs.mkdir()
    _write_pack(packs, "one", ["one_1", "one_2"])
    _write_pack(packs, "two", ["two_1", "two_2"])
    manifest = _manifest()
    if mutator:
        mutator(manifest)
    path = root / "study.yaml"
    path.write_text(yaml.safe_dump(manifest))
    return temp, resolve_study(path, packs, MODELS)


def test_nested_panels_reuse_identical_controls() -> None:
    temp, study = _resolved()
    try:
        # Capability: 8 placements. Curriculum: 8 placements, of which four
        # independent frontier controls are reused. Reliability: 3 placements,
        # with repeat zero reused. Canonical total = 14.
        assert study.placement_count == 19
        assert len(study.episodes) == 14
        assert study.summary()["reused_controls"] == 5
        assert study.summary()["curriculum_sessions"] == 2
    finally:
        temp.cleanup()


def test_role_substitution_preserves_episode_count() -> None:
    temp_a, study_a = _resolved()
    temp_b, study_b = _resolved(
        lambda manifest: manifest["models"]["roles"].update(
            {
                "frontier": {
                    "variant_id": "model-b-x",
                    "family": "replacement",
                    "tier": "frontier",
                    "reference": True,
                },
                "efficient": {
                    "variant_id": "model-a-x",
                    "family": "replacement",
                    "tier": "efficient",
                    "reference": False,
                },
            }
        )
    )
    try:
        assert len(study_a.episodes) == len(study_b.episodes)
        assert study_a.placement_count == study_b.placement_count
    finally:
        temp_a.cleanup()
        temp_b.cleanup()


def test_diagnostic_scope_must_be_headline_subset() -> None:
    try:
        _resolved(
            lambda manifest: manifest["corpus"].update(
                {"diagnostic_games": ["missing"]}
            )
        )
    except ValueError as exc:
        assert "subset" in str(exc)
    else:
        raise AssertionError("invalid diagnostic scope should fail")


def test_anonymous_curriculum_is_rejected() -> None:
    def mutate(manifest: dict) -> None:
        manifest["panels"]["curriculum"]["cells"][0]["anon"] = True

    try:
        _resolved(mutate)
    except ValueError as exc:
        assert "anonymous curriculum" in str(exc)
    else:
        raise AssertionError("anonymous curriculum should fail")


def test_required_tags_and_taxonomy_are_enforced() -> None:
    temp = TemporaryDirectory()
    root = Path(temp.name)
    packs = root / "packs"
    packs.mkdir()
    _write_pack(packs, "one", ["one_1", "one_2"])
    _write_pack(packs, "two", ["two_1", "two_2"])
    (root / "taxonomy.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "tags": {
                    "spatial-planning": {
                        "definition": "Plan spatial decisions."
                    }
                },
            }
        )
    )
    manifest = _manifest()
    manifest["corpus"]["require_game_tags"] = True
    manifest["corpus"]["tag_taxonomy"] = "taxonomy.yaml"
    path = root / "study.yaml"
    path.write_text(yaml.safe_dump(manifest))
    try:
        study = resolve_study(path, packs, MODELS)
        assert study.pack_tags["one"] == ("spatial-planning",)
        assert study.tag_taxonomy_digest
        assert all(
            episode.game_tags == ("spatial-planning",)
            for episode in study.episodes
        )

        one_manifest = packs / "one" / "manifest.json"
        payload = json.loads(one_manifest.read_text())
        payload["tags"] = ["unregistered-tag"]
        one_manifest.write_text(json.dumps(payload))
        try:
            resolve_study(path, packs, MODELS)
        except ValueError as exc:
            assert "frozen taxonomy" in str(exc)
        else:
            raise AssertionError("unknown taxonomy tag should fail")
    finally:
        temp.cleanup()


if __name__ == "__main__":
    test_nested_panels_reuse_identical_controls()
    test_role_substitution_preserves_episode_count()
    test_diagnostic_scope_must_be_headline_subset()
    test_anonymous_curriculum_is_rejected()
    test_required_tags_and_taxonomy_are_enforced()
    print("5 passed")
