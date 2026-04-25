#!/usr/bin/env python3
"""
One-off cleanup for legacy crashed-runner records.

Before bench.py learned to write ``error: "runner exited without won/lost
event"`` on subprocess crash, it fabricated a synthetic "lost" event with
``gold_path_length: 0``. This script walks the historical JSONL output and
adds an ``error`` field to those rows so they are filtered from stats and
charts in aggregate.py.

Idempotent: rows that already carry ``error`` are left untouched.
"""
from __future__ import annotations
import json
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results" / "run"
LEGACY_ERROR = "legacy: runner exited without won/lost event (gold_path_length=0 sentinel)"


def main() -> None:
    total_files = 0
    total_fixed = 0
    for jsonl in sorted(RESULTS_DIR.glob("**/*.jsonl")):
        out_lines: list[str] = []
        fixed = 0
        with open(jsonl) as f:
            for line in f:
                stripped = line.rstrip("\n")
                if not stripped.strip():
                    out_lines.append(stripped)
                    continue
                rec = json.loads(stripped)
                if (
                    rec.get("type") == "level"
                    and rec.get("gold_path_length") == 0
                    and "error" not in rec
                ):
                    rec["error"] = LEGACY_ERROR
                    fixed += 1
                out_lines.append(json.dumps(rec))
        if fixed > 0:
            jsonl.write_text("\n".join(out_lines) + "\n")
            total_files += 1
            total_fixed += fixed
            print(f"  {jsonl.relative_to(RESULTS_DIR)}: marked {fixed}")
    print(f"\nFixed {total_fixed} rows across {total_files} files.")


if __name__ == "__main__":
    main()
