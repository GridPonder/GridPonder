#!/usr/bin/env python3
"""
trace_path.py — Replay a level's goldPath step-by-step and output the board
state after each move, in a canonical format for cross-validation against the
Dart engine (engines/dart/bin/trace.dart).

Works with any GridPonder game pack (carrot_quest, diagonal_swipes, etc.).

Usage:
  python3 trace_path.py path/to/level.json [--max-steps N]

  The level's pack is detected automatically from the file path.

Output format (same as engines/dart/bin/trace.dart):
  level=LEVEL_ID
  avatar_start=(x,y) inventory=none

  step=N action=DIRECTION accepted=true|false [noop]
  avatar=(x,y) inventory=none|ITEM
  events:
    TYPE (x,y) [key=val ...]

  WON at step=N
  -- or --
  end avatar=(x,y) flag=(x,y) won=true|false
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import engine_adapter as ea
from engine_adapter import EngineState, EngineInfo

# Make engines/ importable for Pos type check
_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from engines.python._models import Pos


def _fmt_pos(pos) -> str:
    """Format a Pos or (x, y) as '(x,y)'."""
    if pos is None:
        return "(?,?)"
    if hasattr(pos, "x"):
        return f"({pos.x},{pos.y})"
    return f"({pos[0]},{pos[1]})"


def _fmt_event(ev: dict) -> str:
    t = ev.get("type", "?")
    pos = ev.get("position")
    pos_str = f" {_fmt_pos(pos)}" if pos else ""
    extra = {}
    for k, v in ev.items():
        if k in ("type", "position", "animation"):
            continue
        if isinstance(v, (dict, list)):
            continue  # skip complex values (mirrors Dart behaviour)
        if isinstance(v, Pos):
            extra[k] = f"({v.x}, {v.y})"  # Match Dart's Position.toString()
            continue
        # opType is stored as a separate payload key named "type" in Dart
        display_key = "type" if k == "opType" else k
        extra[display_key] = v
    def _fmt_val(v):
        if v is None:
            return "null"
        if v is True:
            return "true"
        if v is False:
            return "false"
        return v
    extra_str = (" " + " ".join(f"{k}={_fmt_val(v)}" for k, v in extra.items())
                 if extra else "")
    return f"  {t}{pos_str}{extra_str}"


def _state_unchanged(prev: EngineState, curr: EngineState) -> bool:
    """Quick heuristic: same state key means nothing changed."""
    return prev == curr


def _find_flag(state: EngineState) -> str:
    markers = state.game_state.board.layers.get("markers")
    if markers is None:
        return "?"
    for pos, entity in markers.entries():
        if entity.kind == "flag":
            return _fmt_pos(pos)
    return "?"


def _action_label(entry: dict | str) -> str:
    """Return the human-readable action label used in trace output.

    For direction-based actions, return the direction (e.g. 'up').
    For param-less actions, return the action_id (e.g. 'flood_red').
    """
    if isinstance(entry, str):
        return entry
    direction = entry.get("direction")
    if direction:
        return direction
    return entry.get("action", "?")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay a level's goldPath step-by-step (any game).")
    parser.add_argument("level", help="Path to level JSON")
    parser.add_argument("--max-steps", type=int, default=None,
                        help="Stop after N steps")
    args = parser.parse_args()

    level_path = Path(args.level)
    if not level_path.exists():
        print(f"Error: {level_path} not found", file=sys.stderr)
        sys.exit(1)

    level_json = json.loads(level_path.read_text())
    gold_raw = level_json.get("solution", {}).get("goldPath", [])
    if not gold_raw:
        print("No goldPath found in level JSON.", file=sys.stderr)
        sys.exit(1)

    pack_dir = level_path.parent.parent  # levels/xxx.json → pack root
    state, info = ea.load(level_json, pack_dir)
    gold_actions = ea.gold_path_actions(level_json)  # flat strings

    steps_raw = gold_raw[:args.max_steps] if args.max_steps else gold_raw
    steps_flat = gold_actions[:args.max_steps] if args.max_steps else gold_actions

    av = state.game_state.avatar
    start_pos = _fmt_pos(av.position) if av.enabled else "(?,?)"
    print(f"level={level_json.get('id', '?')}")
    print(f"avatar_start={start_pos} inventory=none")
    print()

    for i, (raw_entry, action_str) in enumerate(zip(steps_raw, steps_flat), 1):
        label = _action_label(raw_entry)
        prev_state = state
        new_state, won, events = ea.apply(state, action_str, info)

        is_noop = _state_unchanged(prev_state, new_state) and not won
        noop_str = " noop" if is_noop else ""

        av_new = new_state.game_state.avatar
        pos_str = _fmt_pos(av_new.position) if av_new.enabled else "(?,?)"
        inv = av_new.item or "none"

        print(f"step={i} action={label} accepted={'false' if is_noop else 'true'}{noop_str}")
        print(f"avatar={pos_str} inventory={inv}")

        if events:
            print("events:")
            for ev in events:
                print(_fmt_event(ev))

        state = new_state
        print()

        if won:
            print(f"WON at step={i}")
            return

    flag_str = _find_flag(state)
    av_final = state.game_state.avatar
    final_pos = _fmt_pos(av_final.position) if av_final.enabled else "(?,?)"
    print(f"end avatar={final_pos} flag={flag_str} won={state.game_state.is_won}")


if __name__ == "__main__":
    main()
