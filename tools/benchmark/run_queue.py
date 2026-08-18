#!/usr/bin/env python3
"""Work-queue benchmark launcher.

Parallelises at the individual level granularity rather than the job level.
Each resolved model variant has an independent executor, so a slow model
cannot occupy another model's worker capacity.

Usage:
  python run_queue.py --all                          # all models, all levels, default modes
  python run_queue.py --all --workers-per-model 10   # 10 workers for every model
  python run_queue.py --all --model br-claude-haiku  # single model
  python run_queue.py --all --dry-run                # preview work items
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import threading
import queue
import time
import uuid
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from dotenv import load_dotenv
from tqdm import tqdm

from bench import (
    run_level,
    load_models,
    expand_model_variants,
    all_pack_levels,
    load_suite,
    load_completed,
    RESULTS_BASE,
)
from live_progress import progress_path, write_progress_snapshot
from run_manifest import source_snapshot

SCRIPT_DIR = Path(__file__).parent.resolve()
SCHEDULER_TYPE = "independent_model_executors"
SOURCE_MIGRATION_PATHS = {
    "engines/python/_models.py",
    "engines/python/test_sliding_blocks.py",
    "tools/benchmark/README.md",
    "tools/benchmark/bench.py",
    "tools/benchmark/live_progress.py",
    "tools/benchmark/live_status.py",
    "tools/benchmark/private_report.py",
    "tools/benchmark/run_queue.py",
    "tools/benchmark/test_live_progress.py",
    "tools/benchmark/test_private_report.py",
    "tools/benchmark/test_run_queue.py",
}


@dataclass
class WorkItem:
    pack_id: str
    level_id: str
    model: dict
    variant: dict
    mode: str
    anon: bool
    input_mode: str
    max_n: int | None
    full_variant_id: str
    connector_model: str
    connector: str
    concurrency_group: str
    output_key: str


def compute_output_key(full_variant_id: str, mode: str, max_n: int | None, anon: bool, input_mode: str = "text") -> str:
    mode_tag = mode
    if mode == "flex-n":
        mode_tag = f"flex-{max_n}" if max_n else "flex-n"
    anon_tag = "_anon" if anon else ""
    input_tag = "" if input_mode == "text" else f"_{input_mode.replace('+', '-')}"
    return f"{full_variant_id}_{mode_tag}{anon_tag}{input_tag}"


def build_work_items(
    model_variants: list[tuple[dict, dict]],
    levels_by_pack: dict[str, list[str]],
    modes: list[str],
    anon_modes: list[str],
    input_modes: list[str],
    max_n: int | None,
) -> list[WorkItem]:
    items: list[WorkItem] = []
    # (mode, anon, input_mode) tuples — anon implies text-only (image carries no
    # anonymisation), so we don't pair anon with image/text+image.
    combos: list[tuple[str, bool, str]] = []
    for mode in modes:
        for inp in input_modes:
            combos.append((mode, False, inp))
        if mode in anon_modes:
            combos.append((mode, True, "text"))

    for model, variant in model_variants:
        full_id = f"{model['id']}{variant.get('suffix', '')}"
        connector_model = model.get("model") or model.get("litellm_model")
        if not connector_model:
            raise ValueError(
                f"Model {model.get('id', '<unknown>')!r} has neither model nor litellm_model"
            )
        connector = model.get("connector", "litellm")
        concurrency_group = model.get("concurrency_group", connector)
        for mode, anon, input_mode in combos:
            okey = compute_output_key(full_id, mode, max_n, anon, input_mode)
            for pack_id, level_ids in levels_by_pack.items():
                for level_id in level_ids:
                    items.append(WorkItem(
                        pack_id=pack_id,
                        level_id=level_id,
                        model=model,
                        variant=variant,
                        mode=mode,
                        anon=anon,
                        input_mode=input_mode,
                        max_n=max_n,
                        full_variant_id=full_id,
                        connector_model=connector_model,
                        connector=connector,
                        concurrency_group=concurrency_group,
                        output_key=okey,
                    ))
    return items


def interleave_by_model(items: list[WorkItem]) -> list[WorkItem]:
    buckets: dict[str, list[WorkItem]] = defaultdict(list)
    for item in items:
        buckets[item.connector_model].append(item)
    for key in buckets:
        buckets[key].sort(key=lambda i: (i.pack_id, i.level_id, i.mode, i.anon))
    result: list[WorkItem] = []
    iters = [iter(b) for b in buckets.values()]
    while iters:
        next_round = []
        for it in iters:
            val = next(it, None)
            if val is not None:
                result.append(val)
                next_round.append(it)
        iters = next_round
    return result


def filter_completed(
    items: list[WorkItem],
    scan_dir: Path | None = None,
) -> list[WorkItem]:
    cache: dict[tuple[str, bool, str], set[tuple[str, str, str]]] = {}
    filtered: list[WorkItem] = []
    for item in items:
        key = (item.mode, item.anon, item.input_mode)
        if key not in cache:
            cache[key] = load_completed(
                RESULTS_BASE, item.mode, item.anon,
                scan_dir=scan_dir, input_mode=item.input_mode,
            )
        done = cache[key]
        if (item.full_variant_id, item.pack_id, item.level_id) not in done:
            filtered.append(item)
    return filtered


def build_run_meta(item: WorkItem, args: argparse.Namespace) -> dict:
    return {
        "type": "run_meta",
        "model_id": item.full_variant_id,
        "display_name": item.model["display_name"],
        "litellm_model": item.model.get("litellm_model"),
        "connector": item.connector,
        "model": item.connector_model,
        "concurrency_group": item.concurrency_group,
        "model_params": item.variant.get("params") or {},
        "pricing": item.model.get("pricing"),
        "local": item.model.get("local", True),
        "reasoning": item.variant.get("reasoning", False),
        "inference_mode": item.mode,
        "anon": item.anon,
        "input_mode": item.input_mode,
        "attempt_multiplier": args.attempt_multiplier,
        "total_multiplier": args.total_multiplier,
        "runs_per_level": 1,
        "action_timeout": args.action_timeout,
        "run_id": args.run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def model_run_specs(
    model_variants: list[tuple[dict, dict]],
) -> list[dict[str, Any]]:
    """Return the connector-relevant model configuration for provenance."""
    return [
        {
            "model_id": f"{model['id']}{variant.get('suffix', '')}",
            "connector": model.get("connector", "litellm"),
            "model": model.get("model") or model.get("litellm_model"),
            "concurrency_group": model.get(
                "concurrency_group", model.get("connector", "litellm")
            ),
            "params": variant.get("params") or {},
            "pricing": model.get("pricing"),
        }
        for model, variant in model_variants
    ]


def writer_loop(
    q: queue.Queue,
    results_dir: Path,
    meta_by_key: dict[str, dict],
) -> None:
    handles: dict[str, Any] = {}
    try:
        while True:
            item = q.get()
            if item is None:
                break
            output_key, record = item
            if output_key not in handles:
                path = results_dir / f"{output_key}.jsonl"
                fh = open(path, "a")
                if path.stat().st_size == 0 and output_key in meta_by_key:
                    fh.write(json.dumps(meta_by_key[output_key]) + "\n")
                    fh.flush()
                handles[output_key] = fh
            fh = handles[output_key]
            fh.write(json.dumps(record) + "\n")
            fh.flush()
    finally:
        for fh in handles.values():
            fh.close()


_shutdown = threading.Event()


def _parse_worker_limits(values: list[str], option: str) -> dict[str, int]:
    limits: dict[str, int] = {}
    for value in values:
        key, sep, raw_limit = value.partition("=")
        key = key.strip()
        if not sep or not key:
            raise SystemExit(
                f"Invalid {option} value {value!r}; expected NAME=N"
            )
        try:
            limit = int(raw_limit)
        except ValueError as exc:
            raise SystemExit(
                f"Invalid {option} value {value!r}; N must be an integer"
            ) from exc
        if limit < 1:
            raise SystemExit(
                f"Invalid {option} value {value!r}; N must be positive"
            )
        if key in limits:
            raise SystemExit(f"Duplicate {option} name: {key}")
        limits[key] = limit
    return limits


def _parse_provider_workers(values: list[str]) -> dict[str, int]:
    return _parse_worker_limits(values, "--provider-workers")


def _parse_model_workers(values: list[str]) -> dict[str, int]:
    return _parse_worker_limits(values, "--model-workers")


def _resolve_model_workers(
    model_specs: list[dict[str, Any]],
    workers_per_model: int | None,
    model_overrides: dict[str, int],
    legacy_workers: int | None = None,
    legacy_provider_limits: dict[str, int] | None = None,
) -> dict[str, int]:
    model_ids = [str(spec["model_id"]) for spec in model_specs]
    unknown = sorted(set(model_overrides) - set(model_ids))
    if unknown:
        raise SystemExit(
            "Unknown --model-workers model ID(s): " + ", ".join(unknown)
        )

    if workers_per_model is not None and workers_per_model < 1:
        raise SystemExit("--workers-per-model must be positive")
    if legacy_workers is not None and legacy_workers < 1:
        raise SystemExit("--workers must be positive")

    default_limit = workers_per_model
    if default_limit is None:
        default_limit = (
            max(1, legacy_workers // max(len(model_ids), 1))
            if legacy_workers is not None
            else 10
        )

    provider_limits = legacy_provider_limits or {}
    limits: dict[str, int] = {}
    for spec in model_specs:
        model_id = str(spec["model_id"])
        group = str(spec.get("concurrency_group", ""))
        legacy_limit = provider_limits.get(group)
        limits[model_id] = model_overrides.get(
            model_id,
            (
                legacy_limit
                if workers_per_model is None and legacy_limit
                else default_limit
            ),
        )
    return limits


@contextmanager
def independent_model_futures(
    items: list[WorkItem],
    execute: Callable[[WorkItem], tuple[WorkItem, dict]],
    model_workers: dict[str, int],
) -> Iterator[dict[Future[tuple[WorkItem, dict]], WorkItem]]:
    """Submit work to dedicated executors keyed by resolved model variant."""
    with ExitStack() as stack:
        executors = {
            model_id: stack.enter_context(
                ThreadPoolExecutor(
                    max_workers=limit,
                    thread_name_prefix=f"benchmark-{model_id}",
                )
            )
            for model_id, limit in model_workers.items()
        }
        futures: dict[Future[tuple[WorkItem, dict]], WorkItem] = {}
        for item in items:
            executor = executors.get(item.full_variant_id)
            if executor is None:
                raise RuntimeError(
                    f"No model executor configured for {item.full_variant_id}"
                )
            futures[executor.submit(execute, item)] = item
        yield futures


def _source_sha(source: dict[str, Any] | None) -> str | None:
    return ((source or {}).get("repository") or {}).get("sha")


def _scheduler_from_meta(meta: dict[str, Any]) -> dict[str, Any]:
    scheduler = meta.get("scheduler")
    if scheduler:
        return dict(scheduler)
    return {
        "type": "shared_executor_with_group_semaphores",
        "workers": meta.get("workers"),
        "provider_workers": meta.get("provider_workers") or {},
    }


def _unsupported_source_migration_paths(paths: list[str]) -> list[str]:
    return sorted(set(paths) - SOURCE_MIGRATION_PATHS)


def _assert_source_migration(
    repo_root: Path,
    old_sha: str,
    new_sha: str,
) -> list[str]:
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", old_sha, new_sha],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0:
        raise SystemExit(
            "Refusing source migration: the new source is not a descendant "
            f"of the recorded source {old_sha}"
        )

    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{old_sha}..{new_sha}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if diff.returncode != 0:
        raise SystemExit(
            "Unable to verify source migration diff: " + diff.stderr.strip()
        )
    changed_paths = [line for line in diff.stdout.splitlines() if line]
    unsupported = _unsupported_source_migration_paths(changed_paths)
    if unsupported:
        raise SystemExit(
            "Refusing source migration; unreviewed paths changed: "
            + ", ".join(unsupported)
        )
    return changed_paths


def _assert_resume_compatible(
    existing: dict[str, Any],
    current: dict[str, Any],
    *,
    allow_source_change: bool = False,
) -> None:
    fields = [
        "modes",
        "anon_modes",
        "input_modes",
        "model_variants",
        "model_specs",
        "action_timeout",
        "attempt_multiplier",
        "total_multiplier",
        "flex_max_n",
        "flex_penalty",
        "runner",
        "levels_by_pack",
    ]
    mismatches = [
        field for field in fields if existing.get(field) != current.get(field)
    ]
    old_source = existing.get("source") or {}
    new_source = current.get("source") or {}
    if old_source.get("packs_digest") != new_source.get("packs_digest"):
        mismatches.append("source.packs_digest")
    old_repo = old_source.get("repository") or {}
    new_repo = new_source.get("repository") or {}
    if (
        old_repo.get("sha") != new_repo.get("sha")
        and not allow_source_change
    ):
        mismatches.append("source.repository.sha")
    if old_repo.get("dirty") or new_repo.get("dirty"):
        mismatches.append("source.repository.dirty")
    if mismatches:
        raise SystemExit(
            "Refusing to resume an incompatible run; changed fields: "
            + ", ".join(mismatches)
        )


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="GridPonder Work-Queue Benchmark Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--suite", choices=["curated"], help="Run curated level suite")
    scope.add_argument("--all", action="store_true", help="Run all packs and all levels")
    scope.add_argument("--pack", help="Run all levels in one pack")
    scope.add_argument(
        "--level",
        nargs=2,
        metavar=("PACK", "LEVEL"),
        help="Run one level (useful for an end-to-end canary)",
    )

    parser.add_argument("--model", action="append", dest="models",
                        help="Model or variant ID (repeatable; default: all)")
    parser.add_argument("--modes", nargs="+", default=["single", "flex-n", "full"],
                        help="Inference modes to run (default: single flex-n full)")
    parser.add_argument("--anon-modes", nargs="+", default=["single", "flex-n"],
                        help="Modes that also run with --anon (default: single flex-n)")
    parser.add_argument("--input-modes", nargs="+",
                        choices=["text", "image", "text+image"],
                        default=["text"],
                        help="Input modalities to evaluate. text is the existing baseline; "
                             "image and text+image require vision-capable models. "
                             "Anon variants are only ever run with text. (default: text)")

    parser.add_argument(
        "--workers-per-model",
        type=int,
        default=None,
        help="Workers in each independent model queue (default: 10)",
    )
    parser.add_argument(
        "--model-workers",
        action="append",
        default=[],
        metavar="MODEL=N",
        help="Override workers for one resolved model variant; repeatable",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Deprecated legacy total; distributed across model queues",
    )
    parser.add_argument("--action-timeout", type=int, default=120,
                        help="Per-LLM-call timeout in seconds (default: 120)")
    parser.add_argument("--attempt-multiplier", type=int, default=2)
    parser.add_argument("--total-multiplier", type=int, default=3)
    parser.add_argument("--flex-max-n", type=int, default=None,
                        help="Max actions per call for flex-n mode (default: unlimited)")
    parser.add_argument("--flex-penalty", type=float, default=0.5)
    parser.add_argument("--runner", choices=["auto", "dart", "python"], default="auto")
    parser.add_argument("--no-resume", action="store_true",
                        help="Don't skip already-completed levels")
    parser.add_argument("--run-dir", type=str, default=None,
                        help="Output directory (default: new timestamped dir)")
    parser.add_argument("--include-local", action="store_true",
                        help="Include local (Ollama) models (default: API-only)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print work items without executing")
    parser.add_argument(
        "--packs-dir",
        type=Path,
        default=Path(__file__).parent.parent.parent / "packs",
        help="Pack root to benchmark",
    )
    parser.add_argument(
        "--provider-workers",
        action="append",
        default=[],
        metavar="GROUP=N",
        help="Deprecated legacy group limit; mapped to each matching model queue",
    )
    parser.add_argument(
        "--allow-source-migration",
        "--allow-scheduler-migration",
        dest="allow_source_migration",
        action="store_true",
        help="Allow a clean, reviewed source change when resuming",
    )
    parser.add_argument(
        "--source-migration-reason",
        "--scheduler-migration-reason",
        dest="source_migration_reason",
        help="Reason recorded when --allow-source-migration changes source SHA",
    )

    args = parser.parse_args()
    args.run_id = str(uuid.uuid4())
    launch_session_id = str(uuid.uuid4())

    # ── Resolve levels ───────────────────────────────────────────────────────
    if args.suite == "curated":
        levels_by_pack = load_suite()
    elif args.all:
        levels_by_pack = all_pack_levels(args.packs_dir)
    elif args.pack:
        all_levels = all_pack_levels(args.packs_dir)
        if args.pack not in all_levels:
            sys.exit(f"Pack not found: {args.pack}")
        levels_by_pack = {args.pack: all_levels[args.pack]}
    elif args.level:
        pack_id, level_id = args.level
        all_levels = all_pack_levels(args.packs_dir)
        if pack_id not in all_levels:
            sys.exit(f"Pack not found: {pack_id}")
        if level_id not in all_levels[pack_id]:
            sys.exit(f"Level not found: {pack_id}/{level_id}")
        levels_by_pack = {pack_id: [level_id]}
    else:
        parser.print_help()
        sys.exit(0)

    total_levels = sum(len(v) for v in levels_by_pack.values())

    # ── Resolve model variants ───────────────────────────────────────────────
    all_models = load_models()
    if not args.include_local:
        all_models = [m for m in all_models if not m.get("local", True)]
    model_variants = expand_model_variants(all_models, args.models)
    if not model_variants:
        sys.exit(f"No matching model variants found for: {args.models}")

    # ── Build work items ─────────────────────────────────────────────────────
    max_n = args.flex_max_n if "flex-n" in args.modes else None
    items = build_work_items(
        model_variants, levels_by_pack,
        args.modes, args.anon_modes, args.input_modes, max_n,
    )
    planned_work_items = len(items)
    resolved_variants = [
        f"{model['id']}{variant.get('suffix', '')}"
        for model, variant in model_variants
    ]
    resolved_model_specs = model_run_specs(model_variants)
    provider_limits = _parse_provider_workers(args.provider_workers)
    model_worker_overrides = _parse_model_workers(args.model_workers)
    model_workers = _resolve_model_workers(
        resolved_model_specs,
        args.workers_per_model,
        model_worker_overrides,
        legacy_workers=args.workers,
        legacy_provider_limits=provider_limits,
    )
    scheduler_config = {
        "type": SCHEDULER_TYPE,
        "workers_by_model": model_workers,
        "total_capacity": sum(model_workers.values()),
    }
    resume_meta: dict[str, Any] | None = None
    source: dict[str, Any] | None = None
    source_migration: dict[str, Any] | None = None

    if args.run_dir:
        meta_path = Path(args.run_dir) / "meta.json"
        if meta_path.is_file():
            resume_meta = json.loads(meta_path.read_text())
            source = source_snapshot(SCRIPT_DIR.parent.parent, args.packs_dir)
            _assert_resume_compatible(
                resume_meta,
                {
                    "modes": args.modes,
                    "anon_modes": args.anon_modes,
                    "input_modes": args.input_modes,
                    "model_variants": resolved_variants,
                    "model_specs": resolved_model_specs,
                    "action_timeout": args.action_timeout,
                    "attempt_multiplier": args.attempt_multiplier,
                    "total_multiplier": args.total_multiplier,
                    "flex_max_n": args.flex_max_n,
                    "flex_penalty": args.flex_penalty,
                    "runner": args.runner,
                    "levels_by_pack": levels_by_pack,
                    "source": source,
                },
                allow_source_change=args.allow_source_migration,
            )
            old_sha = _source_sha(resume_meta.get("source"))
            new_sha = _source_sha(source)
            if old_sha != new_sha:
                if not args.allow_source_migration:
                    raise SystemExit(
                        "Refusing to resume after a source change without "
                        "--allow-source-migration"
                    )
                if not args.source_migration_reason:
                    raise SystemExit(
                        "--source-migration-reason is required when the "
                        "recorded source SHA changes"
                    )
                if not old_sha or not new_sha:
                    raise SystemExit(
                        "Cannot verify source migration without both source SHAs"
                    )
                changed_paths = _assert_source_migration(
                    SCRIPT_DIR.parent.parent,
                    old_sha,
                    new_sha,
                )
                source_migration = {
                    "from_source_sha": old_sha,
                    "to_source_sha": new_sha,
                    "reason": args.source_migration_reason,
                    "changed_paths": changed_paths,
                    "from_scheduler": _scheduler_from_meta(resume_meta),
                    "to_scheduler": scheduler_config,
                }
            args.run_id = resume_meta.get("run_id", args.run_id)
        elif any(Path(args.run_dir).glob("*.jsonl")):
            raise SystemExit(
                f"Refusing to resume {args.run_dir}: JSONL files exist but meta.json is missing"
            )

    # ── Resume filtering ─────────────────────────────────────────────────────
    skipped = 0
    if not args.no_resume and args.run_dir:
        before = len(items)
        items = filter_completed(items, scan_dir=Path(args.run_dir))
        skipped = before - len(items)
        if skipped:
            print(f"  Resume: skipping {skipped} already-completed, {len(items)} remaining.")

    if not items:
        print("Nothing to do — all levels already completed.")
        sys.exit(0)

    # ── Interleave ───────────────────────────────────────────────────────────
    items = interleave_by_model(items)

    # ── Summary ──────────────────────────────────────────────────────────────
    config_count = len(args.modes) * len(args.input_modes) + sum(
        1 for mode in args.modes if mode in args.anon_modes
    )
    print(f"{'=' * 68}")
    print(f"  GridPonder Work-Queue Benchmark")
    print(f"  Work items:       {len(items)}")
    print(f"  Model variants:   {len(model_variants)}")
    print(f"  Levels:           {total_levels}")
    print(f"  Configurations:   {config_count}")
    print(f"  Scheduler:        independent model queues")
    print(
        "  Model workers:    "
        + ", ".join(
            f"{model_id}={limit}"
            for model_id, limit in sorted(model_workers.items())
        )
    )
    print(f"  Total capacity:   {sum(model_workers.values())}")
    print(f"  Timeout:          {args.action_timeout}s per LLM call")
    print(f"{'=' * 68}")

    if args.dry_run:
        counts: dict[str, int] = defaultdict(int)
        for item in items:
            counts[item.output_key] += 1
        for key in sorted(counts):
            print(f"  {key}: {counts[key]} levels")
        print(f"\n  Total: {len(items)} work items (dry run)")
        sys.exit(0)

    # ── Output directory ─────────────────────────────────────────────────────
    if args.run_dir:
        results_dir = Path(args.run_dir)
    else:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        results_dir = RESULTS_BASE / ts
    results_dir.mkdir(parents=True, exist_ok=True)

    resumed_at = datetime.now(timezone.utc).isoformat() if resume_meta else None
    current_source = source or source_snapshot(
        SCRIPT_DIR.parent.parent, args.packs_dir
    )
    run_config = {
        "schema_version": 3,
        "run_id": args.run_id,
        "launch_session_id": launch_session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "launcher": "run_queue.py",
        "workers": sum(model_workers.values()),
        "workers_per_model": args.workers_per_model,
        "model_workers": model_workers,
        "scheduler": scheduler_config,
        "modes": args.modes,
        "anon_modes": args.anon_modes,
        "input_modes": args.input_modes,
        "models": args.models,
        "model_variants": resolved_variants,
        "model_specs": resolved_model_specs,
        "packs_dir": str(args.packs_dir.resolve()),
        "provider_workers": provider_limits,
        "action_timeout": args.action_timeout,
        "attempt_multiplier": args.attempt_multiplier,
        "total_multiplier": args.total_multiplier,
        "flex_max_n": args.flex_max_n,
        "flex_penalty": args.flex_penalty,
        "runner": args.runner,
        "total_work_items": planned_work_items,
        "levels_by_pack": levels_by_pack,
        "source": current_source,
    }
    if not resume_meta:
        run_config["source_history"] = [current_source]
        run_config["scheduler_history"] = [
            {
                **scheduler_config,
                "source_sha": _source_sha(current_source),
                "active_from": run_config["timestamp"],
            }
        ]
    if resume_meta:
        run_config["timestamp"] = resume_meta.get(
            "timestamp", run_config["timestamp"]
        )
        run_config["resumed_at"] = resumed_at

        source_history = list(resume_meta.get("source_history") or [])
        if not source_history and resume_meta.get("source"):
            source_history.append(resume_meta["source"])
        if not source_history or _source_sha(source_history[-1]) != _source_sha(
            current_source
        ):
            source_history.append(current_source)
        run_config["source_history"] = source_history

        scheduler_history = list(resume_meta.get("scheduler_history") or [])
        if not scheduler_history:
            initial_scheduler = _scheduler_from_meta(resume_meta)
            initial_scheduler["source_sha"] = _source_sha(resume_meta.get("source"))
            initial_scheduler["active_from"] = resume_meta.get("timestamp")
            scheduler_history.append(initial_scheduler)
        if scheduler_history[-1].get("type") != scheduler_config["type"] or (
            scheduler_history[-1].get("workers_by_model")
            != scheduler_config["workers_by_model"]
        ):
            scheduler_entry = {
                **scheduler_config,
                "source_sha": _source_sha(current_source),
                "active_from": resumed_at,
            }
            if source_migration:
                scheduler_entry["reason"] = source_migration["reason"]
            scheduler_history.append(scheduler_entry)
        run_config["scheduler_history"] = scheduler_history

        resume_history = list(resume_meta.get("resume_history") or [])
        resume_entry = {
            "resumed_at": resumed_at,
            "launch_session_id": launch_session_id,
            "completed_before_resume": skipped,
            "remaining_before_resume": len(items),
            "source_sha": _source_sha(current_source),
            "scheduler": scheduler_config,
        }
        if source_migration:
            resume_entry["source_migration"] = source_migration
        resume_history.append(resume_entry)
        run_config["resume_history"] = resume_history

    meta_path = results_dir / "meta.json"
    meta_tmp_path = results_dir / "meta.json.tmp"
    meta_tmp_path.write_text(json.dumps(run_config, indent=2) + "\n")
    meta_tmp_path.replace(meta_path)

    # ── Pre-compute run_meta for each output key ─────────────────────────────
    meta_by_key: dict[str, dict] = {}
    for item in items:
        if item.output_key not in meta_by_key:
            meta_by_key[item.output_key] = build_run_meta(item, args)

    # ── Writer thread ────────────────────────────────────────────────────────
    writer_q: queue.Queue = queue.Queue()
    writer_thread = threading.Thread(
        target=writer_loop, args=(writer_q, results_dir, meta_by_key), daemon=True,
    )
    writer_thread.start()

    # ── Caffeinate ───────────────────────────────────────────────────────────
    caffeinate = subprocess.Popen(
        ["caffeinate", "-i"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # ── Signal handling ──────────────────────────────────────────────────────
    def on_sigint(sig, frame):
        if not _shutdown.is_set():
            tqdm.write("\nShutting down gracefully — waiting for in-flight levels to finish...")
            _shutdown.set()
        else:
            tqdm.write("Force quit.")
            sys.exit(1)
    signal.signal(signal.SIGINT, on_sigint)

    # ── Stats tracking ───────────────────────────────────────────────────────
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"done": 0, "won": 0, "failed": 0})
    stats_lock = threading.Lock()
    # ── Worker function ──────────────────────────────────────────────────────
    def execute(item: WorkItem) -> tuple[WorkItem, dict]:
        if _shutdown.is_set():
            return item, {"type": "level", "skipped": True}

        snapshot_path = progress_path(
            results_dir,
            item.output_key,
            item.pack_id,
            item.level_id,
        )
        progress_warning_emitted = False

        def on_progress(snapshot: dict[str, Any]) -> None:
            nonlocal progress_warning_emitted
            try:
                write_progress_snapshot(
                    snapshot_path,
                    {
                        **snapshot,
                        "launch_session_id": launch_session_id,
                        "output_key": item.output_key,
                    },
                )
            except Exception as exc:
                if not progress_warning_emitted:
                    tqdm.write(
                        f"Live progress write failed for "
                        f"{item.pack_id}/{item.level_id}: {exc}"
                    )
                    progress_warning_emitted = True

        try:
            result = run_level(
                item.pack_id, item.level_id,
                item.model, item.variant,
                args.attempt_multiplier, args.total_multiplier,
                action_timeout=args.action_timeout,
                mode=item.mode,
                step_size=3,
                max_n=item.max_n,
                flex_penalty=args.flex_penalty,
                anon=item.anon,
                runner=args.runner,
                input_mode=item.input_mode,
                packs_dir=args.packs_dir,
                progress_callback=on_progress,
            )
        except Exception as exc:
            result = {
                "type": "level",
                "model_id": item.full_variant_id,
                "pack_id": item.pack_id,
                "level_id": item.level_id,
                "inference_mode": item.mode,
                "anon": item.anon,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
                "success": False,
            }
            on_progress({
                "status": "error",
                "phase": "error",
                "model_id": item.full_variant_id,
                "pack_id": item.pack_id,
                "level_id": item.level_id,
                "inference_mode": item.mode,
                "anon": item.anon,
                "input_mode": item.input_mode,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "error_type": type(exc).__name__,
            })

        if not result.get("skipped"):
            writer_q.put((item.output_key, result))

        return item, result

    # ── Execute ──────────────────────────────────────────────────────────────
    print(f"\n  Output: {results_dir}")
    print(f"  Press Ctrl+C to stop gracefully.\n")

    completed = 0
    total_cost = 0.0
    total_cost_known = True
    t_start = time.monotonic()

    with independent_model_futures(items, execute, model_workers) as futures:
        pbar = tqdm(total=len(items), desc="Benchmark", unit="lvl")
        for future in as_completed(futures):
            item, result = future.result()

            if result.get("skipped"):
                pbar.update(1)
                continue

            success = result.get("success", False)
            cost = result.get("cost_usd")
            if cost is None:
                if result.get("llm_calls", 0):
                    total_cost_known = False
            else:
                total_cost += cost

            with stats_lock:
                s = stats[item.output_key]
                s["done"] += 1
                if success:
                    s["won"] += 1
                else:
                    s["failed"] += 1

            completed += 1
            pbar.update(1)

            status = "ok  " if success else "FAIL"
            actions = result.get("actions_total", "?")
            gold = result.get("gold_path_length", "?")
            lat = result.get("latency_ms", {})
            lat_total = lat.get("total")
            total_str = f"{lat_total / 1000:5.1f}s" if lat_total is not None else "    ?s"
            cost_str = f"${cost:.3f}" if cost is not None else "    n/a"
            level_col = f"{item.pack_id}/{item.level_id}"
            tqdm.write(
                f"  {status}  {item.output_key:45s}  {level_col:28s}"
                f"  act={actions:>3}/{gold:<3}  {cost_str}  {total_str}"
            )

        pbar.close()

    # ── Shutdown ─────────────────────────────────────────────────────────────
    writer_q.put(None)
    writer_thread.join(timeout=30)
    caffeinate.terminate()

    elapsed = time.monotonic() - t_start
    elapsed_h = elapsed / 3600

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'=' * 68}")
    print(f"  Completed: {completed}/{len(items)} levels in {elapsed_h:.1f}h")
    cost_summary = f"${total_cost:.2f}" if total_cost_known else "unavailable"
    print(f"  Total cost: {cost_summary}")
    print(f"")

    print(f"  {'Job':45s}  {'Done':>5s}  {'Won':>4s}  {'Rate':>5s}")
    print(f"  {'-'*45}  {'-'*5}  {'-'*4}  {'-'*5}")
    for key in sorted(stats):
        s = stats[key]
        pct = s["won"] * 100 // s["done"] if s["done"] > 0 else 0
        print(f"  {key:45s}  {s['done']:5d}  {s['won']:4d}  {pct:3d}%")

    print(f"\n  Results: {results_dir}")
    print(f"  Run 'python aggregate.py' to update leaderboard.")


if __name__ == "__main__":
    main()
