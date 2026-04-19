"""
Smoke test: replay all gold paths for all packs using the Python engine.
Run from engines/python/:  python test_gold_paths.py
"""
from __future__ import annotations
import sys
from pathlib import Path

# Make engines/ importable
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python.loader import load_pack
from engines.python._turn_engine import TurnEngine


PACKS_DIR = ROOT / "packs"


def gold_path_actions(level_json: dict) -> list[tuple[str, dict]]:
    """Return list of (action_id, params) from goldPath."""
    gold_raw = level_json.get("solution", {}).get("goldPath", [])
    actions = []
    for entry in gold_raw:
        if isinstance(entry, dict):
            action_type = entry.get("action", "move")
            direction = entry.get("direction")
            params: dict = {}
            if direction:
                params["direction"] = direction
            for k, v in entry.items():
                if k not in ("action", "direction"):
                    params[k] = v
            actions.append((action_type, params))
        elif isinstance(entry, str):
            _cardinals = {"up", "down", "left", "right"}
            if entry in _cardinals:
                actions.append(("move", {"direction": entry}))
            else:
                actions.append((entry, {}))
    return actions


def run_all():
    passed = 0
    failed = 0
    skipped = 0

    for pack_dir in sorted(PACKS_DIR.iterdir()):
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


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
