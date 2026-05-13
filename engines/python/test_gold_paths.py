"""
Smoke test: replay all gold paths for all packs using the Python engine.
Run from engines/python/:  python test_gold_paths.py
Use --extra-packs-dir <path> to also test packs in a second directory (e.g. packs-private/).
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


def _iter_pack_dirs(*dirs: Path):
    for d in dirs:
        if not d.is_dir():
            continue
        yield from (p for p in sorted(d.iterdir()) if p.is_dir() and (p / "manifest.json").exists())


def run_all(extra_packs_dir: Path | None = None):
    passed = 0
    failed = 0
    skipped = 0

    search_dirs = [PACKS_DIR] + ([extra_packs_dir] if extra_packs_dir else [])
    for pack_dir in _iter_pack_dirs(*search_dirs):
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay all gold paths")
    parser.add_argument("--extra-packs-dir", type=Path, default=None,
                        help="Additional packs directory to include (e.g. packs-private/)")
    args = parser.parse_args()
    ok = run_all(extra_packs_dir=args.extra_packs_dir)
    sys.exit(0 if ok else 1)
