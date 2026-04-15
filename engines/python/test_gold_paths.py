"""
Smoke test: replay all gold paths for all packs using the Python engine.
Run from engines/python/:  python test_gold_paths.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

# Make engines/ importable
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python.loader import load_pack
from engines.python._turn_engine import TurnEngine


PACKS_DIR = ROOT / "packs"

PACK_LEVELS = {
    "flag_adventure": [
        "fw_001","fw_002","fw_003","fw_004","fw_005","fw_006",
        "pw_001","pw_003","fw_007",
        "fw_ice_002","fw_ice_003","fw_ice_005","fw_ice_006",
        "fw_ice_007","fw_ice_008","fw_ice_011",
        "fw_ice_012","fw_ice_013","fw_ice_014","fw_ice_015",
    ],
    "number_cells": [f"nc_{i:03d}" for i in range(1, 21)],
    "rotate_flip": ["rf_001","rf_002"],
    "flood_colors": ["fl_001","fl_002","fl_003"],
    "diagonal_swipes": ["ds_001","ds_002"],
    "box_builder": [],  # will collect dynamically
}


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
            actions.append(("move", {"direction": entry}))
    return actions


def run_all():
    passed = 0
    failed = 0
    skipped = 0

    for pack_name, level_ids in PACK_LEVELS.items():
        pack_dir = PACKS_DIR / pack_name
        if not pack_dir.exists():
            continue

        try:
            game, levels = load_pack(pack_dir)
        except Exception as exc:
            print(f"  LOAD ERROR {pack_name}: {exc}")
            failed += 1
            continue

        # If no level list specified, collect all levels with gold paths
        ids_to_test = level_ids or list(levels.keys())

        for level_id in ids_to_test:
            level_json = levels.get(level_id)
            if level_json is None:
                skipped += 1
                continue

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
                    print(f"  ✓ {pack_name}/{level_id} ({len(gold)} steps)")
                    passed += 1
                else:
                    print(f"  ✗ {pack_name}/{level_id} — NOT WON after {len(gold)} steps")
                    failed += 1
            except Exception as exc:
                import traceback
                print(f"  ✗ {pack_name}/{level_id} — EXCEPTION: {exc}")
                traceback.print_exc()
                failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
