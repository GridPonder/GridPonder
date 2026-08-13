#!/usr/bin/env python3
"""A free, deterministic player used to exercise the harness end to end.

It is not a benchmark subject. Its job is to make the sweep and the report
testable without spending tokens: it reads RULES.md exactly as a model would,
extracts the action shapes, and plays pseudo-random well-formed JSON until the
run ends. That reliably produces losses, retries, illegal moves and the odd
accidental solve, which is the full range the report has to render.

Stdlib only, and it talks to the game solely through ./play — so if this can
play, a model in the same sandbox can too. A failure here is a harness bug, not
a model result.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from pathlib import Path

PLAY = "./play"
_SHAPE_RE = re.compile(r"^Shape: `(.+)`$", re.MULTILINE)
_ENUM_RE = re.compile(r"^- `([^`]+)` — one of: (.+)$", re.MULTILINE)
_POSITION_RE = re.compile(r"^- `([^`]+)` — a `\[x, y\]` board coordinate$", re.MULTILINE)
_ACTION_BLOCK_RE = re.compile(r"^### `([^`]+)`$", re.MULTILINE)


def play(*args: str) -> tuple[str, bool]:
    """Run one ./play command. Returns (text, run_is_over)."""
    proc = subprocess.run([PLAY, *args], capture_output=True, text=True)
    # 3 is the client's "the run is over" code; 2 is a transport failure.
    return proc.stdout, proc.returncode == 3


def parse_actions(rules: str) -> list[dict]:
    """Recover the action shapes from RULES.md.

    Parsed from the rendered document rather than the pack, so this agent is
    held to the same information the model gets. If RULES.md becomes
    unparseable to this, it has probably become unparseable to a model too.
    """
    blocks = _ACTION_BLOCK_RE.split(rules)[1:]
    actions = []
    for name, body in zip(blocks[::2], blocks[1::2]):
        shape_match = _SHAPE_RE.search(body)
        if not shape_match:
            continue
        try:
            shape = json.loads(shape_match.group(1))
        except ValueError:
            continue
        enums = {k: [v.strip() for v in vals.split(",")]
                 for k, vals in _ENUM_RE.findall(body)}
        positions = _POSITION_RE.findall(body)
        actions.append({
            "id": name,
            "params": [k for k in shape if k != "action"],
            "enums": enums,
            "positions": positions,
        })
    return actions


def board_size(state_text: str) -> tuple[int, int]:
    """Infer grid dimensions from the rendered board.

    The board is the run of equal-length lines between the goal line and the
    legend. Guessing wrong only costs a rejected move, which is exactly what an
    agent reading the same text would experience.
    """
    rows = [ln for ln in state_text.splitlines()
            if ln and not ln.startswith(("Attempt", "Goal:", "Each character",
                                         "Legend:", "Stacked", "  ("))]
    widths = {}
    for row in rows:
        widths.setdefault(len(row), []).append(row)
    if not widths:
        return 8, 8
    width, matching = max(widths.items(), key=lambda kv: len(kv[1]))
    return width, len(matching)


def choose(rng: random.Random, action: dict, size: tuple[int, int]) -> dict:
    move = {"action": action["id"]}
    width, height = size
    for param in action["params"]:
        if param in action["enums"]:
            move[param] = rng.choice(action["enums"][param])
        elif param in action["positions"]:
            move[param] = [rng.randrange(width), rng.randrange(height)]
        else:
            move[param] = 0
    return move


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-moves", type=int, default=400)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    rules = Path("RULES.md").read_text(encoding="utf-8")
    actions = parse_actions(rules)
    if not actions:
        print("baseline: could not parse any action from RULES.md", file=sys.stderr)
        return 2

    state, over = play("state")
    size = board_size(state)
    print(f"baseline: {len(actions)} action shape(s), board looks {size[0]}x{size[1]}")

    for i in range(args.max_moves):
        if over:
            break
        move = choose(rng, rng.choice(actions), size)
        state, over = play("move", json.dumps(move))
        # Re-read the board size after a reset: a new attempt renders the
        # starting board, which is the same size, but a pack could differ.
        if "starting position" in state:
            size = board_size(state)
    print(f"baseline: stopped after {i + 1} move(s); run over = {over}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
