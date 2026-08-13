#!/usr/bin/env python3
"""Work-queue benchmark launcher.

Parallelises at the individual level granularity rather than the job level.
A fixed pool of N workers pulls (model, mode, anon, pack, level) items from
a shared queue, keeping all slots busy until the very end.

Usage:
  python run_queue.py --all                          # all models, all levels, default modes
  python run_queue.py --all --workers 20             # limit to 20 concurrent workers
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
from run_manifest import source_snapshot

SCRIPT_DIR = Path(__file__).parent.resolve()


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


def _parse_provider_workers(values: list[str]) -> dict[str, int]:
    limits: dict[str, int] = {}
    for value in values:
        group, sep, raw_limit = value.partition("=")
        group = group.strip()
        if not sep or not group:
            raise SystemExit(
                f"Invalid --provider-workers value {value!r}; expected GROUP=N"
            )
        try:
            limit = int(raw_limit)
        except ValueError as exc:
            raise SystemExit(
                f"Invalid --provider-workers value {value!r}; N must be an integer"
            ) from exc
        if limit < 1:
            raise SystemExit(
                f"Invalid --provider-workers value {value!r}; N must be positive"
            )
        if group in limits:
            raise SystemExit(f"Duplicate --provider-workers group: {group}")
        limits[group] = limit
    return limits


def _assert_resume_compatible(
    existing: dict[str, Any], current: dict[str, Any]
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
    if old_repo.get("sha") != new_repo.get("sha"):
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

    parser.add_argument("--workers", type=int, default=40,
                        help="Concurrent worker threads (default: 40)")
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
        help="Concurrency cap for one model group; repeatable",
    )

    args = parser.parse_args()
    args.run_id = str(uuid.uuid4())

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
    resume_meta: dict[str, Any] | None = None
    source: dict[str, Any] | None = None

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
            )
            args.run_id = resume_meta.get("run_id", args.run_id)
        elif any(Path(args.run_dir).glob("*.jsonl")):
            raise SystemExit(
                f"Refusing to resume {args.run_dir}: JSONL files exist but meta.json is missing"
            )

    # ── Resume filtering ─────────────────────────────────────────────────────
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
    provider_limits = _parse_provider_workers(args.provider_workers)
    print(f"{'=' * 68}")
    print(f"  GridPonder Work-Queue Benchmark")
    print(f"  Work items:       {len(items)}")
    print(f"  Model variants:   {len(model_variants)}")
    print(f"  Levels:           {total_levels}")
    print(f"  Configurations:   {config_count}")
    print(f"  Workers:          {args.workers}")
    if provider_limits:
        print(
            "  Provider limits:  "
            + ", ".join(f"{group}={limit}" for group, limit in sorted(provider_limits.items()))
        )
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

    run_config = {
        "schema_version": 2,
        "run_id": args.run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "launcher": "run_queue.py",
        "workers": args.workers,
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
        "source": source
        or source_snapshot(SCRIPT_DIR.parent.parent, args.packs_dir),
    }
    if resume_meta:
        run_config["timestamp"] = resume_meta.get(
            "timestamp", run_config["timestamp"]
        )
        run_config["resumed_at"] = datetime.now(timezone.utc).isoformat()
    with open(results_dir / "meta.json", "w") as f:
        json.dump(run_config, f, indent=2)

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
    provider_semaphores = {
        group: threading.BoundedSemaphore(limit)
        for group, limit in provider_limits.items()
    }

    # ── Worker function ──────────────────────────────────────────────────────
    def execute(item: WorkItem) -> tuple[WorkItem, dict]:
        if _shutdown.is_set():
            return item, {"type": "level", "skipped": True}

        try:
            semaphore = provider_semaphores.get(item.concurrency_group)
            if semaphore is None:
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
                )
            else:
                with semaphore:
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

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(execute, item): item for item in items}

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
