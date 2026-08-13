#!/usr/bin/env python3
"""Validate packs, gold paths, and all benchmark observation configurations."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).parent.resolve()
REPO_ROOT = SCRIPT_DIR.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engines.python._systems import unsupported_system_types
from engines.python._turn_engine import TurnEngine
from engines.python.action_enum import enumerate_actions
from engines.python.gold_path import gold_path_actions
from engines.python.loader import load_pack
from engines.python.observation import build_prompt
from engines.python.text_renderer import render as render_board
from board_image import render_board_png
from run_manifest import source_snapshot


CONFIGURATIONS = [
    *(("single", False, mode) for mode in ("text", "image", "text+image")),
    *(("flex-n", False, mode) for mode in ("text", "image", "text+image")),
    *(("full", False, mode) for mode in ("text", "image", "text+image")),
    ("single", True, "text"),
    ("flex-n", True, "text"),
]


def validate(
    packs_dir: Path,
    *,
    include_images: bool = True,
    samples_dir: Path | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    packs_out: dict[str, dict[str, Any]] = {}
    prompt_max: dict[str, dict[str, Any]] = {}
    totals = Counter()

    if sys.version_info < (3, 10):
        _issue(
            issues,
            "error",
            "environment",
            f"Python 3.10+ required; running {sys.version.split()[0]}",
        )
    if not packs_dir.is_dir():
        _issue(issues, "error", "packs", f"Pack root does not exist: {packs_dir}")
        return _finish(packs_dir, packs_out, prompt_max, issues, totals)

    for pack_dir in sorted(packs_dir.iterdir()):
        if not (pack_dir / "manifest.json").is_file():
            continue
        pack_id = pack_dir.name
        totals["packs"] += 1
        pack_stats: dict[str, Any] = {
            "levels": 0,
            "gold_paths_passed": 0,
            "states_validated": 0,
            "max_prompt_chars": 0,
            "max_legal_actions": 0,
            "max_syntactic_actions": 0,
            "actions_seen": [],
        }
        packs_out[pack_id] = pack_stats
        try:
            raw_game = json.loads((pack_dir / "game.json").read_text())
            game, levels = load_pack(pack_dir)
        except Exception as exc:
            _issue(issues, "error", pack_id, f"Pack load failed: {exc}")
            continue

        unknown = unsupported_system_types(game)
        if unknown:
            _issue(
                issues,
                "error",
                pack_id,
                "Unsupported enabled systems: " + ", ".join(unknown),
            )

        action_ids = [action.get("id", "") for action in raw_game.get("actions", [])]
        if "give_up" in action_ids:
            _issue(
                issues,
                "error",
                pack_id,
                "Game declares reserved harness action 'give_up'",
            )

        sequence = [
            entry["ref"]
            for entry in raw_game.get("levelSequence", [])
            if entry.get("type") == "level" and entry.get("ref")
        ]
        missing = sorted(set(sequence) - set(levels))
        unsequenced = sorted(set(levels) - set(sequence))
        if missing:
            _issue(
                issues,
                "error",
                pack_id,
                "levelSequence references missing levels: " + ", ".join(missing),
            )
        if unsequenced:
            _issue(
                issues,
                "warning",
                pack_id,
                "Levels omitted from levelSequence: " + ", ".join(unsequenced),
            )

        action_seen: set[str] = set()
        sample_written = False
        for level_id in sequence or sorted(levels):
            if level_id not in levels:
                continue
            totals["levels"] += 1
            pack_stats["levels"] += 1
            level = levels[level_id]
            gold = gold_path_actions(level)
            if not gold:
                _issue(issues, "error", f"{pack_id}/{level_id}", "Missing gold path")
                continue
            try:
                engine = TurnEngine(game, level)
            except Exception as exc:
                _issue(
                    issues,
                    "error",
                    f"{pack_id}/{level_id}",
                    f"Engine initialization failed: {exc}",
                )
                continue

            level_failed = False
            for step, (gold_action, gold_params) in enumerate(gold):
                if engine.is_won:
                    break
                scope = f"{pack_id}/{level_id}@{step}"
                try:
                    syntactic = enumerate_actions(game, engine.state)
                    legal = enumerate_actions(game, engine.state, engine=engine)
                    action_seen.update(action["action"] for action in legal)
                    pack_stats["max_syntactic_actions"] = max(
                        pack_stats["max_syntactic_actions"], len(syntactic)
                    )
                    pack_stats["max_legal_actions"] = max(
                        pack_stats["max_legal_actions"], len(legal)
                    )
                    _validate_state(
                        game,
                        level,
                        engine,
                        pack_dir,
                        legal,
                        include_images,
                        scope,
                        issues,
                        prompt_max,
                        pack_stats,
                    )
                    if samples_dir is not None and not sample_written:
                        _write_samples(
                            samples_dir,
                            pack_id,
                            level_id,
                            game,
                            level,
                            engine,
                            pack_dir,
                            legal,
                            include_images,
                        )
                        sample_written = True
                    pack_stats["states_validated"] += 1
                    totals["states"] += 1
                except Exception as exc:
                    _issue(issues, "error", scope, f"Observation failed: {exc}")
                    level_failed = True
                    break

                result = engine.execute_turn(gold_action, gold_params)
                if not result.accepted:
                    _issue(
                        issues,
                        "error",
                        scope,
                        f"Gold action rejected: {gold_action} {gold_params}",
                    )
                    level_failed = True
                    break

            if not level_failed and not engine.is_won:
                _issue(
                    issues,
                    "error",
                    f"{pack_id}/{level_id}",
                    f"Gold path did not win after {len(gold)} actions",
                )
            elif not level_failed:
                totals["gold_paths_passed"] += 1
                pack_stats["gold_paths_passed"] += 1

        never_seen = sorted(set(action_ids) - action_seen - {"give_up"})
        if never_seen:
            _issue(
                issues,
                "warning",
                pack_id,
                "Actions never legal on any gold-path state: " + ", ".join(never_seen),
            )
        pack_stats["actions_seen"] = sorted(action_seen)

    return _finish(packs_dir, packs_out, prompt_max, issues, totals)


def _validate_state(
    game,
    level: dict,
    engine: TurnEngine,
    pack_dir: Path,
    legal_actions: list[dict[str, Any]],
    include_images: bool,
    scope: str,
    issues: list[dict[str, str]],
    prompt_max: dict[str, dict[str, Any]],
    pack_stats: dict[str, Any],
) -> None:
    board_text = render_board(engine.state, game)
    grid_rows = board_text.splitlines()[: engine.state.board.height]
    widths = {len(row) for row in grid_rows}
    if widths != {engine.state.board.width}:
        _issue(
            issues,
            "error",
            scope,
            f"Text grid widths {sorted(widths)} do not match board width "
            f"{engine.state.board.width}",
        )
    if any(row.endswith(" ") for row in grid_rows):
        _issue(issues, "error", scope, "Text grid contains trailing spaces")

    for inference_mode, anonymous, input_mode in CONFIGURATIONS:
        prompt = build_prompt(
            game,
            level,
            engine.state,
            anonymize=anonymous,
            inference_mode=inference_mode,
            max_n=None,
            text_board=input_mode != "image",
            attach_image=input_mode in ("image", "text+image"),
            valid_actions=legal_actions,
        )
        key = (
            f"{inference_mode}|{'anon' if anonymous else 'named'}|{input_mode}"
        )
        current = prompt_max.get(key)
        if current is None or len(prompt) > current["chars"]:
            prompt_max[key] = {"chars": len(prompt), "scope": scope}
        pack_stats["max_prompt_chars"] = max(
            pack_stats["max_prompt_chars"], len(prompt)
        )
        if len(prompt) > 20000:
            _issue(
                issues,
                "warning",
                scope,
                f"{key} prompt is {len(prompt)} characters",
            )

    if include_images:
        png = render_board_png(game, engine.state, pack_dir)
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            _issue(issues, "error", scope, "Image renderer returned invalid PNG")
        if len(png) < 200:
            _issue(
                issues,
                "error",
                scope,
                f"Image renderer returned suspiciously small PNG ({len(png)} bytes)",
            )
        from PIL import Image
        from io import BytesIO

        image = Image.open(BytesIO(png)).convert("RGB")
        extrema = image.getextrema()
        if all(low == high for low, high in extrema):
            _issue(issues, "error", scope, "Image renderer returned a blank image")


def _write_samples(
    samples_dir: Path,
    pack_id: str,
    level_id: str,
    game,
    level: dict,
    engine: TurnEngine,
    pack_dir: Path,
    legal_actions: list[dict[str, Any]],
    include_images: bool,
) -> None:
    target = samples_dir / pack_id
    target.mkdir(parents=True, exist_ok=True)
    for inference_mode, anonymous, input_mode in CONFIGURATIONS:
        prompt = build_prompt(
            game,
            level,
            engine.state,
            anonymize=anonymous,
            inference_mode=inference_mode,
            max_n=None,
            text_board=input_mode != "image",
            attach_image=input_mode in ("image", "text+image"),
            valid_actions=legal_actions,
        )
        suffix = (
            f"{input_mode.replace('+', '-')}-{inference_mode}"
            + ("-anon" if anonymous else "")
        )
        (target / f"{level_id}-{suffix}.txt").write_text(prompt)
    if include_images:
        (target / f"{level_id}.png").write_bytes(
            render_board_png(game, engine.state, pack_dir)
        )


def _issue(
    issues: list[dict[str, str]], severity: str, scope: str, message: str
) -> None:
    record = {"severity": severity, "scope": scope, "message": message}
    if record not in issues:
        issues.append(record)


def _finish(
    packs_dir: Path,
    packs: dict[str, Any],
    prompt_max: dict[str, Any],
    issues: list[dict[str, str]],
    totals: Counter,
) -> dict[str, Any]:
    source = source_snapshot(REPO_ROOT, packs_dir)
    if (source.get("repository") or {}).get("dirty"):
        _issue(
            issues,
            "warning",
            "source",
            "Repository worktree is dirty; commit or archive changes before the benchmark",
        )
    errors = sum(issue["severity"] == "error" for issue in issues)
    warnings = sum(issue["severity"] == "warning" for issue in issues)
    return {
        "schema_version": 1,
        "generated": datetime.now(timezone.utc).isoformat(),
        "ok": errors == 0,
        "configuration_count": len(CONFIGURATIONS),
        "totals": {
            **dict(totals),
            "errors": errors,
            "warnings": warnings,
        },
        "source": source,
        "prompt_maxima": prompt_max,
        "packs": packs,
        "issues": issues,
    }


def _markdown(report: dict[str, Any]) -> str:
    totals = report["totals"]
    lines = [
        "# Benchmark preflight",
        "",
        f"- Status: {'PASS' if report['ok'] else 'FAIL'}",
        f"- Packs: {totals.get('packs', 0)}",
        f"- Levels: {totals.get('levels', 0)}",
        f"- Gold paths passed: {totals.get('gold_paths_passed', 0)}",
        f"- Observation configurations: {report['configuration_count']}",
        f"- Errors: {totals.get('errors', 0)}",
        f"- Warnings: {totals.get('warnings', 0)}",
        "",
        "## Packs",
        "",
        "| Pack | Levels | Gold | States | Max prompt | Legal/syntactic actions |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for pack_id, stats in report["packs"].items():
        lines.append(
            f"| {pack_id} | {stats['levels']} | {stats['gold_paths_passed']} | "
            f"{stats['states_validated']} | {stats['max_prompt_chars']} | "
            f"{stats['max_legal_actions']}/{stats['max_syntactic_actions']} |"
        )
    lines.extend(["", "## Issues", ""])
    if not report["issues"]:
        lines.append("None.")
    else:
        for issue in report["issues"]:
            lines.append(
                f"- **{issue['severity'].upper()}** `{issue['scope']}`: "
                f"{issue['message']}"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--packs-dir",
        type=Path,
        default=REPO_ROOT / "packs",
    )
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--samples-dir", type=Path)
    args = parser.parse_args()

    report = validate(
        args.packs_dir,
        include_images=not args.skip_images,
        samples_dir=args.samples_dir,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        args.output.with_suffix(".md").write_text(_markdown(report))
        print(f"Wrote {args.output} and {args.output.with_suffix('.md')}")

    totals = report["totals"]
    print(
        f"Preflight: {'PASS' if report['ok'] else 'FAIL'}; "
        f"{totals.get('levels', 0)} levels, "
        f"{totals.get('errors', 0)} errors, "
        f"{totals.get('warnings', 0)} warnings"
    )
    for issue in report["issues"]:
        print(
            f"  {issue['severity'].upper():7s} "
            f"{issue['scope']}: {issue['message']}"
        )
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
