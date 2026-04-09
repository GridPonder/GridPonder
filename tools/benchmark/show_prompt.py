#!/usr/bin/env python3
"""Dump the LLM prompt for any level to stdout.

Usage:
  python show_prompt.py <pack_id> <level_id>
  python show_prompt.py number_cells nc_005
  python show_prompt.py box_builder bb_008
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
RUNNER_BIN = SCRIPT_DIR / "runner" / "runner"
PACKS_DIR = SCRIPT_DIR.parent.parent / "packs"


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    pack_id, level_id = sys.argv[1], sys.argv[2]

    if not RUNNER_BIN.exists():
        sys.exit("Runner binary not found. Run: make benchmark-build")

    proc = subprocess.Popen(
        [str(RUNNER_BIN), "--pack", pack_id, "--level", level_id,
         "--packs-dir", str(PACKS_DIR)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Send a dummy line so the runner's stdin loop exits cleanly.
    stdout, _ = proc.communicate(input="x\n", timeout=10)

    first_line = stdout.splitlines()[0] if stdout.strip() else ""
    if not first_line:
        sys.exit(f"Runner produced no output. Check pack/level IDs.")

    event = json.loads(first_line)
    print(event["prompt"])


if __name__ == "__main__":
    main()
