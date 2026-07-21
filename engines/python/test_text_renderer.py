"""
Smoke test for the `territory` layer in the text renderer.

Builds an inline GameDef + level (no pack files) with a `territory` layer
(same shape as engines/python/_fixtures/actor_balance_smoke/), one owned-but-empty cell
and one actor standing on an owned cell, and asserts the rendered text shows
the territory kind's symbol on the empty owned cell and the actor's symbol
(not the territory symbol) where the actor stands.

Run from engines/python/:  python test_text_renderer.py
"""
from __future__ import annotations
import sys
from pathlib import Path

# Make engines/ importable
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._turn_engine import TurnEngine
from engines.python import text_renderer


def _make_game() -> GameDef:
    data = {
        "id": "com.gridponder.test_text_renderer",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "actors", "occupancy": "zero_or_one"},
            {"id": "territory", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"], "symbol": "."},
            "wei": {"layer": "actors", "tags": ["actor"], "symbol": "W"},
            "terr_wei": {"layer": "territory", "tags": ["territory"], "symbol": "1"},
        },
        "actions": [
            {"id": "move", "params": {"direction": {"type": "direction", "values": ["up", "down", "left", "right"]}}},
        ],
        "systems": [
            {"id": "movement", "type": "coupled_actors", "config": {
                "claim": {"layer": "territory", "map": {"wei": "terr_wei"}},
            }},
        ],
    }
    return GameDef.from_dict(data, id="test_text_renderer")


def _make_level() -> dict:
    """3x1 board: (0,0) owned-but-empty cell, (1,0) actor standing on an
    owned cell, (2,0) plain unowned ground."""
    return {
        "id": "test_level",
        "board": {
            "size": [3, 1],
            "layers": {
                "ground": {"format": "sparse", "entries": []},
                "actors": {
                    "format": "sparse",
                    "entries": [{"position": [1, 0], "kind": "wei"}],
                },
                "territory": {
                    "format": "sparse",
                    "entries": [
                        {"position": [0, 0], "kind": "terr_wei"},
                        {"position": [1, 0], "kind": "terr_wei"},
                    ],
                },
            },
        },
        "state": {},
        "goals": [],
        "loseConditions": [],
    }


def test_territory_symbol_shown_on_owned_empty_cell_and_hidden_under_actor() -> None:
    """An owned cell with nothing standing on it renders the territory kind's
    symbol; an owned cell with an actor on it renders the actor's symbol
    instead (territory sits beneath actors in the layer order)."""
    game = _make_game()
    level = _make_level()
    engine = TurnEngine(game, level)

    rendered = text_renderer.render(engine.state, game, include_legend=False)
    lines = rendered.split("\n")
    grid_line = lines[0]

    assert grid_line == "1W.", f"expected '1W.', got {grid_line!r}"
    print("  OK  territory_symbol_shown_on_owned_empty_cell_and_hidden_under_actor")


def run_all() -> bool:
    tests = [
        test_territory_symbol_shown_on_owned_empty_cell_and_hidden_under_actor,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            import traceback
            print(f"  ERROR {t.__name__}: {exc}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
