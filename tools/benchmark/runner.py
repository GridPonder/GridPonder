#!/usr/bin/env python3
"""Python game-loop runner for AI benchmarking.

Drop-in replacement for the compiled Dart runner (runner/runner).
Communicates via newline-delimited JSON on stdin/stdout — same protocol.

stdout → orchestrator: state / reset / rejected / won / lost events
stdin  ← orchestrator:
  single mode:  {"action": "...", ...params, "memory": "..."}
  other modes:  {"actions": [...], "memory": "..."} or single format

Usage (same flags as the Dart runner):
  python runner.py --pack number_cells --level nc_001 \\
      --packs-dir /path/to/packs \\
      --attempt-multiplier 2 --total-multiplier 3 --mode single
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the repo root importable so engines/python is on the path.
_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from engines.python.loader import load_pack
from engines.python._turn_engine import TurnEngine
from engines.python.text_renderer import render as render_board
from engines.python.observation import build_prompt
from engines.python.anon import build_anon_kind_to_label, build_anon_reverse_map
from engines.python.action_enum import enumerate_actions
from engines.python.gold_path import gold_path_length

_PACKS_DIR = _REPO_ROOT / "packs"
_MAX_CONSECUTIVE_REJECTIONS = 5


def _out(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


def _die(msg: str) -> None:
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Python GridPonder benchmark runner")
    parser.add_argument("--pack", "-p", required=True, help="Pack ID")
    parser.add_argument("--level", "-l", required=True, help="Level ID")
    parser.add_argument("--packs-dir", default=None, help="Absolute path to packs/ directory")
    parser.add_argument("--attempt-multiplier", type=int, default=2)
    parser.add_argument("--total-multiplier", type=int, default=3)
    parser.add_argument(
        "--mode",
        choices=["single", "fixed-n", "flex-n", "full"],
        default="single",
    )
    parser.add_argument("--step-size", type=int, default=1)
    parser.add_argument("--max-n", type=int, default=None)
    parser.add_argument("--anon", action="store_true", default=False)
    args = parser.parse_args()

    pack_id: str = args.pack
    level_id: str = args.level
    packs_dir = Path(args.packs_dir) if args.packs_dir else _PACKS_DIR
    attempt_mul: int = args.attempt_multiplier
    total_mul: int = args.total_multiplier
    mode: str = args.mode
    step_size: int = args.step_size
    max_n: int | None = args.max_n
    anon: bool = args.anon

    # ── Load pack ─────────────────────────────────────────────────────────────
    pack_dir = packs_dir / pack_id
    try:
        game_def, levels = load_pack(pack_dir)
    except Exception as e:
        _die(f'Cannot load pack "{pack_id}": {e}')
        return

    if level_id not in levels:
        _die(f'Level "{level_id}" not found in pack "{pack_id}".')
        return

    level_def = levels[level_id]
    gold_path_len = gold_path_length(level_def)

    limit_per_attempt = (
        attempt_mul * gold_path_len if gold_path_len > 0 else max(10, min(attempt_mul * 10, 60))
    )
    limit_total = (
        total_mul * gold_path_len if gold_path_len > 0 else max(10, min(total_mul * 10, 100))
    )

    # Anon mode: build stable kind→label map for the whole run.
    kind_symbol_overrides: dict[str, str] | None = (
        build_anon_kind_to_label(game_def) if anon else None
    )

    engine = TurnEngine(game_def, level_def)

    attempt_number = 1
    total_game_actions = 0
    give_up_count = 0
    memory = ""
    consecutive_rejections = 0

    last_action: dict | None = None
    prev_board_text: str | None = None
    prev_inventory: str | None = None
    current_anon_map: dict[str, dict] = {}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def emit_state() -> None:
        nonlocal current_anon_map
        total_now = total_game_actions + give_up_count
        valid_actions = enumerate_actions(game_def, engine.state)

        if anon:
            current_anon_map = build_anon_reverse_map(valid_actions)

        prompt = build_prompt(
            game_def,
            level_def,
            engine.state,
            attempt_number=attempt_number,
            total_actions=total_now,
            last_action=last_action,
            previous_board_text=prev_board_text,
            previous_inventory=prev_inventory,
            anonymize=anon,
            kind_symbol_overrides=kind_symbol_overrides,
            inference_mode=mode,
            step_size=step_size,
            max_n=max_n,
            memory=memory,
        )

        event: dict = {
            "event": "state",
            "prompt": prompt,
            "valid_actions": [*valid_actions, {"action": "give_up"}],
            "actions_this_attempt": engine.state.action_count,
            "actions_total": total_now,
            "action_limit_per_attempt": limit_per_attempt,
            "action_limit": limit_total,
            "attempt": attempt_number,
            "gold_path_length": gold_path_len,
            "level_id": level_id,
            "pack_id": pack_id,
            "inference_mode": mode,
        }
        if mode == "fixed-n":
            event["step_size"] = step_size
        elif mode == "flex-n":
            event["max_n"] = max_n
        _out(event)

    def do_reset(reason: str) -> None:
        nonlocal attempt_number, last_action, prev_board_text, prev_inventory
        engine.reset()
        attempt_number += 1
        last_action = None
        prev_board_text = None
        prev_inventory = None
        _out({
            "event": "reset",
            "attempt": attempt_number,
            "reason": reason,
            "actions_total": total_game_actions + give_up_count,
        })

    def won_event() -> dict:
        return {
            "event": "won",
            "actions_this_attempt": engine.state.action_count,
            "actions_total": total_game_actions + give_up_count,
            "attempts": attempt_number,
            "gold_path_length": gold_path_len,
        }

    def lost_event() -> dict:
        return {
            "event": "lost",
            "actions_this_attempt": engine.state.action_count,
            "actions_total": total_game_actions + give_up_count,
            "attempts": attempt_number,
            "gold_path_length": gold_path_len,
        }

    # ── Initial state ─────────────────────────────────────────────────────────
    emit_state()

    # ── Main loop ─────────────────────────────────────────────────────────────
    for raw_line in sys.stdin:
        trimmed = raw_line.strip()
        if not trimmed:
            continue
        try:
            inp: dict = json.loads(trimmed)
        except json.JSONDecodeError:
            print(f"Bad JSON from orchestrator: {trimmed}", file=sys.stderr)
            continue

        mem_update = inp.get("memory")
        if mem_update is not None:
            memory = mem_update

        # ── single mode ───────────────────────────────────────────────────────
        if mode == "single":
            action_id: str | None = inp.get("action")
            if action_id is None:
                print(f'Missing "action" field: {trimmed}', file=sys.stderr)
                continue

            if action_id == "give_up":
                consecutive_rejections = 0
                give_up_count += 1
                total_now = total_game_actions + give_up_count
                do_reset(reason="voluntary")
                if total_now >= limit_total:
                    _out(lost_event())
                    break
                emit_state()
                continue

            prev_board_text = render_board(
                engine.state, game_def, include_legend=False,
                kind_symbol_overrides=kind_symbol_overrides,
            )
            prev_inventory = engine.state.avatar.item if engine.state.avatar.enabled else None

            # Anon mode: reverse-map label to real action params.
            if anon:
                real = current_anon_map.get(action_id)
                if real is None:
                    prev_board_text = None
                    prev_inventory = None
                    consecutive_rejections += 1
                    _out({"event": "rejected", "action": inp})
                    if consecutive_rejections >= _MAX_CONSECUTIVE_REJECTIONS:
                        _out(lost_event())
                        break
                    emit_state()
                    continue
                game_action_id = real["action"]
                game_params = {k: v for k, v in real.items() if k != "action"}
            else:
                game_action_id = action_id
                game_params = {k: v for k, v in inp.items() if k not in ("action", "memory")}

            result = engine.execute_turn(game_action_id, game_params)

            if not result.accepted:
                prev_board_text = None
                prev_inventory = None
                consecutive_rejections += 1
                _out({"event": "rejected", "action": inp})
                if consecutive_rejections >= _MAX_CONSECUTIVE_REJECTIONS:
                    _out(lost_event())
                    break
                emit_state()
                continue

            consecutive_rejections = 0
            last_action = {k: v for k, v in inp.items() if k != "memory"} if not anon else real
            total_game_actions += 1
            total_now = total_game_actions + give_up_count

            if engine.is_won:
                _out(won_event())
                break
            if engine.is_lost:
                _out(lost_event())
                break
            if engine.state.action_count >= limit_per_attempt:
                do_reset(reason="limit")
            if total_now >= limit_total:
                _out(lost_event())
                break
            emit_state()
            continue

        # ── multi-action modes ────────────────────────────────────────────────
        actions = _extract_action_list(
            inp,
            max_allowed=(
                step_size if mode == "fixed-n" else (max_n if mode == "flex-n" else None)
            ),
        )

        if not actions:
            print(f"No valid actions found in input: {trimmed}", file=sys.stderr)
            continue

        outer_break = False
        for action_input in actions:
            action_id = action_input.get("action")
            if action_id is None:
                continue

            if action_id == "give_up":
                consecutive_rejections = 0
                if mode == "full":
                    _out(lost_event())
                    outer_break = True
                else:
                    give_up_count += 1
                    total_now = total_game_actions + give_up_count
                    do_reset(reason="voluntary")
                    if total_now >= limit_total:
                        _out(lost_event())
                        outer_break = True
                break

            prev_board_text = render_board(
                engine.state, game_def, include_legend=False,
                kind_symbol_overrides=kind_symbol_overrides,
            )
            prev_inventory = engine.state.avatar.item if engine.state.avatar.enabled else None

            if anon:
                real = current_anon_map.get(action_id)
                if real is None:
                    prev_board_text = None
                    prev_inventory = None
                    consecutive_rejections += 1
                    _out({"event": "rejected", "action": action_input})
                    if consecutive_rejections >= _MAX_CONSECUTIVE_REJECTIONS:
                        _out(lost_event())
                        outer_break = True
                    break
                game_action_id = real["action"]
                game_params = {k: v for k, v in real.items() if k != "action"}
            else:
                game_action_id = action_id
                game_params = {
                    k: v for k, v in action_input.items() if k not in ("action", "memory")
                }

            result = engine.execute_turn(game_action_id, game_params)

            if not result.accepted:
                prev_board_text = None
                prev_inventory = None
                consecutive_rejections += 1
                _out({"event": "rejected", "action": action_input})
                if consecutive_rejections >= _MAX_CONSECUTIVE_REJECTIONS:
                    _out(lost_event())
                    outer_break = True
                break

            consecutive_rejections = 0
            last_action = action_input if not anon else real
            total_game_actions += 1
            total_now = total_game_actions + give_up_count

            if engine.is_won:
                _out(won_event())
                outer_break = True
                break
            if engine.is_lost:
                _out(lost_event())
                outer_break = True
                break

            if mode != "full" and engine.state.action_count >= limit_per_attempt:
                do_reset(reason="limit")
                if total_now >= limit_total:
                    _out(lost_event())
                    outer_break = True
                break

            if total_now >= limit_total:
                _out(lost_event())
                outer_break = True
                break

        if outer_break:
            break

        if mode == "full":
            _out(lost_event())
            break

        emit_state()


def _extract_action_list(inp: dict, max_allowed: int | None) -> list[dict]:
    raw: list | None = None
    if "actions" in inp:
        raw = inp["actions"]
    elif "action" in inp:
        raw = [inp]
    if not raw:
        return []
    actions = [a for a in raw if isinstance(a, dict) and "action" in a]
    if max_allowed is not None:
        actions = actions[:max_allowed]
    return actions


if __name__ == "__main__":
    main()
