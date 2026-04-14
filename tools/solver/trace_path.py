#!/usr/bin/env python3
"""
trace_path.py — Replay a level's goldPath step-by-step and output the board
state after each move, in a canonical format for cross-validation against the
Dart engine.

Usage:
  python3 trace_path.py path/to/level.json [--max-steps N]

Output format (same as engine/bin/trace.dart):
  step=N action=DIRECTION accepted=true|false [noop]
  avatar=(x,y) inventory=none|ITEM
  events: TYPE (x,y) [key=val ...]
"""
import json
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from games.flag_adventure import load, apply, FAState, LevelInfo, ACTIONS


def _fmt_pos(x, y):
    return f"({x},{y})"


def _state_eq(a: FAState, b: FAState) -> bool:
    return (a.ax == b.ax and a.ay == b.ay and
            a.inventory == b.inventory and
            a.rocks == b.rocks and
            a.wood == b.wood and
            a.crates == b.crates and
            a.pickups == b.pickups and
            a.bridges == b.bridges and
            a.ice_cells == b.ice_cells and
            a.extra_water == b.extra_water)


def _fmt_event(ev: dict) -> str:
    t = ev.get("type", "?")
    pos = ev.get("position")
    pos_str = f" {_fmt_pos(*pos)}" if pos else ""
    extra = {k: v for k, v in ev.items()
             if k not in ("type", "position", "animation")}
    extra_str = " " + " ".join(f"{k}={v}" for k, v in sorted(extra.items())) if extra else ""
    return f"  {t}{pos_str}{extra_str}"


def _objects_snapshot(state: FAState) -> dict:
    """Sorted dict of (x,y) -> kind for all objects."""
    result = {}
    for x, y in sorted(state.rocks):
        result[(x, y)] = "rock"
    for x, y in sorted(state.wood):
        result[(x, y)] = "wood"
    for x, y in sorted(state.crates):
        result[(x, y)] = "metal_crate"
    for x, y, kind in sorted(state.pickups):
        result[(x, y)] = kind
    for x, y in sorted(state.bridges):
        result[(x, y)] = "bridge"
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Trace a flag_adventure goldPath step by step")
    parser.add_argument("level", help="Path to level JSON")
    parser.add_argument("--max-steps", type=int, default=None,
                        help="Stop after N steps")
    args = parser.parse_args()

    level_path = Path(args.level)
    if not level_path.exists():
        print(f"Error: {level_path} not found", file=sys.stderr)
        sys.exit(1)

    level_data = json.loads(level_path.read_text())
    gold_path = level_data.get("solution", {}).get("goldPath", [])
    if not gold_path:
        print("No goldPath found in level JSON.", file=sys.stderr)
        sys.exit(1)

    state, info = load(level_data)
    steps = gold_path[:args.max_steps] if args.max_steps else gold_path

    print(f"level={level_data.get('id', '?')}")
    print(f"avatar_start={_fmt_pos(state.ax, state.ay)} inventory=none")
    print()

    for i, step in enumerate(steps, 1):
        direction = step.get("direction", step.get("action", "?"))

        prev_state = state
        new_state, won, events = apply(state, direction, info)

        is_noop = _state_eq(prev_state, new_state) and not won
        noop_str = " noop" if is_noop else ""

        print(f"step={i} action={direction} accepted={'false' if is_noop else 'true'}{noop_str}")
        print(f"avatar={_fmt_pos(new_state.ax, new_state.ay)} inventory={new_state.inventory or 'none'}")

        if events:
            print("events:")
            for ev in events:
                print(_fmt_event(ev))

        state = new_state
        print()

        if won:
            print(f"WON at step={i}")
            break

    else:
        av = _fmt_pos(state.ax, state.ay)
        flag = _fmt_pos(*info.flag)
        won_final = (state.ax, state.ay) == info.flag
        print(f"end avatar={av} flag={flag} won={won_final}")


if __name__ == "__main__":
    main()
