#!/usr/bin/env python3
"""Build a self-contained, run-scoped benchmark report."""
from __future__ import annotations

import argparse
import html
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_run(results_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    meta_path = results_dir / "meta.json"
    run_meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
    datasets: list[dict[str, Any]] = []
    for path in sorted(results_dir.glob("*.jsonl")):
        file_meta: dict[str, Any] = {}
        levels: list[dict[str, Any]] = []
        with path.open() as handle:
            for raw_line in handle:
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") == "run_meta":
                    file_meta = record
                elif record.get("type") == "level":
                    levels.append(record)
        if file_meta:
            datasets.append(
                {"path": path, "meta": file_meta, "levels": levels}
            )
    return run_meta, datasets


def summarize(
    run_meta: dict[str, Any], datasets: list[dict[str, Any]]
) -> dict[str, Any]:
    expected_levels = sum(
        len(levels) for levels in (run_meta.get("levels_by_pack") or {}).values()
    )
    expected_configurations = _expected_configuration_keys(run_meta, datasets)
    expected_keys = set(expected_configurations)
    present_keys = {_configuration_key(dataset["meta"]) for dataset in datasets}
    missing_keys = sorted(expected_keys - present_keys)
    configs: list[dict[str, Any]] = []
    known_cost_total = 0.0
    unknown_cost_levels = 0
    total_errors = 0
    total_completed = 0
    seen_keys: set[tuple[str, str, str, str, bool, str]] = set()
    duplicates = 0

    for dataset in datasets:
        meta = dataset["meta"]
        levels = dataset["levels"]
        valid = [level for level in levels if "error" not in level]
        errors = [level for level in levels if "error" in level]
        successes = [level for level in valid if level.get("success")]
        scores = [float(level.get("aggregate_score") or 0.0) for level in valid]
        costs = [
            float(level["cost_usd"])
            for level in levels
            if level.get("cost_usd") is not None
        ]
        unknown_cost = sum(
            1
            for level in levels
            if level.get("cost_usd") is None
            and int(level.get("llm_calls") or 0) > 0
        )
        known_cost_total += sum(costs)
        unknown_cost_levels += unknown_cost
        total_errors += len(errors)
        total_completed += len(levels)

        for level in levels:
            key = (
                str(meta.get("model_id", "")),
                str(level.get("pack_id", "")),
                str(level.get("level_id", "")),
                str(meta.get("inference_mode", "single")),
                bool(meta.get("anon", False)),
                str(meta.get("input_mode", "text")),
            )
            if key in seen_keys:
                duplicates += 1
            seen_keys.add(key)

        configs.append(
            {
                "file": dataset["path"].name,
                "model_id": meta.get("model_id", ""),
                "display_name": meta.get("display_name", meta.get("model_id", "")),
                "model": meta.get("model") or meta.get("litellm_model", ""),
                "connector": meta.get("connector", "litellm"),
                "model_params": meta.get("model_params") or {},
                "pricing": meta.get("pricing"),
                "inference_mode": meta.get("inference_mode", "single"),
                "anonymous": bool(meta.get("anon", False)),
                "input_mode": meta.get("input_mode", "text"),
                "expected": expected_levels,
                "completed": len(levels),
                "valid": len(valid),
                "errors": len(errors),
                "successes": len(successes),
                "success_rate_valid": (
                    len(successes) / len(valid) if valid else None
                ),
                "success_rate_expected": (
                    len(successes) / expected_levels if expected_levels else None
                ),
                "mean_score": statistics.mean(scores) if scores else None,
                "cost_usd": None if unknown_cost else sum(costs),
                "known_cost_usd": sum(costs),
                "unknown_cost_levels": unknown_cost,
                "cost_sources": sorted(
                    {
                        source
                        for level in levels
                        for source in (level.get("cost_sources") or [])
                    }
                ),
                "llm_calls": sum(int(level.get("llm_calls") or 0) for level in levels),
                "input_tokens": sum(
                    int(level.get("input_tokens_total") or 0) for level in levels
                ),
                "reasoning_tokens": sum(
                    int(level.get("thinking_tokens_total") or 0) for level in levels
                ),
                "output_tokens": sum(
                    int(level.get("output_tokens_total") or 0) for level in levels
                ),
            }
        )

    per_pack: dict[str, dict[str, int]] = defaultdict(
        lambda: {"completed": 0, "errors": 0, "successes": 0}
    )
    error_rows: list[dict[str, str]] = []
    for dataset in datasets:
        model_id = str(dataset["meta"].get("model_id", ""))
        config = _config_label(dataset["meta"])
        for level in dataset["levels"]:
            pack = str(level.get("pack_id", ""))
            per_pack[pack]["completed"] += 1
            if "error" in level:
                per_pack[pack]["errors"] += 1
                error_rows.append(
                    {
                        "model": model_id,
                        "config": config,
                        "level": f"{pack}/{level.get('level_id', '')}",
                        "error": str(level.get("error", "")),
                    }
                )
            elif level.get("success"):
                per_pack[pack]["successes"] += 1

    expected_configuration_count = len(expected_configurations)
    expected_level_runs = expected_levels * expected_configuration_count
    incomplete_configurations = [
        f"{config['model_id']}: {_config_label(config)} "
        f"({config['completed']}/{config['expected']})"
        for config in configs
        if config["completed"] != config["expected"]
    ]
    missing_configurations = [
        f"{model_id}: {_config_label({'inference_mode': mode, 'anon': anonymous, 'input_mode': input_mode})}"
        for model_id, mode, anonymous, input_mode in missing_keys
    ]
    complete = (
        bool(expected_configuration_count)
        and not missing_configurations
        and not incomplete_configurations
        and not total_errors
        and not duplicates
    )

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "run": run_meta,
        "complete": complete,
        "expected_levels_per_configuration": expected_levels,
        "configuration_count": len(configs),
        "expected_configuration_count": expected_configuration_count,
        "expected_level_runs": expected_level_runs,
        "missing_configurations": missing_configurations,
        "incomplete_configurations": incomplete_configurations,
        "completed": total_completed,
        "errors": total_errors,
        "duplicates": duplicates,
        "cost_usd": None if unknown_cost_levels else known_cost_total,
        "known_cost_usd": known_cost_total,
        "unknown_cost_levels": unknown_cost_levels,
        "llm_calls": sum(config["llm_calls"] for config in configs),
        "input_tokens": sum(config["input_tokens"] for config in configs),
        "reasoning_tokens": sum(config["reasoning_tokens"] for config in configs),
        "output_tokens": sum(config["output_tokens"] for config in configs),
        "configurations": configs,
        "per_pack": dict(sorted(per_pack.items())),
        "error_rows": error_rows,
    }


def render_html(summary: dict[str, Any]) -> str:
    run = summary["run"]
    source = run.get("source") or {}
    repository = source.get("repository") or {}
    configurations = summary["configurations"]

    def esc(value: Any) -> str:
        return html.escape(str(value))

    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{value * 100:.1f}%"

    def num(value: float | None, digits: int = 3) -> str:
        return "n/a" if value is None else f"{value:.{digits}f}"

    def money(value: float | None) -> str:
        return "n/a" if value is None else f"${value:.2f}"

    config_rows = "\n".join(
        "<tr>"
        f"<td>{esc(config['display_name'])}<small>{esc(config['model'])}</small></td>"
        f"<td>{esc(_config_label(config))}</td>"
        f"<td>{config['completed']}/{config['expected'] or '?'}</td>"
        f"<td>{config['errors']}</td>"
        f"<td>{config['successes']}</td>"
        f"<td>{pct(config['success_rate_expected'])}</td>"
        f"<td>{num(config['mean_score'])}</td>"
        f"<td>{config['llm_calls']}</td>"
        f"<td>{config['input_tokens']}/{config['reasoning_tokens']}/{config['output_tokens']}</td>"
        f"<td>{money(config['cost_usd'])}</td>"
        f'<td><a href="../{esc(config["file"])}">JSONL</a></td>'
        "</tr>"
        for config in configurations
    )
    pack_rows = "\n".join(
        "<tr>"
        f"<td>{esc(pack)}</td>"
        f"<td>{stats['completed']}</td>"
        f"<td>{stats['successes']}</td>"
        f"<td>{stats['errors']}</td>"
        "</tr>"
        for pack, stats in summary["per_pack"].items()
    )
    error_rows = "\n".join(
        "<tr>"
        f"<td>{esc(row['model'])}</td>"
        f"<td>{esc(row['config'])}</td>"
        f"<td>{esc(row['level'])}</td>"
        f"<td><code>{esc(row['error'])}</code></td>"
        "</tr>"
        for row in summary["error_rows"]
    ) or '<tr><td colspan="4">No infrastructure errors.</td></tr>'
    params_by_model = {
        str(config["model_id"]): {
            "params": config["model_params"],
            "pricing": config["pricing"],
        }
        for config in configurations
        if config["model_params"] or config["pricing"]
    }
    model_params = "\n".join(
        f"<li><strong>{esc(model_id)}</strong>: "
        f"<code>{esc(json.dumps(config, sort_keys=True))}</code></li>"
        for model_id, config in sorted(params_by_model.items())
    ) or "<li>None recorded.</li>"
    missing_items = "\n".join(
        f"<li>{esc(label)}</li>"
        for label in (
            summary["missing_configurations"]
            + summary["incomplete_configurations"]
        )
    ) or "<li>None.</li>"
    status = "COMPLETE" if summary["complete"] else "INCOMPLETE"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GridPonder benchmark report</title>
<style>
:root {{ color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
body {{ margin: 0; color: #17212b; background: #f5f7f8; }}
header, main {{ max-width: 1240px; margin: auto; padding: 24px; }}
header {{ padding-bottom: 8px; }}
h1 {{ font-size: 28px; margin: 0 0 6px; }}
h2 {{ font-size: 18px; margin-top: 32px; }}
p, li {{ line-height: 1.5; }}
.status {{ font-weight: 700; }}
.muted, small {{ color: #63707c; }}
.metrics {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(150px,1fr)); gap: 8px; }}
.metric {{ background: white; border: 1px solid #dce2e6; border-radius: 6px; padding: 12px; }}
.metric strong {{ display: block; font-size: 21px; }}
.table-wrap {{ overflow-x: auto; background: white; border: 1px solid #dce2e6; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ padding: 9px 10px; text-align: left; border-bottom: 1px solid #e6eaed; vertical-align: top; }}
th {{ background: #eef2f4; white-space: nowrap; }}
td small {{ display: block; margin-top: 3px; }}
code {{ font-family: ui-monospace, SFMono-Regular, monospace; font-size: 12px; }}
a {{ color: #075985; }}
</style>
</head>
<body>
<header>
  <h1>GridPonder benchmark report</h1>
  <div class="muted"><span class="status">{status}</span> · Run {esc(run.get('run_id', 'unknown'))} · generated {esc(summary['generated'])}</div>
</header>
<main>
  <section class="metrics">
    <div class="metric"><strong>{summary['configuration_count']}/{summary['expected_configuration_count']}</strong><span>configuration files</span></div>
    <div class="metric"><strong>{summary['completed']}/{summary['expected_level_runs']}</strong><span>completed level runs</span></div>
    <div class="metric"><strong>{summary['errors']}</strong><span>infrastructure errors</span></div>
    <div class="metric"><strong>{summary['duplicates']}</strong><span>duplicate result keys</span></div>
    <div class="metric"><strong>{summary['llm_calls']}</strong><span>model calls</span></div>
    <div class="metric"><strong>{money(summary['cost_usd'])}</strong><span>recorded cost ({summary['unknown_cost_levels']} unknown)</span></div>
  </section>

  <h2>Provenance</h2>
  <p>
    Repository <code>{esc(repository.get('sha', 'unknown'))}</code>
    ({'dirty' if repository.get('dirty') else 'clean'});
    packs <code>{esc(source.get('packs_digest', 'unknown'))}</code>;
    Python <code>{esc((source.get('python') or {}).get('version', 'unknown'))}</code>.
  </p>

  <h2>Configurations</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>Model</th><th>Configuration</th><th>Complete</th><th>Errors</th><th>Solved</th><th>Solved / expected</th><th>Mean score</th><th>Calls</th><th>Tokens in/reason/out</th><th>Cost</th><th>Raw</th></tr></thead>
    <tbody>{config_rows}</tbody>
  </table></div>

  <h2>Missing Or Incomplete</h2>
  <ul>{missing_items}</ul>

  <h2>Pack Totals</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>Pack</th><th>Completed</th><th>Solved</th><th>Errors</th></tr></thead>
    <tbody>{pack_rows}</tbody>
  </table></div>

  <h2>Model Parameters</h2>
  <ul>{model_params}</ul>

  <h2>Infrastructure Errors</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>Model</th><th>Configuration</th><th>Level</th><th>Error</th></tr></thead>
    <tbody>{error_rows}</tbody>
  </table></div>
</main>
</body>
</html>
"""


def _config_label(meta: dict[str, Any]) -> str:
    mode = str(meta.get("inference_mode", "single"))
    input_mode = str(meta.get("input_mode", "text"))
    anonymous = bool(meta.get("anonymous", meta.get("anon", False)))
    return f"{input_mode} · {mode}" + (" · anonymous" if anonymous else "")


def _configuration_key(meta: dict[str, Any]) -> tuple[str, str, bool, str]:
    return (
        str(meta.get("model_id", "")),
        str(meta.get("inference_mode", "single")),
        bool(meta.get("anonymous", meta.get("anon", False))),
        str(meta.get("input_mode", "text")),
    )


def _expected_configuration_keys(
    run_meta: dict[str, Any],
    datasets: list[dict[str, Any]],
) -> list[tuple[str, str, bool, str]]:
    model_ids = [
        str(model_id) for model_id in (run_meta.get("model_variants") or [])
    ]
    if not model_ids:
        model_ids = sorted(
            {
                str(dataset["meta"].get("model_id", ""))
                for dataset in datasets
            }
        )
    modes = [str(mode) for mode in (run_meta.get("modes") or [])]
    input_modes = [
        str(input_mode)
        for input_mode in (run_meta.get("input_modes") or ["text"])
    ]
    anon_modes = {
        str(mode) for mode in (run_meta.get("anon_modes") or [])
    }
    if not modes:
        return sorted({_configuration_key(dataset["meta"]) for dataset in datasets})

    keys: list[tuple[str, str, bool, str]] = []
    for model_id in model_ids:
        for mode in modes:
            keys.extend(
                (model_id, mode, False, input_mode)
                for input_mode in input_modes
            )
            if mode in anon_modes:
                keys.append((model_id, mode, True, "text"))
    return keys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    output_dir = args.output_dir or args.results_dir / "report"
    output_dir.mkdir(parents=True, exist_ok=True)
    run_meta, datasets = load_run(args.results_dir)
    if not datasets:
        raise SystemExit(f"No JSONL result datasets found in {args.results_dir}")
    summary = summarize(run_meta, datasets)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (output_dir / "index.html").write_text(render_html(summary))
    print(f"Wrote {output_dir / 'index.html'}")


if __name__ == "__main__":
    main()
