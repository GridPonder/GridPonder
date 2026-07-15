"""Tests for claim.overwrite — never / always / tagged.

Run from engines/python/:  python test_claim_overwrite.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._turn_engine import TurnEngine
from engines.python._models import Pos


def _make_game(overwrite: dict | None) -> GameDef:
    claim: dict = {
        "layer": "territory",
        "map": {"alpha": "terr_alpha", "beta": "terr_beta"},
    }
    if overwrite is not None:
        claim["overwrite"] = overwrite
    data = {
        "id": "com.gridponder.test_claim_overwrite",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "actors", "occupancy": "zero_or_one"},
            {"id": "territory", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"]},
            "wall": {"layer": "ground", "tags": ["solid"]},
            "contested": {"layer": "ground", "tags": ["walkable", "contested"]},
            "alpha": {"layer": "actors", "tags": ["actor"]},
            "beta": {"layer": "actors", "tags": ["actor"]},
            "terr_alpha": {"layer": "territory", "tags": ["territory"]},
            "terr_beta": {"layer": "territory", "tags": ["territory"]},
        },
        "actions": [
            {"id": "move", "params": {"direction": {"type": "direction",
             "values": ["up", "down", "left", "right"]}}},
        ],
        "systems": [
            {"id": "movement", "type": "coupled_actors", "config": {"claim": claim}},
        ],
    }
    return GameDef.from_dict(data, id="test_claim_overwrite")


def _level(ground_entries, territory_entries, actor_entries, size=(4, 1)):
    return {
        "id": "lvl",
        "board": {
            "size": list(size),
            "layers": {
                "ground": {"format": "sparse", "entries": ground_entries},
                "actors": {"format": "sparse", "entries": actor_entries},
                "territory": {"format": "sparse", "entries": territory_entries},
            },
        },
        "state": {},
        "goals": [],
        "loseConditions": [],
    }


def _owner_at(engine: TurnEngine, x: int, y: int) -> str | None:
    e = engine.state.board.get_entity("territory", Pos(x, y))
    return e.kind if e else None


def test_never_does_not_repaint_owned_cell() -> None:
    """Default: crossing another owner's land is a free transit."""
    game = _make_game(None)
    level = _level([], [{"position": [1, 0], "kind": "terr_beta"}],
                   [{"position": [0, 0], "kind": "alpha"}])
    engine = TurnEngine(game, level)
    engine.execute_turn("move", {"direction": "right"})
    assert _owner_at(engine, 1, 0) == "terr_beta", (
        f"transit must not repaint, got {_owner_at(engine, 1, 0)}"
    )
    print("  OK  never_does_not_repaint_owned_cell")


def test_always_repaints_any_owned_cell() -> None:
    game = _make_game({"mode": "always"})
    level = _level([], [{"position": [1, 0], "kind": "terr_beta"}],
                   [{"position": [0, 0], "kind": "alpha"}])
    engine = TurnEngine(game, level)
    engine.execute_turn("move", {"direction": "right"})
    assert _owner_at(engine, 1, 0) == "terr_alpha", (
        f"always must repaint, got {_owner_at(engine, 1, 0)}"
    )
    print("  OK  always_repaints_any_owned_cell")


def test_tagged_repaints_only_tagged_ground() -> None:
    """Tagged ground is stolen on entry; untagged owned ground is transited."""
    game = _make_game({"mode": "tagged", "tag": "contested"})
    level = _level(
        [{"position": [1, 0], "kind": "contested"}],
        [{"position": [1, 0], "kind": "terr_beta"},
         {"position": [2, 0], "kind": "terr_beta"}],
        [{"position": [0, 0], "kind": "alpha"}],
    )
    engine = TurnEngine(game, level)
    engine.execute_turn("move", {"direction": "right"})
    assert _owner_at(engine, 1, 0) == "terr_alpha", (
        f"tagged cell must be stolen on entry, got {_owner_at(engine, 1, 0)}"
    )
    engine.execute_turn("move", {"direction": "right"})
    assert _owner_at(engine, 2, 0) == "terr_beta", (
        f"plain owned cell must transit unchanged, got {_owner_at(engine, 2, 0)}"
    )
    print("  OK  tagged_repaints_only_tagged_ground")


def test_reentering_own_cell_emits_no_claim_event() -> None:
    """Re-entering your own land is never a re-claim, even when overwritable."""
    game = _make_game({"mode": "always"})
    level = _level([], [{"position": [1, 0], "kind": "terr_alpha"}],
                   [{"position": [0, 0], "kind": "alpha"}])
    engine = TurnEngine(game, level)
    result = engine.execute_turn("move", {"direction": "right"})
    claimed = [e for e in result.events if e["type"] == "cell_claimed"]
    assert not claimed, f"expected no cell_claimed re-entering own land, got {claimed}"
    print("  OK  reentering_own_cell_emits_no_claim_event")


def run_all() -> bool:
    tests = [
        test_never_does_not_repaint_owned_cell,
        test_always_repaints_any_owned_cell,
        test_tagged_repaints_only_tagged_ground,
        test_reentering_own_cell_emits_no_claim_event,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            import traceback
            print(f"  ERROR {t.__name__}: {exc}")
            traceback.print_exc()
            failed += 1
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
