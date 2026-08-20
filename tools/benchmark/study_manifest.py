"""Manifest parsing and canonical episode expansion for GridPonder studies."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from bench import all_pack_levels, expand_model_variants
from game_tags import validate_game_tags
from instructions import INSTRUCTION_POLICY, canonical_json, sha256_json, sha256_text


VALID_MODES = {"single", "fixed-n", "flex-n", "full"}
VALID_INPUTS = {"text", "image", "text+image"}
VALID_CONDITIONS = {"independent", "curriculum"}


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-") or "item"


@dataclass(frozen=True)
class ModelRole:
    role: str
    variant_id: str
    family: str
    tier: str
    reference: bool
    model: dict[str, Any] = field(compare=False, repr=False)
    variant: dict[str, Any] = field(compare=False, repr=False)

    @property
    def connector_model(self) -> str:
        value = self.model.get("model") or self.model.get("litellm_model")
        if not value:
            raise ValueError(f"Model role {self.role} has no connector model")
        return str(value)

    @property
    def connector(self) -> str:
        return str(self.model.get("connector", "litellm"))

    def provenance(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "variant_id": self.variant_id,
            "family": self.family,
            "tier": self.tier,
            "reference": self.reference,
            "display_name": self.model.get("display_name", self.variant_id),
            "connector": self.connector,
            "model": self.connector_model,
            "concurrency_group": self.model.get(
                "concurrency_group", self.connector
            ),
            "params": self.variant.get("params") or {},
            "pricing": self.model.get("pricing"),
            "local": self.model.get("local", True),
            "reasoning": self.variant.get("reasoning", False),
        }


@dataclass
class StudyEpisode:
    episode_id: str
    study_id: str
    panels: tuple[str, ...]
    cells: tuple[str, ...]
    priority: int
    model_role: ModelRole
    condition: str
    pack_id: str
    game_tags: tuple[str, ...]
    level_id: str
    level_index: int
    scope: str
    mode: str
    input_mode: str
    anon: bool
    max_n: int | None
    repeat_index: int
    instruction_policy: str

    @property
    def model_id(self) -> str:
        return self.model_role.variant_id

    @property
    def configuration_id(self) -> str:
        mode = self.mode
        if mode == "flex-n" and self.max_n:
            mode = f"flex-{self.max_n}"
        anon = "-anon" if self.anon else ""
        inp = self.input_mode.replace("+", "-")
        return f"{self.condition}-{mode}{anon}-{inp}"

    @property
    def output_key(self) -> str:
        return f"{_slug(self.model_id)}_{_slug(self.configuration_id)}"

    @property
    def session_key(self) -> str | None:
        if self.condition != "curriculum":
            return None
        raw = "|".join(
            (
                self.study_id,
                self.model_id,
                self.condition,
                self.mode,
                self.input_mode,
                str(self.anon),
                str(self.max_n),
                self.pack_id,
                str(self.repeat_index),
                self.instruction_policy,
            )
        )
        return sha256_text(raw)

    def provenance(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "study_id": self.study_id,
            "panels": list(self.panels),
            "cells": list(self.cells),
            "priority": self.priority,
            "model_role": self.model_role.role,
            "model_id": self.model_id,
            "condition": self.condition,
            "pack_id": self.pack_id,
            "game_tags": list(self.game_tags),
            "level_id": self.level_id,
            "level_index": self.level_index,
            "scope": self.scope,
            "inference_mode": self.mode,
            "input_mode": self.input_mode,
            "anon": self.anon,
            "max_n": self.max_n,
            "repeat_index": self.repeat_index,
            "instruction_policy": self.instruction_policy,
            "session_key": self.session_key,
        }


@dataclass(frozen=True)
class ResolvedStudy:
    path: Path
    raw: dict[str, Any]
    digest: str
    study_id: str
    instruction_policy: str
    headline_games: tuple[str, ...]
    diagnostic_games: tuple[str, ...]
    reliability_levels: tuple[tuple[str, str], ...]
    levels_by_pack: dict[str, list[str]]
    pack_tags: dict[str, tuple[str, ...]]
    tag_taxonomy: dict[str, Any] | None
    tag_taxonomy_digest: str | None
    model_roles: dict[str, ModelRole]
    model_selection_record: dict[str, Any] | None
    model_selection_digest: str | None
    corpus_selection_record: dict[str, Any] | None
    corpus_selection_digest: str | None
    episodes: tuple[StudyEpisode, ...]
    placement_count: int
    selected_panels: tuple[str, ...]

    def summary(self) -> dict[str, Any]:
        by_panel: dict[str, int] = {}
        by_model: dict[str, int] = {}
        by_condition: dict[str, int] = {}
        curriculum_sessions: set[str] = set()
        reflection_calls = 0
        by_tag: dict[str, int] = {}
        for episode in self.episodes:
            for panel in episode.panels:
                by_panel[panel] = by_panel.get(panel, 0) + 1
            by_model[episode.model_id] = by_model.get(episode.model_id, 0) + 1
            by_condition[episode.condition] = (
                by_condition.get(episode.condition, 0) + 1
            )
            if episode.session_key:
                curriculum_sessions.add(episode.session_key)
                reflection_calls += 1
            for tag in episode.game_tags:
                by_tag[tag] = by_tag.get(tag, 0) + 1
        return {
            "study_id": self.study_id,
            "digest": self.digest,
            "canonical_episodes": len(self.episodes),
            "panel_placements": self.placement_count,
            "reused_controls": self.placement_count - len(self.episodes),
            "curriculum_sessions": len(curriculum_sessions),
            "projected_reflection_calls": reflection_calls,
            "by_panel": dict(sorted(by_panel.items())),
            "by_model": dict(sorted(by_model.items())),
            "by_condition": dict(sorted(by_condition.items())),
            "by_tag": dict(sorted(by_tag.items())),
        }


def load_study_manifest(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("Study manifest must contain a YAML object")
    if int(raw.get("schema_version", 0)) != 1:
        raise ValueError("Study manifest schema_version must be 1")
    if not raw.get("study_id"):
        raise ValueError("Study manifest requires study_id")
    return raw


def _load_selection_record(
    manifest_path: Path,
    value: Any,
    *,
    field: str,
) -> tuple[dict[str, Any] | None, str | None]:
    if value in (None, ""):
        return None, None
    path = Path(str(value))
    if not path.is_absolute():
        path = manifest_path.parent / path
    if not path.is_file():
        raise ValueError(f"{field} does not exist: {path}")
    record = json.loads(path.read_text())
    if not isinstance(record, dict):
        raise ValueError(f"{field} must contain a JSON object")
    return record, sha256_json(record)


def _load_tag_taxonomy(
    manifest_path: Path,
    value: Any,
) -> tuple[dict[str, Any] | None, str | None, frozenset[str] | None]:
    if value in (None, ""):
        return None, None, None
    path = Path(str(value))
    if not path.is_absolute():
        path = manifest_path.parent / path
    if not path.is_file():
        raise ValueError(f"corpus.tag_taxonomy does not exist: {path}")
    record = yaml.safe_load(path.read_text())
    if not isinstance(record, dict):
        raise ValueError("corpus.tag_taxonomy must contain a YAML object")
    if int(record.get("schema_version", 0)) != 1:
        raise ValueError("corpus.tag_taxonomy schema_version must be 1")
    tags = record.get("tags")
    if not isinstance(tags, dict) or not tags:
        raise ValueError("corpus.tag_taxonomy requires a non-empty tags object")
    for tag, definition in tags.items():
        validate_game_tags(
            {"tags": [tag]},
            pack_id="tag_taxonomy",
        )
        if not isinstance(definition, dict) or not definition.get("definition"):
            raise ValueError(
                f"corpus.tag_taxonomy tag {tag!r} requires a definition"
            )
    return record, sha256_json(record), frozenset(str(tag) for tag in tags)


def _model_variant_index(
    models: list[dict[str, Any]],
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    return {
        f"{model['id']}{variant.get('suffix', '')}": (model, variant)
        for model, variant in expand_model_variants(models, None)
    }


def _resolve_roles(
    raw: dict[str, Any],
    models: list[dict[str, Any]],
) -> dict[str, ModelRole]:
    role_defs = (raw.get("models") or {}).get("roles") or {}
    if not isinstance(role_defs, dict) or not role_defs:
        raise ValueError("Study manifest requires models.roles")
    index = _model_variant_index(models)
    roles: dict[str, ModelRole] = {}
    used_variants: set[str] = set()
    for role, definition in role_defs.items():
        if not isinstance(definition, dict):
            raise ValueError(f"Model role {role} must be an object")
        variant_id = str(definition.get("variant_id") or "")
        if variant_id not in index:
            raise ValueError(
                f"Model role {role} references unknown variant {variant_id!r}"
            )
        if variant_id in used_variants:
            raise ValueError(
                f"Model variant {variant_id} is assigned to multiple roles"
            )
        model, variant = index[variant_id]
        roles[str(role)] = ModelRole(
            role=str(role),
            variant_id=variant_id,
            family=str(definition.get("family") or "unspecified"),
            tier=str(definition.get("tier") or "unspecified"),
            reference=bool(definition.get("reference", False)),
            model=model,
            variant=variant,
        )
        used_variants.add(variant_id)
    return roles


def _resolve_levels(
    raw: dict[str, Any],
    packs_dir: Path,
    allowed_tags: frozenset[str] | None,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[tuple[str, str], ...],
    dict[str, list[str]],
    dict[str, tuple[str, ...]],
]:
    available = all_pack_levels(packs_dir)
    corpus = raw.get("corpus") or {}
    headline = tuple(str(value) for value in corpus.get("headline_games") or [])
    diagnostic = tuple(
        str(value) for value in corpus.get("diagnostic_games") or []
    )
    if not headline:
        raise ValueError("corpus.headline_games must not be empty")
    missing = sorted(set(headline) - set(available))
    if missing:
        raise ValueError("Unknown headline games: " + ", ".join(missing))
    if not set(diagnostic).issubset(headline):
        raise ValueError("diagnostic_games must be a subset of headline_games")
    require_tags = bool(corpus.get("require_game_tags", False))
    pack_tags: dict[str, tuple[str, ...]] = {}
    for pack_id in headline:
        manifest_path = packs_dir / pack_id / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError(f"Missing pack manifest: {manifest_path}")
        manifest = json.loads(manifest_path.read_text())
        pack_tags[pack_id] = validate_game_tags(
            manifest,
            pack_id=pack_id,
            required=require_tags,
            allowed_tags=allowed_tags,
        )

    reliability: list[tuple[str, str]] = []
    for entry in corpus.get("reliability_levels") or []:
        if not isinstance(entry, dict):
            raise ValueError("reliability_levels entries must be objects")
        pack_id = str(entry.get("pack") or "")
        level_id = str(entry.get("level") or "")
        if pack_id not in available or level_id not in available[pack_id]:
            raise ValueError(
                f"Unknown reliability level: {pack_id}/{level_id}"
            )
        reliability.append((pack_id, level_id))

    levels_by_pack = {pack_id: list(available[pack_id]) for pack_id in headline}
    return (
        headline,
        diagnostic,
        tuple(reliability),
        levels_by_pack,
        pack_tags,
    )


def _scope_levels(
    scope: str,
    *,
    headline: tuple[str, ...],
    diagnostic: tuple[str, ...],
    reliability: tuple[tuple[str, str], ...],
    levels_by_pack: dict[str, list[str]],
) -> list[tuple[str, str, int]]:
    if scope == "headline":
        packs = headline
        return [
            (pack_id, level_id, index)
            for pack_id in packs
            for index, level_id in enumerate(levels_by_pack[pack_id])
        ]
    if scope == "diagnostic":
        packs = diagnostic
        return [
            (pack_id, level_id, index)
            for pack_id in packs
            for index, level_id in enumerate(levels_by_pack[pack_id])
        ]
    if scope == "reliability":
        return [
            (pack_id, level_id, levels_by_pack[pack_id].index(level_id))
            for pack_id, level_id in reliability
        ]
    raise ValueError(f"Unknown study scope: {scope}")


def _episode_identity(
    *,
    study_id: str,
    model_id: str,
    condition: str,
    pack_id: str,
    level_id: str,
    mode: str,
    input_mode: str,
    anon: bool,
    max_n: int | None,
    repeat_index: int,
    instruction_policy: str,
) -> str:
    return sha256_json(
        {
            "study_id": study_id,
            "model_id": model_id,
            "condition": condition,
            "pack_id": pack_id,
            "level_id": level_id,
            "mode": mode,
            "input_mode": input_mode,
            "anon": anon,
            "max_n": max_n,
            "repeat_index": repeat_index,
            "instruction_policy": instruction_policy,
        }
    )


def resolve_study(
    path: Path,
    packs_dir: Path,
    models: list[dict[str, Any]],
    *,
    selected_panels: Iterable[str] | None = None,
) -> ResolvedStudy:
    raw = load_study_manifest(path)
    model_selection_record, model_selection_digest = _load_selection_record(
        path,
        (raw.get("models") or {}).get("selection_record"),
        field="models.selection_record",
    )
    corpus_selection_record, corpus_selection_digest = _load_selection_record(
        path,
        (raw.get("corpus") or {}).get("selection_record"),
        field="corpus.selection_record",
    )
    (
        tag_taxonomy,
        tag_taxonomy_digest,
        allowed_tags,
    ) = _load_tag_taxonomy(
        path,
        (raw.get("corpus") or {}).get("tag_taxonomy"),
    )
    digest = sha256_json(
        {
            "manifest": raw,
            "model_selection_record": model_selection_record,
            "corpus_selection_record": corpus_selection_record,
            "tag_taxonomy": tag_taxonomy,
        }
    )
    study_id = str(raw["study_id"])
    instruction_policy = str(
        raw.get("instruction_policy") or INSTRUCTION_POLICY
    )
    roles = _resolve_roles(raw, models)
    (
        headline,
        diagnostic,
        reliability,
        levels_by_pack,
        pack_tags,
    ) = _resolve_levels(
        raw,
        packs_dir,
        allowed_tags,
    )

    panel_defs = raw.get("panels") or {}
    if not isinstance(panel_defs, dict) or not panel_defs:
        raise ValueError("Study manifest requires panels")
    selected = tuple(selected_panels or panel_defs.keys())
    unknown_panels = sorted(set(selected) - set(panel_defs))
    if unknown_panels:
        raise ValueError("Unknown panels: " + ", ".join(unknown_panels))

    episodes_by_id: dict[str, StudyEpisode] = {}
    placement_count = 0
    for panel_name in selected:
        panel = panel_defs[panel_name] or {}
        panel_roles = list(panel.get("model_roles") or [])
        if not panel_roles:
            raise ValueError(f"Panel {panel_name} has no model_roles")
        unknown_roles = sorted(set(panel_roles) - set(roles))
        if unknown_roles:
            raise ValueError(
                f"Panel {panel_name} has unknown roles: "
                + ", ".join(unknown_roles)
            )
        panel_conditions = list(panel.get("conditions") or ["independent"])
        repeats = int(panel.get("repeats", 1))
        priority = int(panel.get("priority", 100))
        if repeats < 1:
            raise ValueError(f"Panel {panel_name} repeats must be positive")
        cells = panel.get("cells") or []
        if not cells:
            raise ValueError(f"Panel {panel_name} has no cells")

        for cell_index, cell in enumerate(cells):
            cell_id = str(cell.get("id") or f"{panel_name}-{cell_index + 1}")
            scope = str(cell.get("scope") or "diagnostic")
            mode = str(cell.get("mode") or "single")
            input_mode = str(cell.get("input_mode") or "text")
            anon = bool(cell.get("anon", False))
            max_n = cell.get("max_n")
            if max_n is not None:
                max_n = int(max_n)
            conditions = list(cell.get("conditions") or panel_conditions)
            cell_roles = list(cell.get("model_roles") or panel_roles)
            cell_repeats = int(cell.get("repeats", repeats))

            if mode not in VALID_MODES:
                raise ValueError(f"Cell {cell_id} has invalid mode {mode}")
            if input_mode not in VALID_INPUTS:
                raise ValueError(
                    f"Cell {cell_id} has invalid input_mode {input_mode}"
                )
            if anon and input_mode != "text":
                raise ValueError(
                    f"Cell {cell_id}: anonymous conditions must use text"
                )
            if mode != "flex-n" and max_n is not None:
                raise ValueError(
                    f"Cell {cell_id}: max_n is only valid for flex-n"
                )
            if any(condition not in VALID_CONDITIONS for condition in conditions):
                raise ValueError(
                    f"Cell {cell_id} has invalid conditions {conditions}"
                )
            if anon and "curriculum" in conditions:
                raise ValueError(
                    f"Cell {cell_id}: anonymous curriculum is not supported"
                )

            scoped_levels = _scope_levels(
                scope,
                headline=headline,
                diagnostic=diagnostic,
                reliability=reliability,
                levels_by_pack=levels_by_pack,
            )
            for role_name in cell_roles:
                role = roles.get(role_name)
                if role is None:
                    raise ValueError(
                        f"Cell {cell_id} references unknown role {role_name}"
                    )
                for condition in conditions:
                    for repeat_index in range(cell_repeats):
                        for pack_id, level_id, level_index in scoped_levels:
                            placement_count += 1
                            episode_id = _episode_identity(
                                study_id=study_id,
                                model_id=role.variant_id,
                                condition=condition,
                                pack_id=pack_id,
                                level_id=level_id,
                                mode=mode,
                                input_mode=input_mode,
                                anon=anon,
                                max_n=max_n,
                                repeat_index=repeat_index,
                                instruction_policy=instruction_policy,
                            )
                            existing = episodes_by_id.get(episode_id)
                            if existing is not None:
                                existing.panels = tuple(
                                    sorted(set(existing.panels) | {panel_name})
                                )
                                existing.cells = tuple(
                                    sorted(set(existing.cells) | {cell_id})
                                )
                                existing.priority = min(existing.priority, priority)
                                continue
                            episodes_by_id[episode_id] = StudyEpisode(
                                episode_id=episode_id,
                                study_id=study_id,
                                panels=(panel_name,),
                                cells=(cell_id,),
                                priority=priority,
                                model_role=role,
                                condition=condition,
                                pack_id=pack_id,
                                game_tags=pack_tags[pack_id],
                                level_id=level_id,
                                level_index=level_index,
                                scope=scope,
                                mode=mode,
                                input_mode=input_mode,
                                anon=anon,
                                max_n=max_n,
                                repeat_index=repeat_index,
                                instruction_policy=instruction_policy,
                            )

    episodes = tuple(
        sorted(
            episodes_by_id.values(),
            key=lambda item: (
                item.priority,
                item.model_id,
                item.condition != "curriculum",
                item.pack_id,
                item.level_index,
                item.configuration_id,
                item.repeat_index,
            ),
        )
    )
    return ResolvedStudy(
        path=path.resolve(),
        raw=raw,
        digest=digest,
        study_id=study_id,
        instruction_policy=instruction_policy,
        headline_games=headline,
        diagnostic_games=diagnostic,
        reliability_levels=reliability,
        levels_by_pack=levels_by_pack,
        pack_tags=pack_tags,
        tag_taxonomy=tag_taxonomy,
        tag_taxonomy_digest=tag_taxonomy_digest,
        model_roles=roles,
        model_selection_record=model_selection_record,
        model_selection_digest=model_selection_digest,
        corpus_selection_record=corpus_selection_record,
        corpus_selection_digest=corpus_selection_digest,
        episodes=episodes,
        placement_count=placement_count,
        selected_panels=selected,
    )


def write_resolved_manifest(study: ResolvedStudy, path: Path) -> None:
    payload = {
        "schema_version": 1,
        "study_id": study.study_id,
        "manifest_path": str(study.path),
        "manifest_digest": study.digest,
        "instruction_policy": study.instruction_policy,
        "headline_games": list(study.headline_games),
        "diagnostic_games": list(study.diagnostic_games),
        "game_tags": {
            pack_id: list(tags)
            for pack_id, tags in sorted(study.pack_tags.items())
        },
        "tag_taxonomy": {
            "digest": study.tag_taxonomy_digest,
            "record": study.tag_taxonomy,
        },
        "reliability_levels": [
            {"pack": pack_id, "level": level_id}
            for pack_id, level_id in study.reliability_levels
        ],
        "models": {
            role: model_role.provenance()
            for role, model_role in sorted(study.model_roles.items())
        },
        "model_selection": {
            "digest": study.model_selection_digest,
            "record": study.model_selection_record,
        },
        "corpus_selection": {
            "digest": study.corpus_selection_digest,
            "record": study.corpus_selection_record,
        },
        "selected_panels": list(study.selected_panels),
        "panel_definitions": {
            panel: study.raw["panels"][panel]
            for panel in study.selected_panels
        },
        "summary": study.summary(),
        "episodes": [episode.provenance() for episode in study.episodes],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")
