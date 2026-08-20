#!/usr/bin/env python3
"""Run a manifest-defined GridPonder nested-panel study."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from tqdm import tqdm

from bench import all_pack_levels, load_models, run_level
from curriculum import (
    ReflectionResult,
    advance_session_state,
    atomic_write_json,
    empty_session_state,
    load_pending_checkpoint,
    load_session_state,
    notebook_digest,
    pending_checkpoint,
    reflect_notebook,
    session_file_name,
)
from instructions import (
    InstructionPayload,
    audit_instruction_payloads,
    compile_instruction_map,
    sha256_json,
)
from live_progress import progress_path, write_progress_snapshot
from run_manifest import source_snapshot
from run_queue import _parse_model_workers, _resolve_model_workers
from study_manifest import (
    ResolvedStudy,
    StudyEpisode,
    resolve_study,
    write_resolved_manifest,
)


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
RESULTS_BASE = SCRIPT_DIR / "results" / "study"
SCHEDULER_TYPE = "independent_model_executors_with_ordered_sessions"
_shutdown = threading.Event()


@dataclass(frozen=True)
class StudyTask:
    full_variant_id: str
    task_id: str
    priority: int
    episodes: tuple[StudyEpisode, ...]
    curriculum: bool


class ResultWriter:
    """Append JSONL records synchronously so session checkpoints can follow."""

    def __init__(
        self,
        results_dir: Path,
        meta_by_key: dict[str, dict[str, Any]],
    ) -> None:
        self.results_dir = results_dir
        self.meta_by_key = meta_by_key
        self._lock = threading.Lock()

    def append(self, output_key: str, record: dict[str, Any]) -> None:
        path = self.results_dir / f"{output_key}.jsonl"
        with self._lock:
            is_new = not path.exists() or path.stat().st_size == 0
            with path.open("a") as handle:
                if is_new:
                    handle.write(json.dumps(self.meta_by_key[output_key]) + "\n")
                handle.write(json.dumps(record) + "\n")
                handle.flush()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_episode_records(
    results_dir: Path,
) -> tuple[dict[str, list[dict[str, Any]]], set[str]]:
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    valid: set[str] = set()
    if not results_dir.is_dir():
        return records, valid
    for path in sorted(results_dir.glob("*.jsonl")):
        with path.open() as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") != "level" or not record.get("episode_id"):
                    continue
                episode_id = str(record["episode_id"])
                records[episode_id].append(record)
                if "error" not in record:
                    valid.add(episode_id)
    return records, valid


def _build_tasks(
    episodes: list[StudyEpisode],
    completed: set[str],
) -> list[StudyTask]:
    independent: list[StudyTask] = []
    sessions: dict[str, list[StudyEpisode]] = defaultdict(list)
    for episode in episodes:
        if episode.session_key:
            sessions[episode.session_key].append(episode)
        elif episode.episode_id not in completed:
            independent.append(
                StudyTask(
                    full_variant_id=episode.model_id,
                    task_id=episode.episode_id,
                    priority=episode.priority,
                    episodes=(episode,),
                    curriculum=False,
                )
            )
    curriculum = [
        StudyTask(
            full_variant_id=items[0].model_id,
            task_id=session_key,
            priority=min(item.priority for item in items),
            episodes=tuple(
                sorted(items, key=lambda item: (item.level_index, item.repeat_index))
            ),
            curriculum=True,
        )
        for session_key, items in sessions.items()
        if any(item.episode_id not in completed for item in items)
    ]
    return sorted(
        [*curriculum, *independent],
        key=lambda task: (
            task.priority,
            not task.curriculum,
            task.full_variant_id,
            task.task_id,
        ),
    )


def _run_meta_for_output(
    output_key: str,
    episodes: list[StudyEpisode],
    run_id: str,
    action_timeout: int | None,
    attempt_multiplier: int,
    total_multiplier: int,
) -> dict[str, Any]:
    first = episodes[0]
    role = first.model_role
    return {
        "type": "run_meta",
        "schema_version": 2,
        "study_id": first.study_id,
        "model_id": first.model_id,
        "model_role": role.role,
        "model_family": role.family,
        "model_tier": role.tier,
        "display_name": role.model.get("display_name", first.model_id),
        "connector": role.connector,
        "model": role.connector_model,
        "model_params": role.variant.get("params") or {},
        "pricing": role.model.get("pricing"),
        "local": role.model.get("local", True),
        "reasoning": role.variant.get("reasoning", False),
        "condition": first.condition,
        "inference_mode": first.mode,
        "anon": first.anon,
        "input_mode": first.input_mode,
        "max_n": first.max_n,
        "instruction_policy": first.instruction_policy,
        "output_key": output_key,
        "expected_episode_ids": sorted(
            episode.episode_id for episode in episodes
        ),
        "attempt_multiplier": attempt_multiplier,
        "total_multiplier": total_multiplier,
        "action_timeout": action_timeout,
        "run_id": run_id,
        "timestamp": _now(),
    }


def _study_model_specs(study: ResolvedStudy) -> list[dict[str, Any]]:
    return [
        {
            "model_id": role.variant_id,
            "concurrency_group": role.model.get(
                "concurrency_group", role.connector
            ),
        }
        for role in study.model_roles.values()
        if any(
            episode.model_id == role.variant_id for episode in study.episodes
        )
    ]


def _assert_resume_compatible(
    existing: dict[str, Any],
    current: dict[str, Any],
) -> None:
    fields = [
        "study_id",
        "study_manifest_digest",
        "instruction_policy",
        "selected_panels",
        "model_roles",
        "episode_ids",
        "action_timeout",
        "attempt_multiplier",
        "total_multiplier",
        "flex_penalty",
        "runner",
    ]
    mismatches = [
        field for field in fields
        if existing.get(field) != current.get(field)
    ]
    old_source = existing.get("source") or {}
    new_source = current.get("source") or {}
    for field in ("packs_digest",):
        if old_source.get(field) != new_source.get(field):
            mismatches.append(f"source.{field}")
    for repository_key in ("repository", "packs_repository"):
        old_repo = old_source.get(repository_key) or {}
        new_repo = new_source.get(repository_key) or {}
        if old_repo.get("sha") != new_repo.get("sha"):
            mismatches.append(f"source.{repository_key}.sha")
        if old_repo.get("dirty") or new_repo.get("dirty"):
            mismatches.append(f"source.{repository_key}.dirty")
    if mismatches:
        raise SystemExit(
            "Refusing to resume an incompatible study: "
            + ", ".join(mismatches)
        )


def _source_is_dirty(source: dict[str, Any]) -> list[str]:
    dirty: list[str] = []
    for name in ("repository", "packs_repository"):
        snapshot = source.get(name) or {}
        if snapshot.get("dirty"):
            dirty.append(name)
    return dirty


def _write_meta(path: Path, value: dict[str, Any]) -> None:
    atomic_write_json(path, value)


def _merge_reflection_cost(
    gameplay: dict[str, Any],
    reflection: ReflectionResult,
) -> dict[str, Any]:
    result = dict(gameplay)
    gameplay_cost = gameplay.get("cost_usd")
    reflection_cost = reflection.cost_usd
    result["gameplay_cost_usd"] = gameplay_cost
    result["reflection"] = reflection.public_metadata()
    result["reflection_calls"] = 1
    result["total_llm_calls"] = int(gameplay.get("llm_calls") or 0) + 1
    if gameplay_cost is None or reflection_cost is None:
        result["cost_usd"] = None
    else:
        result["cost_usd"] = round(float(gameplay_cost) + reflection_cost, 6)
    result["gameplay_input_tokens_total"] = int(
        gameplay.get("input_tokens_total") or 0
    )
    result["gameplay_thinking_tokens_total"] = int(
        gameplay.get("thinking_tokens_total") or 0
    )
    result["gameplay_output_tokens_total"] = int(
        gameplay.get("output_tokens_total") or 0
    )
    result["input_tokens_total"] = (
        result["gameplay_input_tokens_total"] + reflection.input_tokens
    )
    result["thinking_tokens_total"] = (
        result["gameplay_thinking_tokens_total"] + reflection.reasoning_tokens
    )
    result["output_tokens_total"] = (
        result["gameplay_output_tokens_total"] + reflection.output_tokens
    )
    return result


def _episode_context(episode: StudyEpisode) -> dict[str, Any]:
    return {
        "episode_id": episode.episode_id,
        "study_id": episode.study_id,
        "panels": list(episode.panels),
        "cells": list(episode.cells),
        "model_role": episode.model_role.role,
        "model_family": episode.model_role.family,
        "model_tier": episode.model_role.tier,
        "condition": episode.condition,
        "game_tags": list(episode.game_tags),
        "scope": episode.scope,
        "level_index": episode.level_index,
        "repeat_index": episode.repeat_index,
        "configuration_id": episode.configuration_id,
        "session_key": episode.session_key,
    }


def _progress_callback(
    *,
    results_dir: Path,
    episode: StudyEpisode,
    launch_session_id: str,
) -> Callable[[dict[str, Any]], None]:
    progress_level = (
        f"{episode.level_id}__r{episode.repeat_index}"
        if episode.repeat_index
        else episode.level_id
    )
    path = progress_path(
        results_dir,
        episode.output_key,
        episode.pack_id,
        progress_level,
    )
    warned = False

    def callback(snapshot: dict[str, Any]) -> None:
        nonlocal warned
        try:
            write_progress_snapshot(
                path,
                {
                    **snapshot,
                    **_episode_context(episode),
                    "launch_session_id": launch_session_id,
                    "output_key": episode.output_key,
                },
            )
        except Exception as exc:
            if not warned:
                tqdm.write(
                    f"Live progress write failed for "
                    f"{episode.pack_id}/{episode.level_id}: {exc}"
                )
                warned = True

    return callback


def _run_episode_gameplay(
    *,
    episode: StudyEpisode,
    instruction: InstructionPayload,
    notebook: str,
    args: argparse.Namespace,
    results_dir: Path,
    launch_session_id: str,
) -> dict[str, Any]:
    role = episode.model_role
    authored_instruction = None if episode.anon else instruction
    return run_level(
        episode.pack_id,
        episode.level_id,
        role.model,
        role.variant,
        args.attempt_multiplier,
        args.total_multiplier,
        action_timeout=args.action_timeout,
        mode=episode.mode,
        step_size=3,
        max_n=episode.max_n,
        flex_penalty=args.flex_penalty,
        anon=episode.anon,
        runner=args.runner,
        input_mode=episode.input_mode,
        packs_dir=args.packs_dir,
        progress_callback=_progress_callback(
            results_dir=results_dir,
            episode=episode,
            launch_session_id=launch_session_id,
        ),
        instruction_payload=authored_instruction,
        game_notebook=notebook,
        result_context={
            **_episode_context(episode),
            "instruction_context_applied": authored_instruction is not None,
            "instruction_digest": (
                authored_instruction.digest if authored_instruction else None
            ),
        },
    )


def _error_record(
    episode: StudyEpisode,
    exc: Exception,
    *,
    phase: str,
) -> dict[str, Any]:
    return {
        "type": "level",
        **_episode_context(episode),
        "model_id": episode.model_id,
        "pack_id": episode.pack_id,
        "level_id": episode.level_id,
        "inference_mode": episode.mode,
        "input_mode": episode.input_mode,
        "anon": episode.anon,
        "timestamp": _now(),
        "success": False,
        "error": str(exc),
        "error_type": type(exc).__name__,
        "error_phase": phase,
    }


def _execute_independent(
    task: StudyTask,
    *,
    instructions: dict[tuple[str, str], InstructionPayload],
    args: argparse.Namespace,
    results_dir: Path,
    launch_session_id: str,
    writer: ResultWriter,
) -> list[dict[str, Any]]:
    episode = task.episodes[0]
    if _shutdown.is_set():
        return []
    try:
        result = _run_episode_gameplay(
            episode=episode,
            instruction=instructions[(episode.pack_id, episode.level_id)],
            notebook="",
            args=args,
            results_dir=results_dir,
            launch_session_id=launch_session_id,
        )
    except Exception as exc:
        result = _error_record(episode, exc, phase="gameplay")
    writer.append(episode.output_key, result)
    return [result]


def _reflection_from_pending(value: dict[str, Any]) -> ReflectionResult:
    return ReflectionResult(**value)


def _execute_curriculum(
    task: StudyTask,
    *,
    instructions: dict[tuple[str, str], InstructionPayload],
    args: argparse.Namespace,
    results_dir: Path,
    launch_session_id: str,
    writer: ResultWriter,
    valid_episode_ids: set[str],
) -> list[dict[str, Any]]:
    episodes = list(task.episodes)
    first = episodes[0]
    session_key = first.session_key
    if session_key is None:
        raise RuntimeError("Curriculum task has no session key")

    sessions_dir = results_dir / "sessions"
    session_path = sessions_dir / session_file_name(session_key)
    expected_state = empty_session_state(
        session_key=session_key,
        study_id=first.study_id,
        model_id=first.model_id,
        model_role=first.model_role.role,
        pack_id=first.pack_id,
        configuration_id=first.configuration_id,
        instruction_policy=first.instruction_policy,
        expected_episode_ids=[episode.episode_id for episode in episodes],
    )
    state = load_session_state(session_path, expected_state)
    emitted: list[dict[str, Any]] = []
    pending_dir = sessions_dir / "pending"

    for episode in episodes:
        if _shutdown.is_set():
            break
        cursor = int(state["cursor"])
        pending_path = pending_dir / (
            episode.episode_id.removeprefix("sha256:") + ".json"
        )
        if episode.episode_id in state["completed_episode_ids"]:
            if episode.episode_id not in valid_episode_ids:
                raise ValueError(
                    f"Session state advances beyond durable result "
                    f"{episode.episode_id}"
                )
            pending_path.unlink(missing_ok=True)
            continue
        expected_id = state["expected_episode_ids"][cursor]
        if expected_id != episode.episode_id:
            raise ValueError(
                f"Curriculum sequence mismatch: expected {expected_id}, "
                f"got {episode.episode_id}"
            )

        instruction = instructions[(episode.pack_id, episode.level_id)]
        notebook_before = str(state.get("notebook") or "")
        pending = load_pending_checkpoint(
            pending_path,
            episode_id=episode.episode_id,
            instruction_digest=instruction.digest,
            notebook_before=notebook_before,
        )
        if episode.episode_id in valid_episode_ids and (
            pending is None or pending.get("status") != "reflected"
        ):
            raise ValueError(
                "Durable curriculum result is ahead of its session cursor "
                f"without a reflected pending checkpoint: {episode.episode_id}"
            )

        if pending is None:
            try:
                gameplay = _run_episode_gameplay(
                    episode=episode,
                    instruction=instruction,
                    notebook=notebook_before,
                    args=args,
                    results_dir=results_dir,
                    launch_session_id=launch_session_id,
                )
            except Exception as exc:
                error = _error_record(episode, exc, phase="gameplay")
                writer.append(episode.output_key, error)
                emitted.append(error)
                break
            if "error" in gameplay:
                writer.append(episode.output_key, gameplay)
                emitted.append(gameplay)
                break
            pending = pending_checkpoint(
                episode=_episode_context(episode),
                instruction=instruction,
                notebook_before=notebook_before,
                gameplay_result=gameplay,
            )
            pending["status"] = "gameplay_complete"
            atomic_write_json(pending_path, pending)

        gameplay = dict(pending["gameplay_result"])
        if pending.get("status") == "reflected":
            reflection = _reflection_from_pending(pending["reflection"])
            notebook_after = str(pending["notebook_after"])
            final_result = dict(pending["final_result"])
        else:
            try:
                reflection = reflect_notebook(
                    instruction=instruction,
                    notebook_before=notebook_before,
                    gameplay_result=gameplay,
                    model=episode.model_role.model,
                    variant=episode.model_role.variant,
                    timeout_s=args.action_timeout,
                )
            except Exception as exc:
                error = _error_record(episode, exc, phase="reflection")
                error["pending_gameplay_digest"] = pending[
                    "gameplay_result_digest"
                ]
                error["reflection_calls"] = 1
                writer.append(episode.output_key, error)
                emitted.append(error)
                break
            notebook_after = reflection.notebook
            final_result = _merge_reflection_cost(gameplay, reflection)
            final_result.update(
                {
                    "notebook_after_digest": notebook_digest(notebook_after),
                    "notebook_after_chars": len(notebook_after),
                }
            )
            pending.update(
                {
                    "status": "reflected",
                    "reflection": asdict(reflection),
                    "notebook_after": notebook_after,
                    "final_result": final_result,
                }
            )
            atomic_write_json(pending_path, pending)

        if episode.episode_id not in valid_episode_ids:
            writer.append(episode.output_key, final_result)
            valid_episode_ids.add(episode.episode_id)
            emitted.append(final_result)
        state = advance_session_state(
            state,
            episode_id=episode.episode_id,
            notebook=notebook_after,
            reflection=reflection,
            outcome=gameplay,
        )
        atomic_write_json(session_path, state)
        pending_path.unlink(missing_ok=True)

    return emitted


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a predeclared GridPonder nested-panel study with durable "
            "curriculum sessions."
        )
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--packs-dir",
        type=Path,
        default=REPO_ROOT / "packs",
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        help="Output directory; defaults to a timestamped study directory",
    )
    parser.add_argument(
        "--panel",
        action="append",
        default=[],
        help="Run only one named panel; repeatable",
    )
    parser.add_argument("--workers-per-model", type=int, default=20)
    parser.add_argument(
        "--model-workers",
        action="append",
        default=[],
        metavar="MODEL=N",
        help="Override workers for one resolved model variant; repeatable",
    )
    parser.add_argument(
        "--action-timeout",
        type=int,
        default=1800,
        help="Per-model-call timeout in seconds",
    )
    parser.add_argument("--attempt-multiplier", type=int, default=2)
    parser.add_argument("--total-multiplier", type=int, default=3)
    parser.add_argument("--flex-penalty", type=float, default=0.5)
    parser.add_argument(
        "--runner",
        choices=["auto", "dart", "python"],
        default="auto",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and print the exact workload without model calls",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the manifest and authored instruction stream",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Permit dirty source trees for local fake-model development only",
    )
    parser.add_argument(
        "--no-caffeinate",
        action="store_true",
        help="Do not prevent macOS idle sleep while the study is running",
    )
    return parser.parse_args()


def _corpus_source_snapshot(
    study: ResolvedStudy,
    packs_dir: Path,
) -> dict[str, Any]:
    available = all_pack_levels(packs_dir)
    excluded = sorted(set(available) - set(study.headline_games))
    return source_snapshot(REPO_ROOT, packs_dir, excluded)


def _current_run_config(
    *,
    args: argparse.Namespace,
    study: ResolvedStudy,
    source: dict[str, Any],
    run_id: str,
    launch_session_id: str,
    model_workers: dict[str, int],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "launch_session_id": launch_session_id,
        "timestamp": _now(),
        "launcher": "run_study.py",
        "scheduler": {
            "type": SCHEDULER_TYPE,
            "workers_by_model": model_workers,
            "total_capacity": sum(model_workers.values()),
        },
        "study_id": study.study_id,
        "study_manifest": str(study.path),
        "study_manifest_digest": study.digest,
        "instruction_policy": study.instruction_policy,
        "selected_panels": list(study.selected_panels),
        "model_roles": {
            name: role.provenance()
            for name, role in sorted(study.model_roles.items())
        },
        "model_selection_digest": study.model_selection_digest,
        "corpus_selection_digest": study.corpus_selection_digest,
        "episode_ids": sorted(
            episode.episode_id for episode in study.episodes
        ),
        "summary": study.summary(),
        "total_work_items": len(study.episodes),
        "packs_dir": str(args.packs_dir.resolve()),
        "action_timeout": args.action_timeout,
        "attempt_multiplier": args.attempt_multiplier,
        "total_multiplier": args.total_multiplier,
        "flex_penalty": args.flex_penalty,
        "runner": args.runner,
        "source": source,
    }


def _print_study_summary(
    study: ResolvedStudy,
    model_workers: dict[str, int],
    *,
    completed: int,
    remaining: int,
) -> None:
    summary = study.summary()
    print("=" * 72)
    print("  GridPonder manifest-defined study")
    print(f"  Study:             {study.study_id}")
    print(f"  Panels:            {', '.join(study.selected_panels)}")
    print(f"  Canonical episodes:{summary['canonical_episodes']:>8}")
    print(f"  Reused controls:   {summary['reused_controls']:>8}")
    print(f"  Curriculum sessions:{summary['curriculum_sessions']:>7}")
    print(f"  Reflection calls:  {summary['projected_reflection_calls']:>8}")
    print(f"  Completed:         {completed:>8}")
    print(f"  Remaining:         {remaining:>8}")
    print(
        "  Model workers:     "
        + ", ".join(
            f"{model_id}={workers}"
            for model_id, workers in sorted(model_workers.items())
        )
    )
    print(f"  Total capacity:    {sum(model_workers.values()):>8}")
    print("=" * 72)


def _task_error_record(
    task: StudyTask,
    exc: Exception,
    valid_episode_ids: set[str],
) -> tuple[str, dict[str, Any]] | None:
    episode = next(
        (
            item
            for item in task.episodes
            if item.episode_id not in valid_episode_ids
        ),
        None,
    )
    if episode is None:
        return None
    return episode.output_key, _error_record(
        episode,
        exc,
        phase="curriculum_session" if task.curriculum else "launcher",
    )


def main() -> None:
    args = _parse_args()
    load_dotenv()
    args.manifest = args.manifest.resolve()
    args.packs_dir = args.packs_dir.resolve()
    if args.action_timeout is not None and args.action_timeout < 1:
        raise SystemExit("--action-timeout must be positive")
    if args.attempt_multiplier < 1 or args.total_multiplier < 1:
        raise SystemExit("Action multipliers must be positive")

    selected_panels = args.panel or None
    study = resolve_study(
        args.manifest,
        args.packs_dir,
        load_models(),
        selected_panels=selected_panels,
    )
    instructions = compile_instruction_map(
        args.packs_dir,
        study.headline_games,
        policy=study.instruction_policy,
    )
    missing_instructions = sorted(
        {
            (episode.pack_id, episode.level_id)
            for episode in study.episodes
            if (episode.pack_id, episode.level_id) not in instructions
        }
    )
    if missing_instructions:
        raise SystemExit(
            "Missing authored instruction payloads: "
            + ", ".join(f"{pack}/{level}" for pack, level in missing_instructions)
        )
    instruction_audit = audit_instruction_payloads(instructions.values())
    if not instruction_audit["ok"]:
        raise SystemExit(
            "Instruction audit failed: "
            + json.dumps(instruction_audit["issues"])
        )

    model_workers = _resolve_model_workers(
        _study_model_specs(study),
        args.workers_per_model,
        _parse_model_workers(args.model_workers),
    )
    results_dir = (
        args.run_dir.resolve()
        if args.run_dir
        else RESULTS_BASE / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    )
    existing_records, valid_episode_ids = _load_episode_records(results_dir)
    duplicate_valid = {
        episode_id: sum("error" not in record for record in records)
        for episode_id, records in existing_records.items()
        if sum("error" not in record for record in records) > 1
    }
    if duplicate_valid:
        raise SystemExit(
            "Run directory contains duplicate valid episode records: "
            + ", ".join(sorted(duplicate_valid)[:10])
        )
    unknown_results = sorted(
        set(existing_records)
        - {episode.episode_id for episode in study.episodes}
    )
    if unknown_results:
        raise SystemExit(
            f"Run directory contains {len(unknown_results)} episode(s) "
            "outside the resolved manifest"
        )
    tasks = _build_tasks(list(study.episodes), valid_episode_ids)
    remaining = sum(
        episode.episode_id not in valid_episode_ids
        for episode in study.episodes
    )
    _print_study_summary(
        study,
        model_workers,
        completed=len(valid_episode_ids),
        remaining=remaining,
    )
    print(
        f"  Instruction audit: {instruction_audit['payload_count']} payloads, "
        f"{len(instruction_audit['warnings'])} warnings"
    )

    if args.validate_only or args.dry_run:
        by_model: dict[str, int] = defaultdict(int)
        by_condition: dict[str, int] = defaultdict(int)
        for episode in study.episodes:
            if episode.episode_id in valid_episode_ids:
                continue
            by_model[episode.model_id] += 1
            by_condition[episode.condition] += 1
        for model_id, count in sorted(by_model.items()):
            print(f"  {model_id}: {count} remaining episodes")
        for condition, count in sorted(by_condition.items()):
            print(f"  condition/{condition}: {count} remaining episodes")
        print(f"  Scheduler tasks: {len(tasks)}")
        return

    source = _corpus_source_snapshot(study, args.packs_dir)
    dirty_sources = _source_is_dirty(source)
    if dirty_sources and not args.allow_dirty:
        raise SystemExit(
            "Refusing a paid study from dirty source trees: "
            + ", ".join(dirty_sources)
        )

    results_dir.mkdir(parents=True, exist_ok=True)
    meta_path = results_dir / "meta.json"
    existing_meta = (
        json.loads(meta_path.read_text()) if meta_path.is_file() else None
    )
    if not existing_meta and any(results_dir.glob("*.jsonl")):
        raise SystemExit(
            f"Refusing {results_dir}: JSONL files exist without meta.json"
        )
    run_id = (
        str(existing_meta.get("run_id"))
        if existing_meta
        else str(uuid.uuid4())
    )
    launch_session_id = str(uuid.uuid4())
    run_config = _current_run_config(
        args=args,
        study=study,
        source=source,
        run_id=run_id,
        launch_session_id=launch_session_id,
        model_workers=model_workers,
    )
    if existing_meta:
        _assert_resume_compatible(existing_meta, run_config)
        run_config["timestamp"] = existing_meta.get(
            "timestamp", run_config["timestamp"]
        )
        run_config["resumed_at"] = _now()
        run_config["resume_history"] = [
            *list(existing_meta.get("resume_history") or []),
            {
                "resumed_at": run_config["resumed_at"],
                "launch_session_id": launch_session_id,
                "completed_before_resume": len(valid_episode_ids),
                "remaining_before_resume": remaining,
                "scheduler": run_config["scheduler"],
            },
        ]
        run_config["launch_history"] = [
            *list(existing_meta.get("launch_history") or []),
            {
                "launch_session_id": launch_session_id,
                "started_at": run_config["resumed_at"],
                "workers_by_model": model_workers,
            },
        ]
    else:
        run_config["resume_history"] = []
        run_config["launch_history"] = [
            {
                "launch_session_id": launch_session_id,
                "started_at": run_config["timestamp"],
                "workers_by_model": model_workers,
            }
        ]
    _write_meta(meta_path, run_config)
    write_resolved_manifest(study, results_dir / "resolved-manifest.json")
    _write_meta(results_dir / "instruction-audit.json", instruction_audit)

    if remaining == 0:
        print("Nothing to do: all study episodes are complete.")
        return

    episodes_by_output: dict[str, list[StudyEpisode]] = defaultdict(list)
    for episode in study.episodes:
        episodes_by_output[episode.output_key].append(episode)
    meta_by_key = {
        output_key: _run_meta_for_output(
            output_key,
            episodes,
            run_id,
            args.action_timeout,
            args.attempt_multiplier,
            args.total_multiplier,
        )
        for output_key, episodes in episodes_by_output.items()
    }
    writer = ResultWriter(results_dir, meta_by_key)
    valid_lock = threading.Lock()
    caffeinate: subprocess.Popen[bytes] | None = None
    if not args.no_caffeinate and sys.platform == "darwin":
        caffeinate = subprocess.Popen(
            ["caffeinate", "-i"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def on_interrupt(_signal: int, _frame: Any) -> None:
        if _shutdown.is_set():
            raise KeyboardInterrupt
        tqdm.write(
            "\nStopping submission; in-flight levels may finish before exit."
        )
        _shutdown.set()

    signal.signal(signal.SIGINT, on_interrupt)
    signal.signal(signal.SIGTERM, on_interrupt)

    def execute(task: StudyTask) -> list[dict[str, Any]]:
        if _shutdown.is_set():
            return []
        if task.curriculum:
            with valid_lock:
                known_valid = set(valid_episode_ids)
            records = _execute_curriculum(
                task,
                instructions=instructions,
                args=args,
                results_dir=results_dir,
                launch_session_id=launch_session_id,
                writer=writer,
                valid_episode_ids=known_valid,
            )
            with valid_lock:
                valid_episode_ids.update(known_valid)
            return records
        records = _execute_independent(
            task,
            instructions=instructions,
            args=args,
            results_dir=results_dir,
            launch_session_id=launch_session_id,
            writer=writer,
        )
        with valid_lock:
            for record in records:
                if "error" not in record and record.get("episode_id"):
                    valid_episode_ids.add(str(record["episode_id"]))
        return records

    print(f"\n  Output: {results_dir}")
    print("  Press Ctrl+C to stop after in-flight model calls.\n")
    completed_now = 0
    successes = 0
    errors = 0
    cost = 0.0
    cost_complete = True
    started = time.monotonic()
    futures: dict[Future[list[dict[str, Any]]], StudyTask] = {}
    try:
        with ExitStack() as stack:
            executors = {
                model_id: stack.enter_context(
                    ThreadPoolExecutor(
                        max_workers=workers,
                        thread_name_prefix=f"study-{model_id}",
                    )
                )
                for model_id, workers in model_workers.items()
            }
            for task in tasks:
                futures[
                    executors[task.full_variant_id].submit(execute, task)
                ] = task

            with tqdm(total=remaining, desc="Study", unit="episode") as progress:
                for future in as_completed(futures):
                    task = futures[future]
                    try:
                        records = future.result()
                    except CancelledError:
                        continue
                    except Exception as exc:
                        with valid_lock:
                            task_error = _task_error_record(
                                task, exc, valid_episode_ids
                            )
                        if task_error is None:
                            continue
                        output_key, record = task_error
                        writer.append(output_key, record)
                        records = [record]
                    for record in records:
                        if record.get("skipped"):
                            continue
                        completed_now += 1
                        if "error" in record:
                            errors += 1
                        elif record.get("success"):
                            successes += 1
                        record_cost = record.get("cost_usd")
                        if record_cost is None:
                            if record.get("llm_calls"):
                                cost_complete = False
                        else:
                            cost += float(record_cost)
                        progress.update(1)
                    if _shutdown.is_set():
                        for queued in futures:
                            queued.cancel()
    finally:
        if caffeinate is not None:
            caffeinate.terminate()
            try:
                caffeinate.wait(timeout=5)
            except subprocess.TimeoutExpired:
                caffeinate.kill()

    elapsed_hours = (time.monotonic() - started) / 3600
    cost_text = f"${cost:.2f}" if cost_complete else f"${cost:.2f}+"
    print("\n" + "=" * 72)
    print(
        f"  This launch wrote {completed_now} records in "
        f"{elapsed_hours:.2f} hours"
    )
    print(f"  Successes: {successes}; errors: {errors}; cost: {cost_text}")
    print(f"  Results: {results_dir}")


if __name__ == "__main__":
    main()
