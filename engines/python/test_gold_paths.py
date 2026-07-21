"""
Smoke test: replay all gold paths for all packs using the Python engine.
Run from engines/python/:  python test_gold_paths.py
Add private/local packs with:  python test_gold_paths.py --extra-packs-dir <dir>
(repeatable; each <dir>'s immediate children must be pack folders, same shape
as packs/).
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

# Make engines/ importable
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python.loader import load_pack
from engines.python._turn_engine import TurnEngine
from engines.python.gold_path import gold_path_actions


PACKS_DIR = ROOT / "packs"

# Throwaway fixture packs (engines/python/_fixtures/<name>/) exercise
# newly-added DSL features end-to-end via a gold path — same manifest/game/
# levels shape as a real pack, but never shipped in the app. Scanned after
# PACKS_DIR so a feature stays under default behavioural-parity CI even
# before a real pack using it exists.
FIXTURES_DIR = Path(__file__).parent / "_fixtures"

PACK_SEARCH_DIRS = [PACKS_DIR, FIXTURES_DIR]


def run_all(extra_packs_dirs: list[Path] | None = None):
    passed = 0
    failed = 0
    skipped = 0

    search_dirs = PACK_SEARCH_DIRS + (extra_packs_dirs or [])

    pack_dirs = [
        pack_dir
        for base_dir in search_dirs
        if base_dir.exists()
        for pack_dir in sorted(base_dir.iterdir())
    ]

    for pack_dir in pack_dirs:
        if not pack_dir.is_dir() or not (pack_dir / "manifest.json").exists():
            continue
        try:
            game, levels = load_pack(pack_dir)
        except Exception as exc:
            print(f"  LOAD ERROR {pack_dir.name}: {exc}")
            failed += 1
            continue

        for level_id, level_json in levels.items():
            gold = gold_path_actions(level_json)
            if not gold:
                skipped += 1
                continue

            try:
                engine = TurnEngine(game, level_json)
                for action_id, params in gold:
                    if engine.is_won:
                        break
                    engine.execute_turn(action_id, params)

                if engine.is_won:
                    print(f"  ✓ {pack_dir.name}/{level_id} ({len(gold)} steps)")
                    passed += 1
                else:
                    print(f"  ✗ {pack_dir.name}/{level_id} — NOT WON after {len(gold)} steps")
                    failed += 1
            except Exception as exc:
                import traceback
                print(f"  ✗ {pack_dir.name}/{level_id} — EXCEPTION: {exc}")
                traceback.print_exc()
                failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    return failed == 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--extra-packs-dir",
        action="append",
        dest="extra_packs_dir",
        default=[],
        help="Directory whose immediate children are pack folders (same shape "
        "as packs/); repeatable.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    extra_dirs = [Path(d) for d in args.extra_packs_dir]
    ok = run_all(extra_packs_dirs=extra_dirs)
    sys.exit(0 if ok else 1)
