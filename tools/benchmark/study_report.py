#!/usr/bin/env python3
"""Build matched-panel analysis and local reports for a GridPonder study."""
from __future__ import annotations

import argparse
import html
import json
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterable


BOOTSTRAP_SEED = 2027
BOOTSTRAP_SAMPLES = 2_000


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _load_records(
    results_dir: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    list[dict[str, Any]],
]:
    valid: dict[str, dict[str, Any]] = {}
    attempts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_records: list[dict[str, Any]] = []
    for path in sorted(results_dir.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") != "level" or not record.get("episode_id"):
                continue
            episode_id = str(record["episode_id"])
            attempts[episode_id].append(record)
            all_records.append(record)
            if "error" not in record:
                valid[episode_id] = record
    return valid, attempts, all_records


def _rate(values: Iterable[bool]) -> float | None:
    items = list(values)
    return sum(items) / len(items) if items else None


def _average(values: Iterable[float | int | None]) -> float | None:
    items = [float(value) for value in values if value is not None]
    return mean(items) if items else None


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None else None


def _episode_config(episode: dict[str, Any]) -> dict[str, Any]:
    return {
        "condition": episode["condition"],
        "mode": episode["inference_mode"],
        "input_mode": episode["input_mode"],
        "anon": bool(episode["anon"]),
        "max_n": episode.get("max_n"),
    }


def _config_id(config: dict[str, Any]) -> str:
    mode = config["mode"]
    if mode == "flex-n" and config.get("max_n"):
        mode = f"flex-{config['max_n']}"
    anon = "-anon" if config["anon"] else ""
    return (
        f"{config['condition']}-{mode}{anon}-"
        f"{config['input_mode'].replace('+', '-')}"
    )


def _metric_summary(
    episodes: list[dict[str, Any]],
    valid: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    records = [
        valid[episode["episode_id"]]
        for episode in episodes
        if episode["episode_id"] in valid
    ]
    solved = sum(bool(record.get("success")) for record in records)
    return {
        "expected": len(episodes),
        "complete": len(records),
        "completion_rate": _round(
            len(records) / len(episodes) if episodes else None
        ),
        "solved": solved,
        "accuracy": _round(solved / len(records) if records else None),
        "efficiency": _round(
            _average(
                record.get("efficiency")
                for record in records
                if record.get("success")
            )
        ),
        "mean_actions": _round(
            _average(record.get("actions_total") for record in records), 2
        ),
        "mean_calls": _round(
            _average(record.get("llm_calls") for record in records), 2
        ),
        "mean_cost_usd": _round(
            _average(record.get("cost_usd") for record in records), 4
        ),
        "cost_usd": _round(
            sum(float(record.get("cost_usd") or 0) for record in records), 2
        ),
    }


def _select(
    episodes: Iterable[dict[str, Any]],
    *,
    packs: set[str] | None = None,
    model_role: str | None = None,
    condition: str | None = None,
    mode: str | None = None,
    input_mode: str | None = None,
    anon: bool | None = None,
    repeat_index: int | None = 0,
) -> list[dict[str, Any]]:
    selected = []
    for episode in episodes:
        if packs is not None and episode["pack_id"] not in packs:
            continue
        if model_role is not None and episode["model_role"] != model_role:
            continue
        if condition is not None and episode["condition"] != condition:
            continue
        if mode is not None and episode["inference_mode"] != mode:
            continue
        if input_mode is not None and episode["input_mode"] != input_mode:
            continue
        if anon is not None and bool(episode["anon"]) != anon:
            continue
        if repeat_index is not None and int(episode["repeat_index"]) != repeat_index:
            continue
        selected.append(episode)
    return selected


def _pair_key(episode: dict[str, Any]) -> tuple[str, str, str, int]:
    return (
        episode["model_role"],
        episode["pack_id"],
        episode["level_id"],
        int(episode["repeat_index"]),
    )


def _cluster_bootstrap(
    pairs: list[tuple[str, float, float]],
) -> tuple[float | None, float | None]:
    by_game: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for pack_id, baseline, comparison in pairs:
        by_game[pack_id].append((baseline, comparison))
    games = sorted(by_game)
    if len(games) < 2:
        return None, None
    rng = random.Random(BOOTSTRAP_SEED)
    deltas: list[float] = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sampled = [rng.choice(games) for _ in games]
        rows = [row for game in sampled for row in by_game[game]]
        deltas.append(
            mean(comparison - baseline for baseline, comparison in rows)
        )
    deltas.sort()
    low = deltas[int(0.025 * (len(deltas) - 1))]
    high = deltas[int(0.975 * (len(deltas) - 1))]
    return _round(low), _round(high)


def _matched_contrast(
    *,
    name: str,
    model_role: str,
    baseline_episodes: list[dict[str, Any]],
    comparison_episodes: list[dict[str, Any]],
    valid: dict[str, dict[str, Any]],
    exclude_first_level: bool = False,
) -> dict[str, Any]:
    baseline = {
        _pair_key(episode): (episode, valid[episode["episode_id"]])
        for episode in baseline_episodes
        if episode["episode_id"] in valid
    }
    comparison = {
        _pair_key(episode): (episode, valid[episode["episode_id"]])
        for episode in comparison_episodes
        if episode["episode_id"] in valid
    }
    keys = sorted(set(baseline) & set(comparison))
    if exclude_first_level:
        keys = [key for key in keys if int(baseline[key][0]["level_index"]) > 0]
    pairs = [
        (
            baseline[key][0]["pack_id"],
            float(bool(baseline[key][1].get("success"))),
            float(bool(comparison[key][1].get("success"))),
        )
        for key in keys
    ]
    baseline_accuracy = _rate(bool(baseline[key][1].get("success")) for key in keys)
    comparison_accuracy = _rate(
        bool(comparison[key][1].get("success")) for key in keys
    )
    low, high = _cluster_bootstrap(pairs)
    helped = sum(
        not bool(baseline[key][1].get("success"))
        and bool(comparison[key][1].get("success"))
        for key in keys
    )
    harmed = sum(
        bool(baseline[key][1].get("success"))
        and not bool(comparison[key][1].get("success"))
        for key in keys
    )
    return {
        "name": name,
        "model_role": model_role,
        "paired_n": len(keys),
        "games": len({key[1] for key in keys}),
        "baseline_accuracy": _round(baseline_accuracy),
        "comparison_accuracy": _round(comparison_accuracy),
        "delta": _round(
            comparison_accuracy - baseline_accuracy
            if baseline_accuracy is not None and comparison_accuracy is not None
            else None
        ),
        "ci95_low": low,
        "ci95_high": high,
        "helped": helped,
        "harmed": harmed,
        "both_solved": sum(
            bool(baseline[key][1].get("success"))
            and bool(comparison[key][1].get("success"))
            for key in keys
        ),
        "neither_solved": sum(
            not bool(baseline[key][1].get("success"))
            and not bool(comparison[key][1].get("success"))
            for key in keys
        ),
    }


def _model_rows(
    *,
    episodes: list[dict[str, Any]],
    roles: dict[str, dict[str, Any]],
    valid: dict[str, dict[str, Any]],
    packs: set[str],
    condition: str,
    mode: str,
    input_mode: str,
    anon: bool,
) -> list[dict[str, Any]]:
    rows = []
    for role_name, role in sorted(roles.items()):
        selected = _select(
            episodes,
            packs=packs,
            model_role=role_name,
            condition=condition,
            mode=mode,
            input_mode=input_mode,
            anon=anon,
        )
        if not selected:
            continue
        rows.append(
            {
                "model_role": role_name,
                "model_id": role["variant_id"],
                "display_name": role["display_name"],
                "family": role["family"],
                "tier": role["tier"],
                "reference": role["reference"],
                **_metric_summary(selected, valid),
            }
        )
    return rows


def _contrast_rows(
    *,
    name: str,
    episodes: list[dict[str, Any]],
    roles: dict[str, dict[str, Any]],
    valid: dict[str, dict[str, Any]],
    packs: set[str],
    baseline_filter: dict[str, Any],
    comparison_filter: dict[str, Any],
    exclude_first_level: bool = False,
) -> list[dict[str, Any]]:
    rows = []
    for role_name, role in sorted(roles.items()):
        baseline = _select(
            episodes,
            packs=packs,
            model_role=role_name,
            **baseline_filter,
        )
        comparison = _select(
            episodes,
            packs=packs,
            model_role=role_name,
            **comparison_filter,
        )
        if not baseline or not comparison:
            continue
        rows.append(
            {
                **_matched_contrast(
                    name=name,
                    model_role=role_name,
                    baseline_episodes=baseline,
                    comparison_episodes=comparison,
                    valid=valid,
                    exclude_first_level=exclude_first_level,
                ),
                "model_id": role["variant_id"],
                "display_name": role["display_name"],
            }
        )
    return rows


def _challenge_rows(
    episodes: list[dict[str, Any]],
    roles: dict[str, dict[str, Any]],
    valid: dict[str, dict[str, Any]],
    headline: set[str],
) -> list[dict[str, Any]]:
    rows = []
    for pack_id in sorted(headline):
        selected = _select(
            episodes,
            packs={pack_id},
            condition="independent",
            mode="single",
            input_mode="text",
            anon=False,
        )
        metric = _metric_summary(selected, valid)
        model_accuracies = []
        for role_name in roles:
            model_records = _select(
                selected,
                model_role=role_name,
            )
            if model_records:
                model_accuracies.append(
                    {
                        "model_role": role_name,
                        **_metric_summary(model_records, valid),
                    }
                )
        rows.append(
            {
                "pack_id": pack_id,
                **metric,
                "above_50_percent": (
                    metric["accuracy"] is not None and metric["accuracy"] > 0.5
                ),
                "models": model_accuracies,
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            -(row["accuracy"] if row["accuracy"] is not None else -1),
            row["pack_id"],
        ),
    )


def _curriculum_diagnostics(
    episodes: list[dict[str, Any]],
    valid: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    curriculum = [
        episode for episode in episodes if episode["condition"] == "curriculum"
    ]
    first_levels = [
        episode for episode in curriculum if int(episode["level_index"]) == 0
    ]
    parity_checked = 0
    parity_failures = []
    independent_by_key = {
        (
            episode["model_role"],
            episode["pack_id"],
            episode["level_id"],
            episode["inference_mode"],
            episode["input_mode"],
            bool(episode["anon"]),
            episode.get("max_n"),
            int(episode["repeat_index"]),
        ): episode
        for episode in episodes
        if episode["condition"] == "independent"
    }
    for curriculum_episode in first_levels:
        key = (
            curriculum_episode["model_role"],
            curriculum_episode["pack_id"],
            curriculum_episode["level_id"],
            curriculum_episode["inference_mode"],
            curriculum_episode["input_mode"],
            bool(curriculum_episode["anon"]),
            curriculum_episode.get("max_n"),
            int(curriculum_episode["repeat_index"]),
        )
        independent = independent_by_key.get(key)
        if not independent:
            continue
        left = valid.get(independent["episode_id"])
        right = valid.get(curriculum_episode["episode_id"])
        if not left or not right:
            continue
        parity_checked += 1
        if left.get("initial_prompt_digest") != right.get("initial_prompt_digest"):
            parity_failures.append(
                {
                    "model_role": curriculum_episode["model_role"],
                    "pack_id": curriculum_episode["pack_id"],
                    "level_id": curriculum_episode["level_id"],
                }
            )
    records = [
        valid[episode["episode_id"]]
        for episode in curriculum
        if episode["episode_id"] in valid
    ]
    return {
        "first_level_prompt_parity_checked": parity_checked,
        "first_level_prompt_parity_failures": parity_failures,
        "mean_notebook_chars": _round(
            _average(record.get("notebook_after_chars") for record in records),
            1,
        ),
        "reflection_cost_usd": _round(
            sum(
                float((record.get("reflection") or {}).get("cost_usd") or 0)
                for record in records
            ),
            2,
        ),
        "reflection_calls": sum(
            int(record.get("reflection_calls") or 0) for record in records
        ),
    }


def _reliability_rows(
    episodes: list[dict[str, Any]],
    roles: dict[str, dict[str, Any]],
    valid: dict[str, dict[str, Any]],
    reliability_levels: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    groups: dict[
        tuple[str, str, str, bool, str, str],
        list[dict[str, Any]],
    ] = defaultdict(list)
    for episode in episodes:
        if (episode["pack_id"], episode["level_id"]) not in reliability_levels:
            continue
        config = _episode_config(episode)
        if config["condition"] != "independent":
            continue
        groups[
            (
                episode["model_role"],
                config["mode"],
                config["input_mode"],
                config["anon"],
                episode["pack_id"],
                episode["level_id"],
            )
        ].append(episode)

    rows = []
    for key, items in sorted(groups.items()):
        role_name, mode, input_mode, anon, pack_id, level_id = key
        records = [
            valid[item["episode_id"]]
            for item in items
            if item["episode_id"] in valid
        ]
        if len(items) < 2:
            continue
        outcomes = [bool(record.get("success")) for record in records]
        rows.append(
            {
                "model_role": role_name,
                "display_name": roles[role_name]["display_name"],
                "pack_id": pack_id,
                "level_id": level_id,
                "configuration": _config_id(
                    {
                        "condition": "independent",
                        "mode": mode,
                        "input_mode": input_mode,
                        "anon": anon,
                        "max_n": None,
                    }
                ),
                "expected_repeats": len(items),
                "complete_repeats": len(records),
                "solve_rate": _round(_rate(outcomes)),
                "unanimous": len(set(outcomes)) <= 1 if outcomes else None,
            }
        )
    return rows


def build_study_report(results_dir: Path) -> dict[str, Any]:
    meta = _load_json(results_dir / "meta.json")
    resolved = _load_json(results_dir / "resolved-manifest.json")
    valid, attempts, all_records = _load_records(results_dir)
    episodes = list(resolved["episodes"])
    roles = dict(resolved["models"])
    headline = set(resolved["headline_games"])
    diagnostic = set(resolved["diagnostic_games"])
    reliability_levels = {
        (item["pack"], item["level"])
        for item in resolved.get("reliability_levels") or []
    }
    expected_ids = {episode["episode_id"] for episode in episodes}
    unresolved_errors = sum(
        episode_id not in valid
        for episode_id, records in attempts.items()
        if any("error" in record for record in records)
    )
    duplicate_valid = {
        episode_id: sum("error" not in record for record in records)
        for episode_id, records in attempts.items()
        if sum("error" not in record for record in records) > 1
    }
    actual_cost = sum(
        float(record.get("cost_usd") or 0) for record in all_records
    )

    common = {
        "condition": "independent",
        "input_mode": "text",
        "anon": False,
    }
    planning = [
        *_contrast_rows(
            name="single_to_flex",
            episodes=episodes,
            roles=roles,
            valid=valid,
            packs=diagnostic,
            baseline_filter={**common, "mode": "single"},
            comparison_filter={**common, "mode": "flex-n"},
        ),
        *_contrast_rows(
            name="single_to_full",
            episodes=episodes,
            roles=roles,
            valid=valid,
            packs=diagnostic,
            baseline_filter={**common, "mode": "single"},
            comparison_filter={**common, "mode": "full"},
        ),
    ]
    representation = [
        *_contrast_rows(
            name="text_to_image",
            episodes=episodes,
            roles=roles,
            valid=valid,
            packs=diagnostic,
            baseline_filter={**common, "mode": "single"},
            comparison_filter={
                "condition": "independent",
                "mode": "single",
                "input_mode": "image",
                "anon": False,
            },
        ),
        *_contrast_rows(
            name="text_to_text_image",
            episodes=episodes,
            roles=roles,
            valid=valid,
            packs=diagnostic,
            baseline_filter={**common, "mode": "single"},
            comparison_filter={
                "condition": "independent",
                "mode": "single",
                "input_mode": "text+image",
                "anon": False,
            },
        ),
    ]
    surface = [
        *_contrast_rows(
            name="named_to_anonymous_single",
            episodes=episodes,
            roles=roles,
            valid=valid,
            packs=diagnostic,
            baseline_filter={**common, "mode": "single"},
            comparison_filter={
                "condition": "independent",
                "mode": "single",
                "input_mode": "text",
                "anon": True,
            },
        ),
        *_contrast_rows(
            name="named_to_anonymous_flex",
            episodes=episodes,
            roles=roles,
            valid=valid,
            packs=diagnostic,
            baseline_filter={**common, "mode": "flex-n"},
            comparison_filter={
                "condition": "independent",
                "mode": "flex-n",
                "input_mode": "text",
                "anon": True,
            },
        ),
    ]

    curriculum = []
    curriculum_configs = sorted(
        {
            (
                episode["inference_mode"],
                episode["input_mode"],
                bool(episode["anon"]),
                episode.get("max_n"),
            )
            for episode in episodes
            if episode["condition"] == "curriculum"
        }
    )
    for mode, input_mode, anon, max_n in curriculum_configs:
        packs = headline if mode == "single" and input_mode == "text" else diagnostic
        name = f"curriculum_{mode}_{input_mode}".replace("+", "_")
        for role_name, role in sorted(roles.items()):
            baseline = _select(
                episodes,
                packs=packs,
                model_role=role_name,
                condition="independent",
                mode=mode,
                input_mode=input_mode,
                anon=anon,
            )
            comparison = _select(
                episodes,
                packs=packs,
                model_role=role_name,
                condition="curriculum",
                mode=mode,
                input_mode=input_mode,
                anon=anon,
            )
            if not comparison:
                continue
            curriculum.append(
                {
                    **_matched_contrast(
                        name=name,
                        model_role=role_name,
                        baseline_episodes=baseline,
                        comparison_episodes=comparison,
                        valid=valid,
                        exclude_first_level=True,
                    ),
                    "model_id": role["variant_id"],
                    "display_name": role["display_name"],
                    "configuration": _config_id(
                        {
                            "condition": "curriculum",
                            "mode": mode,
                            "input_mode": input_mode,
                            "anon": anon,
                            "max_n": max_n,
                        }
                    ),
                }
            )

    return {
        "schema_version": 1,
        "generated": datetime.now(timezone.utc).isoformat(),
        "study": {
            "study_id": resolved["study_id"],
            "manifest_digest": resolved["manifest_digest"],
            "instruction_policy": resolved["instruction_policy"],
            "selected_panels": resolved["selected_panels"],
            "headline_games": sorted(headline),
            "diagnostic_games": sorted(diagnostic),
            "models": roles,
        },
        "completion": {
            "expected": len(expected_ids),
            "complete": len(expected_ids & set(valid)),
            "remaining": len(expected_ids - set(valid)),
            "completion_rate": _round(
                len(expected_ids & set(valid)) / len(expected_ids)
                if expected_ids
                else None
            ),
            "unresolved_error_episodes": unresolved_errors,
            "duplicate_valid_records": duplicate_valid,
            "attempt_records": len(all_records),
            "recorded_cost_usd": _round(actual_cost, 2),
        },
        "views": {
            "headline": {
                "title": "Headline capability",
                "scope": "All frozen games; independent, named text, single-step",
                "rows": _model_rows(
                    episodes=episodes,
                    roles=roles,
                    valid=valid,
                    packs=headline,
                    condition="independent",
                    mode="single",
                    input_mode="text",
                    anon=False,
                ),
            },
            "planning": {
                "title": "Planning commitment",
                "scope": "Matched diagnostic games and levels",
                "rows": planning,
            },
            "representation": {
                "title": "Representation",
                "scope": "Matched diagnostic games and levels; single-step",
                "rows": representation,
            },
            "surface": {
                "title": "Semantic surface",
                "scope": "Matched diagnostic games and levels; text input",
                "rows": surface,
            },
            "curriculum": {
                "title": "Cross-level skill acquisition",
                "scope": (
                    "Matched levels; first level excluded from the primary "
                    "curriculum contrast"
                ),
                "rows": curriculum,
                "diagnostics": _curriculum_diagnostics(episodes, valid),
            },
            "reliability": {
                "title": "Repeated-run reliability",
                "scope": "Predeclared reliability levels and configurations",
                "rows": _reliability_rows(
                    episodes,
                    roles,
                    valid,
                    reliability_levels,
                ),
            },
        },
        "challenge": {
            "definition": (
                "Independent named-text single-step accuracy across all "
                "role-selected models"
            ),
            "games": _challenge_rows(episodes, roles, valid, headline),
        },
        "provenance": {
            "run_id": meta.get("run_id"),
            "source": meta.get("source"),
            "scheduler": meta.get("scheduler"),
            "launch_history": meta.get("launch_history") or [],
        },
    }


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def _report_html(report: dict[str, Any]) -> str:
    completion = report["completion"]
    headline_rows = report["views"]["headline"]["rows"]
    challenge_rows = report["challenge"]["games"]
    curriculum_rows = report["views"]["curriculum"]["rows"]

    def table(headers: list[str], rows: list[list[str]]) -> str:
        head = "".join(f"<th>{html.escape(value)}</th>" for value in headers)
        body = "".join(
            "<tr>" + "".join(f"<td>{value}</td>" for value in row) + "</tr>"
            for row in rows
        )
        return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"

    headline_table = table(
        ["Model role", "Model", "Complete", "Accuracy", "Efficiency", "Cost"],
        [
            [
                html.escape(row["model_role"]),
                html.escape(row["display_name"]),
                f"{row['complete']}/{row['expected']}",
                _percent(row["accuracy"]),
                _percent(row["efficiency"]),
                f"${row['cost_usd']:.2f}",
            ]
            for row in headline_rows
        ],
    )
    challenge_table = table(
        ["Game", "Complete", "Accuracy", "Durability"],
        [
            [
                html.escape(row["pack_id"]),
                f"{row['complete']}/{row['expected']}",
                _percent(row["accuracy"]),
                (
                    "<strong class='warn'>Above 50%</strong>"
                    if row["above_50_percent"]
                    else "Headroom"
                ),
            ]
            for row in challenge_rows
        ],
    )
    curriculum_table = table(
        ["Model", "Configuration", "Pairs", "Independent", "Curriculum", "Delta", "95% game CI"],
        [
            [
                html.escape(row["display_name"]),
                html.escape(row["configuration"]),
                str(row["paired_n"]),
                _percent(row["baseline_accuracy"]),
                _percent(row["comparison_accuracy"]),
                _percent(row["delta"]),
                (
                    "n/a"
                    if row["ci95_low"] is None
                    else f"{_percent(row['ci95_low'])} to {_percent(row['ci95_high'])}"
                ),
            ]
            for row in curriculum_rows
        ],
    )
    payload = html.escape(json.dumps(report, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GridPonder study report</title>
<style>
:root {{ color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, sans-serif; color: #172033; background: #f5f7fa; }}
body {{ margin: 0; }}
main {{ max-width: 1180px; margin: 0 auto; padding: 42px 24px 80px; }}
h1 {{ font-size: 34px; margin: 0 0 8px; letter-spacing: 0; }}
h2 {{ margin-top: 38px; font-size: 21px; }}
.lede {{ color: #526079; max-width: 820px; }}
.status {{ display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 1px; margin: 26px 0; border: 1px solid #d7dde7; background: #d7dde7; }}
.metric {{ background: white; padding: 16px; }}
.metric b {{ display: block; font-size: 23px; }}
.metric span {{ color: #65718a; font-size: 12px; text-transform: uppercase; }}
.table-wrap {{ overflow-x: auto; border: 1px solid #d7dde7; background: white; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th,td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #e8ebf0; white-space: nowrap; }}
th {{ background: #eef1f5; color: #536079; font-size: 11px; text-transform: uppercase; }}
.warn {{ color: #a13e21; }}
details {{ margin-top: 38px; }}
pre {{ overflow: auto; padding: 16px; background: #172033; color: #e9edf5; font-size: 11px; }}
@media(max-width:720px) {{ .status {{ grid-template-columns: repeat(2,minmax(0,1fr)); }} main {{ padding: 28px 14px 60px; }} }}
</style>
</head>
<body><main>
<h1>GridPonder study report</h1>
<p class="lede">Matched nested-panel analysis. Every contrast is limited to the models, games, levels, and configurations that support it.</p>
<div class="status">
  <div class="metric"><b>{completion['complete']}/{completion['expected']}</b><span>episodes complete</span></div>
  <div class="metric"><b>{_percent(completion['completion_rate'])}</b><span>completion</span></div>
  <div class="metric"><b>{completion['unresolved_error_episodes']}</b><span>unresolved errors</span></div>
  <div class="metric"><b>${completion['recorded_cost_usd']:.2f}</b><span>recorded cost</span></div>
</div>
<h2>Headline capability</h2>{headline_table}
<h2>Challenge durability by game</h2><p class="lede">Accuracy above 50% is highlighted as a possible saturation risk, not as a quality failure.</p>{challenge_table}
<h2>Curriculum versus independent</h2>{curriculum_table}
<details><summary>Machine-readable report</summary><pre>{payload}</pre></details>
</main></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        help="Study leaderboard JSON; defaults inside the run directory",
    )
    parser.add_argument(
        "--html",
        type=Path,
        help="Self-contained HTML report; defaults inside the run directory",
    )
    args = parser.parse_args()
    results_dir = args.results_dir.resolve()
    report = build_study_report(results_dir)
    output = args.output or results_dir / "study-leaderboard.json"
    html_output = args.html or results_dir / "report" / "study.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    html_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    html_output.write_text(_report_html(report))
    completion = report["completion"]
    print(
        f"Wrote {output} and {html_output}; "
        f"{completion['complete']}/{completion['expected']} complete"
    )


if __name__ == "__main__":
    main()
