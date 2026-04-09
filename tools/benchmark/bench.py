#!/usr/bin/env python3
"""GridPonder AI Benchmark Orchestrator.

Drives the compiled Dart game-loop runner as a subprocess and calls LLMs
(local via Ollama or cloud via API) to play levels. Results are written as
JSONL to results/runs/.

Usage examples:
  python bench.py --suite curated --model qwen3-4b
  python bench.py --all --model gemma4-e2b --model gemma4-e2b-think
  python bench.py --pack number_cells --level nc_001 --model claude-sonnet
  python bench.py --suite curated   # runs all models in models.yaml
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from tqdm import tqdm

from agent_client import call_llm, extract_action

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
RUNNER_BIN = SCRIPT_DIR / "runner" / "runner"
PACKS_DIR = SCRIPT_DIR.parent.parent / "packs"
MODELS_FILE = SCRIPT_DIR / "models.yaml"
SUITE_FILE = SCRIPT_DIR / "suite.yaml"
RESULTS_DIR = SCRIPT_DIR / "results" / "runs"

# Max consecutive rejected actions before forcing a give_up.
MAX_CONSECUTIVE_REJECTIONS = 3


def load_models() -> list[dict]:
    with open(MODELS_FILE) as f:
        return yaml.safe_load(f)["models"]


def load_suite() -> dict[str, list[str]]:
    with open(SUITE_FILE) as f:
        return yaml.safe_load(f)["levels"]


def all_pack_levels() -> dict[str, list[str]]:
    """Discover all levels for all packs by reading game.json files."""
    result: dict[str, list[str]] = {}
    for pack_dir in sorted(PACKS_DIR.iterdir()):
        if not pack_dir.is_dir():
            continue
        game_json = pack_dir / "game.json"
        if not game_json.exists():
            continue
        try:
            game = json.loads(game_json.read_text())
            levels = [
                e["ref"]
                for e in game.get("levelSequence", [])
                if e.get("type") == "level" and "ref" in e
            ]
            if levels:
                result[pack_dir.name] = levels
        except Exception:
            pass
    return result


def expand_model_variants(
    models: list[dict], selected_ids: list[str] | None
) -> list[tuple[dict, dict]]:
    """Return (model, variant) pairs, filtered by selected_ids if given.

    selected_ids can be a model id ("gemma4-e2b") or a full variant id
    ("gemma4-e2b-think"). None means all models and all variants.
    """
    pairs: list[tuple[dict, dict]] = []
    for model in models:
        for variant in model["variants"]:
            full_id = f"{model['id']}{variant.get('suffix', '')}"
            if selected_ids is None or model["id"] in selected_ids or full_id in selected_ids:
                pairs.append((model, variant))
    return pairs


# ── Level runner ───────────────────────────────────────────────────────────────

def run_level(
    pack_id: str,
    level_id: str,
    model: dict,
    variant: dict,
    attempt_multiplier: int,
    total_multiplier: int,
    action_timeout: int | None = None,
) -> dict[str, Any]:
    """Run one level with one model variant. Returns a result dict.

    Args:
        action_timeout: Hard timeout in seconds per individual LLM call.
                        When a call exceeds the limit it is treated as a
                        failed response (give_up).  The model still gets to
                        use its full action budget; only runaway calls are
                        cut short.  None means no per-action limit.
    """
    if not RUNNER_BIN.exists():
        sys.exit(
            f"Runner binary not found: {RUNNER_BIN}\n"
            "Build it first: make benchmark-build"
        )

    cmd = [
        str(RUNNER_BIN),
        "--pack", pack_id,
        "--level", level_id,
        "--packs-dir", str(PACKS_DIR),
        "--attempt-multiplier", str(attempt_multiplier),
        "--total-multiplier", str(total_multiplier),
    ]

    litellm_model: str = model["litellm_model"]
    extra_params: dict = dict(variant.get("params") or {})
    full_model_id = f"{model['id']}{variant.get('suffix', '')}"

    latencies: list[float] = []
    thinking_tokens_total = 0
    output_tokens_total = 0
    resets = 0
    consecutive_rejections = 0
    final_event: dict | None = None

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def send(action: dict) -> None:
        line = json.dumps(action) + "\n"
        proc.stdin.write(line)  # type: ignore[union-attr]
        proc.stdin.flush()  # type: ignore[union-attr]

    try:
        for raw_line in proc.stdout:  # type: ignore[union-attr]
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("event")

            if etype == "state":
                prompt: str = event["prompt"]
                try:
                    response_text, latency_ms, think_tok, out_tok = call_llm(
                        prompt, litellm_model, extra_params,
                        request_timeout=action_timeout,
                    )
                except Exception as exc:
                    # LLM call failed — give_up to avoid hanging.
                    send({"action": "give_up", "memory": f"LLM error: {exc}"})
                    continue

                latencies.append(latency_ms)
                thinking_tokens_total += think_tok
                output_tokens_total += out_tok

                action = extract_action(response_text)
                if action is None:
                    action = {
                        "action": "give_up",
                        "memory": "Could not parse a valid action from response.",
                    }
                send(action)
                consecutive_rejections = 0

            elif etype == "rejected":
                consecutive_rejections += 1
                if consecutive_rejections >= MAX_CONSECUTIVE_REJECTIONS:
                    send({"action": "give_up", "memory": "Too many rejected actions."})
                    consecutive_rejections = 0
                else:
                    # Re-request: runner already re-emitted state, nothing to do.
                    pass

            elif etype == "reset":
                resets += 1

            elif etype in ("won", "lost"):
                final_event = event
                break

    finally:
        try:
            proc.stdin.close()  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    if final_event is None:
        final_event = {
            "event": "lost",
            "actions_total": len(latencies),
            "gold_path_length": 0,
        }

    success = final_event["event"] == "won"
    actions_total: int = final_event.get("actions_total", 0)
    gold_path_length: int = final_event.get("gold_path_length", 0)
    attempts: int = final_event.get("attempts", 1)
    efficiency: float | None = (
        gold_path_length / actions_total
        if (success and actions_total > 0 and gold_path_length > 0)
        else None
    )

    sorted_lat = sorted(latencies)
    n = len(sorted_lat)

    return {
        "type": "level",
        "model_id": full_model_id,
        "pack_id": pack_id,
        "level_id": level_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "local": model.get("local", True),
        "reasoning": variant.get("reasoning", False),
        "success": success,
        "actions_total": actions_total,
        "gold_path_length": gold_path_length,
        "efficiency": efficiency,
        "attempts": attempts,
        "resets": resets,
        "latency_ms": {
            "mean": sum(sorted_lat) / n if n else 0,
            "median": sorted_lat[n // 2] if n else 0,
            "p95": sorted_lat[int(n * 0.95)] if n else 0,
            "total": sum(sorted_lat),
        },
        "thinking_tokens_total": thinking_tokens_total,
        "output_tokens_total": output_tokens_total,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="GridPonder AI Benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # What to run
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--suite", choices=["curated"], help="Run a predefined level suite")
    scope.add_argument("--all", action="store_true", help="Run all packs and all levels")
    scope.add_argument("--pack", help="Run all levels in one pack")
    scope.add_argument("--level", nargs=2, metavar=("PACK", "LEVEL"),
                       help="Run a single level: --level <pack_id> <level_id>")

    # Which models
    parser.add_argument("--model", action="append", dest="models",
                        help="Model or variant ID to run (repeatable); default: all in models.yaml")

    # Limits
    parser.add_argument("--attempt-multiplier", type=int, default=3,
                        help="action_limit_per_attempt = M × gold_path_length (default: 3)")
    parser.add_argument("--total-multiplier", type=int, default=5,
                        help="action_limit = M × gold_path_length, give_up costs 1 (default: 5)")

    # Repetitions
    parser.add_argument("--runs", type=int, default=1,
                        help="Repetitions per (model, level) pair (default: 1)")

    # Per-level hard timeout
    parser.add_argument("--action-timeout", type=int, default=None, metavar="SECONDS",
                        help="Hard timeout per individual LLM call in seconds (default: none). "
                             "Runaway calls are treated as give_up; the model still gets its full action budget.")

    args = parser.parse_args()

    # ── Resolve level scope ──────────────────────────────────────────────────
    if args.level:
        pack_id, level_id = args.level
        levels_by_pack: dict[str, list[str]] = {pack_id: [level_id]}
    elif args.pack:
        all_levels = all_pack_levels()
        if args.pack not in all_levels:
            sys.exit(f"Pack not found: {args.pack}")
        levels_by_pack = {args.pack: all_levels[args.pack]}
    elif args.suite == "curated":
        levels_by_pack = load_suite()
    elif args.all:
        levels_by_pack = all_pack_levels()
    else:
        parser.print_help()
        sys.exit(0)

    # ── Resolve model variants ────────────────────────────────────────────────
    all_models = load_models()
    model_variants = expand_model_variants(all_models, args.models)
    if not model_variants:
        sys.exit(f"No matching model variants found for: {args.models}")

    # ── Build work list ───────────────────────────────────────────────────────
    work: list[tuple[str, str, dict, dict]] = []
    for pack_id, level_ids in levels_by_pack.items():
        for level_id in level_ids:
            for model, variant in model_variants:
                for _ in range(args.runs):
                    work.append((pack_id, level_id, model, variant))

    total = len(work)
    print(f"Benchmark: {total} run(s) — "
          f"{len(model_variants)} model variant(s) × "
          f"{sum(len(v) for v in levels_by_pack.values())} level(s)"
          f"{f' × {args.runs} runs' if args.runs > 1 else ''}")

    # ── Output file per model variant ─────────────────────────────────────────
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    # Group work by model variant so we write one file per variant.
    from collections import defaultdict
    by_variant: dict[str, list[tuple[str, str, dict, dict]]] = defaultdict(list)
    for item in work:
        pack_id, level_id, model, variant = item
        full_id = f"{model['id']}{variant.get('suffix', '')}"
        by_variant[full_id].append(item)

    # ── Run ───────────────────────────────────────────────────────────────────
    for full_id, items in by_variant.items():
        out_file = RESULTS_DIR / f"{ts}_{full_id}.jsonl"
        model_cfg = items[0][2]
        variant_cfg = items[0][3]

        # Write run metadata as first line.
        run_meta = {
            "type": "run_meta",
            "model_id": full_id,
            "display_name": model_cfg["display_name"],
            "litellm_model": model_cfg["litellm_model"],
            "local": model_cfg.get("local", True),
            "reasoning": variant_cfg.get("reasoning", False),
            "attempt_multiplier": args.attempt_multiplier,
            "total_multiplier": args.total_multiplier,
            "runs_per_level": args.runs,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        with open(out_file, "w") as fout:
            fout.write(json.dumps(run_meta) + "\n")

            pbar = tqdm(items, desc=full_id, unit="level")
            for pack_id, level_id, model, variant in pbar:
                pbar.set_postfix(pack=pack_id, level=level_id)
                try:
                    result = run_level(
                        pack_id, level_id, model, variant,
                        args.attempt_multiplier, args.total_multiplier,
                        action_timeout=args.action_timeout,
                    )
                except Exception as exc:
                    result = {
                        "type": "level",
                        "model_id": full_id,
                        "pack_id": pack_id,
                        "level_id": level_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "error": str(exc),
                        "success": False,
                    }
                fout.write(json.dumps(result) + "\n")
                fout.flush()

        print(f"  → {out_file}")

    print(f"\nDone. Run 'python aggregate.py' to update leaderboard.json.")


if __name__ == "__main__":
    main()
