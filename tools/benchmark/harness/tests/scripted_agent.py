#!/usr/bin/env python3
"""A fake agent that exercises the sandbox exactly the way a real one would.

It is handed the moves to play, so it proves nothing about puzzle-solving —
that is the point. It exists to drive every part of the loop (RULES.md, the
socket, ./play, the runner, the engine, the counters) with a known-good script,
so a failure is unambiguously the harness rather than the model.

Reads the moves from argv as one JSON array. Everything else it does the hard
way: shells out to ./play, parses nothing but exit codes and printed text.

Exit codes: 0 finished the script, 1 the run ended early, 2 sandbox is broken.
"""
import json
import subprocess
import sys
from pathlib import Path

PLAY = "./play"


def play(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [PLAY, *args], capture_output=True, text=True, timeout=60
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def main() -> int:
    if not Path("RULES.md").is_file():
        print("no RULES.md in the sandbox", file=sys.stderr)
        return 2
    if not Path(PLAY).is_file():
        print("no play client in the sandbox", file=sys.stderr)
        return 2

    rules = Path("RULES.md").read_text()
    print(f"[agent] read RULES.md ({len(rules)} chars)")

    rc, text = play("state")
    if rc != 0:
        print(f"[agent] ./play state failed rc={rc}: {text}", file=sys.stderr)
        return 2
    print(f"[agent] opening board:\n{text}\n")

    moves = json.loads(sys.argv[1]) if len(sys.argv) > 1 else []
    for i, move in enumerate(moves, start=1):
        rc, text = play("move", json.dumps(move))
        first = text.splitlines()[0] if text else ""
        print(f"[agent] move {i}/{len(moves)} {json.dumps(move)} -> rc={rc} | {first}")
        if rc == 3:
            print(f"[agent] run ended:\n{text}")
            return 0
        if rc != 0:
            print(f"[agent] transport failure: {text}", file=sys.stderr)
            return 2

    rc, text = play("history")
    print(f"[agent] history:\n{text}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
