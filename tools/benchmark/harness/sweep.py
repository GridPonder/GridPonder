#!/usr/bin/env python3
"""Play a set of levels with one agent and collect the results.

supervisor.py is one level, one agent, one process. This is the loop around it:
it reads the level list, model and concurrency out of harness.yaml, runs each
session in its own sandbox, and writes a single results file that report.py
turns into a PDF.

Each session is a separate supervisor process. That costs a little startup time
per level and buys isolation of the useful kind: a level that hangs, crashes,
or leaves a wedged socket cannot take the sweep down with it, and its result is
recorded as a failure rather than lost.

    python tools/benchmark/harness/sweep.py --agent baseline --out tmp/run
    python tools/benchmark/harness/sweep.py --agent claude --model haiku --out tmp/run
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
import time
from pathlib import Path

_HARNESS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _HARNESS_DIR.parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.benchmark.harness import agents, isolation  # noqa: E402
from tools.benchmark.harness.supervisor import load_config  # noqa: E402

SUPERVISOR = _HARNESS_DIR / "supervisor.py"


def resolve_levels(packs_dir: Path, spec: dict) -> list[tuple[str, str]]:
    """Expand the config's level spec into concrete (pack, level) pairs.

    `pack: all` sweeps the whole pack in sorted order. A level named
    explicitly but missing is an error rather than a silent skip: a sweep that
    quietly covers less than it was asked to is worse than one that stops.
    """
    pairs: list[tuple[str, str]] = []
    for pack, levels in (spec or {}).items():
        level_dir = packs_dir / pack / "levels"
        if not level_dir.is_dir():
            raise SystemExit(f"pack {pack!r} has no levels/ under {packs_dir}")
        if levels == "all" or levels is None:
            pairs += [(pack, p.stem) for p in sorted(level_dir.glob("*.json"))]
            continue
        for level in levels:
            if not (level_dir / f"{level}.json").is_file():
                raise SystemExit(f"level {pack}/{level} not found")
            pairs.append((pack, level))
    return pairs


def run_one(job: dict) -> dict:
    """Run one supervisor session and return its result dict."""
    argv = [
        sys.executable, str(SUPERVISOR),
        "--pack", job["pack"], "--level", job["level"],
        "--packs-dir", job["packs_dir"],
        "--sandbox", job["sandbox"],
        "--result", job["result_path"],
        "--config", job["config"],
        "--agent", job["agent"],
        "--isolation", job["isolation"],
        "--max-attempts", str(job["max_attempts"]),
        "--timeout", str(job["timeout"]),
    ]
    if job.get("transcript"):
        argv += ["--transcript", job["transcript"]]
    if job.get("model"):
        argv += ["--model", job["model"]]
    argv += ["--seed", str(job["repeat"])]
    if job.get("anon"):
        argv.append("--anon")

    started = time.monotonic()
    proc = subprocess.run(
        argv, capture_output=True, text=True,
        # A supervisor that ignores its own timeout still must not wedge the
        # sweep, so allow it a margin and then take it out.
        timeout=job["timeout"] + 120,
    )
    elapsed = time.monotonic() - started

    result_file = Path(job["result_path"])
    if proc.returncode != 0 or not result_file.is_file():
        # Record the failure as a run. Dropping it would silently shrink the
        # denominator and make the agent look better than it did.
        return {
            "pack_id": job["pack"], "level_id": job["level"],
            "repeat": job["repeat"], "solved": False, "error": (
                proc.stderr.strip()[-2000:] or f"exit {proc.returncode}"
            ),
            "tier": "error", "wall_seconds": round(elapsed, 2),
        }
    result = json.loads(result_file.read_text())
    result["repeat"] = job["repeat"]
    if job.get("transcript"):
        result["transcript"] = job["transcript"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep one agent over many levels")
    parser.add_argument("--config", default=str(_HARNESS_DIR / "harness.yaml"))
    parser.add_argument("--packs-dir", required=True)
    parser.add_argument("--out", required=True, help="Directory for sandboxes and results")
    parser.add_argument("--tier", default="tier1", help="Config block to read")
    parser.add_argument("--agent", default=None,
                        help=f"Override the tier's harness: {', '.join(agents.known_agents())}")
    parser.add_argument("--model", default=None, help="Override the tier's model")
    parser.add_argument("--repeats", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--isolation", choices=list(isolation.MODES), default=None)
    parser.add_argument("--max-attempts", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--anon", action="store_true", default=False)
    parser.add_argument("--pack", default=None, help="Sweep one pack, ignoring the config list")
    parser.add_argument("--level", action="append", default=None,
                        help="Sweep specific levels (repeatable); needs --pack")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    tier = config.get(args.tier, {})
    run_cfg = config.get("run", {})

    agent = args.agent or tier.get("harness")
    if not agent:
        parser.error(f"no agent: pass --agent or set {args.tier}.harness in the config")
    model = args.model if args.model is not None else tier.get("model")
    # A tier names a model even when the agent is a local script. Drop it
    # rather than stamping the config's model onto a run that never saw one.
    if not agents.build(agent).uses_model:
        model = None
    repeats = args.repeats if args.repeats is not None else int(tier.get("repeats", 1))
    concurrency = args.concurrency or int(config.get("concurrency", 1))
    iso = args.isolation or run_cfg.get("isolation", "bwrap")
    max_attempts = (args.max_attempts if args.max_attempts is not None
                    else int(run_cfg.get("max_attempts", 1)))
    timeout = args.timeout if args.timeout is not None else float(run_cfg.get("timeout", 900))

    packs_dir = Path(args.packs_dir).resolve()
    if args.pack:
        level_spec = {args.pack: args.level or "all"}
    else:
        level_spec = tier.get("levels") or {}
        if not level_spec:
            parser.error(
                f"no levels: pass --pack, or set {args.tier}.levels in the config"
            )
    pairs = resolve_levels(packs_dir, level_spec)

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    if iso != "none" and not isolation.available(iso):
        raise SystemExit(
            f"isolation {iso!r} unavailable on this host; install bubblewrap, "
            f"or pass --isolation none and treat the scores as unverified"
        )

    jobs = []
    for pack, level in pairs:
        for repeat in range(repeats):
            tag = f"{pack}_{level}_r{repeat}"
            jobs.append({
                "pack": pack, "level": level, "repeat": repeat,
                "packs_dir": str(packs_dir),
                "sandbox": str(out / "sandboxes" / tag),
                "result_path": str(out / "results" / f"{tag}.json"),
                "transcript": str(out / "transcripts" / f"{tag}.jsonl"),
                "config": args.config, "agent": agent, "model": model,
                "isolation": iso, "max_attempts": max_attempts,
                "timeout": timeout, "anon": args.anon,
            })
    (out / "results").mkdir(exist_ok=True)
    (out / "transcripts").mkdir(exist_ok=True)
    (out / "sandboxes").mkdir(exist_ok=True)

    print(f"[sweep] {len(jobs)} session(s): {len(pairs)} level(s) x {repeats} "
          f"repeat(s), agent={agent} model={model or '-'} isolation={iso} "
          f"max_attempts={max_attempts} concurrency={concurrency}")

    started = time.monotonic()
    runs: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(run_one, job): job for job in jobs}
        for done in concurrent.futures.as_completed(futures):
            job = futures[done]
            try:
                result = done.result()
            except Exception as exc:  # noqa: BLE001 - a crash is a run outcome
                result = {
                    "pack_id": job["pack"], "level_id": job["level"],
                    "repeat": job["repeat"], "solved": False,
                    "error": f"{type(exc).__name__}: {exc}", "tier": "error",
                }
            runs.append(result)
            mark = "✓" if result.get("solved") else "·"
            print(f"  {mark} {result['pack_id']}/{result['level_id']} "
                  f"r{result['repeat']}: {result.get('tier', '?')}"
                  f" attempts={result.get('attempts', '-')}"
                  f" losses={result.get('losses', '-')}"
                  f" actions={result.get('actions_total', '-')}"
                  f"{'  ERROR: ' + result['error'][:120] if result.get('error') else ''}")

    runs.sort(key=lambda r: (r["pack_id"], r["level_id"], r["repeat"]))
    payload = {
        "meta": {
            "agent": agent, "model": model, "tier": args.tier,
            "repeats": repeats, "isolation": iso,
            "max_attempts": max_attempts, "anon": args.anon,
            "packs_dir": str(packs_dir),
            "levels": len(pairs), "sessions": len(jobs),
            "wall_seconds": round(time.monotonic() - started, 2),
        },
        "runs": runs,
    }
    results_path = out / "results.json"
    results_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    solved = sum(1 for r in runs if r.get("solved"))
    print(f"[sweep] {solved}/{len(runs)} solved in "
          f"{payload['meta']['wall_seconds']}s -> {results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
