"""
Tests for the `balance_regions` system.

Run from the repo root:  python3 engines/python/test_balance_regions.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._turn_engine import TurnEngine

GROUP = {
    "pans": [
        {"name": "west", "groundTags": ["pan_west"]},
        {"name": "east", "groundTags": ["pan_east"]},
    ],
    "weights": {"carriage": 1},
    "avatarWeight": 1,
    "stateVariable": "attitude",
    "leaves": [
        {"marker": "hinge_west", "solidWhen": ["west"], "solidKind": "leaf_plate"},
        {"marker": "hinge_level", "solidWhen": ["level"], "solidKind": "leaf_plate"},
    ],
    "fallVariable": "fell",
}


def _make_game(group: dict | None = None) -> GameDef:
    data = {
        "id": "com.gridponder.test_balance_regions",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "void"},
            {"id": "objects", "occupancy": "zero_or_one"},
            {"id": "actors", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "void": {"layer": "ground", "tags": [], "symbol": " "},
            "deck": {"layer": "ground", "tags": ["walkable"], "symbol": "."},
            "deck_west": {"layer": "ground", "tags": ["walkable", "pan_west"], "symbol": "w"},
            "deck_east": {"layer": "ground", "tags": ["walkable", "pan_east"], "symbol": "e"},
            "leaf_plate": {"layer": "ground", "tags": ["walkable"], "symbol": "="},
            "hinge_west": {"layer": "objects", "tags": [], "symbol": "1"},
            "hinge_level": {"layer": "objects", "tags": [], "symbol": "2"},
            "carriage": {"layer": "actors", "tags": ["npc", "solid"], "symbol": "C"},
        },
        "actions": [
            {"id": "move", "params": {"direction": {"type": "direction",
                                                    "values": ["up", "down", "left", "right"]}}},
            {"id": "wait", "params": {}},
        ],
        "systems": [
            {"id": "walk", "type": "avatar_navigation",
             "config": {"solidHandling": "block", "groundLayer": "ground",
                        "validGroundTags": ["walkable"], "solidLayers": ["objects", "actors"]}},
            {"id": "balance", "type": "balance_regions",
             "config": {"groups": {"hall": group if group is not None else GROUP}}},
        ],
    }
    return GameDef.from_dict(data, id="test_balance_regions")


def _level(ground: list[list[str]], avatar: list[int], *,
           objects: list[dict] | None = None,
           actors: list[dict] | None = None,
           lose: list[dict] | None = None) -> dict:
    return {
        "id": "t",
        "board": {
            "size": [len(ground[0]), len(ground)],
            "layers": {
                "ground": ground,
                "objects": {"format": "sparse", "entries": objects or []},
                "actors": {"format": "sparse", "entries": actors or []},
            },
        },
        "state": {"avatar": {"enabled": True, "position": avatar, "facing": "right"},
                  "variables": {"fell": 0}},
        "goals": [],
        "loseConditions": lose or [],
        "rules": [],
    }


# ground row helpers: W = west pan, E = east pan, N = neutral deck
_W, _E, _N = "deck_west", "deck_east", "deck"


def test_avatar_alone_tips_its_own_pan():
    game = _make_game()
    level = _level([[_W, _W, _N, _E, _E]], avatar=[0, 0])
    eng = TurnEngine(game, level)
    assert eng.state.variables["attitude"] == -1, eng.state.variables


def test_opposite_pans_balance():
    game = _make_game()
    level = _level([[_W, _W, _N, _E, _E]], avatar=[0, 0],
                   actors=[{"position": [4, 0], "kind": "carriage"}])
    eng = TurnEngine(game, level)
    assert eng.state.variables["attitude"] == 0, eng.state.variables


def test_neutral_floor_weighs_nothing():
    game = _make_game()
    level = _level([[_W, _W, _N, _E, _E]], avatar=[2, 0])
    eng = TurnEngine(game, level)
    assert eng.state.variables["attitude"] == 0, eng.state.variables


def test_attitude_follows_the_avatar_across_the_pivot():
    game = _make_game()
    level = _level([[_W, _W, _N, _E, _E]], avatar=[1, 0])
    eng = TurnEngine(game, level)
    assert eng.state.variables["attitude"] == -1
    eng.execute_turn("move", {"direction": "right"})   # onto neutral
    assert eng.state.variables["attitude"] == 0
    eng.execute_turn("move", {"direction": "right"})   # onto the east pan
    assert eng.state.variables["attitude"] == 1


def test_inert_without_groups():
    game = _make_game(group={})
    level = _level([[_W, _W, _N, _E, _E]], avatar=[0, 0])
    eng = TurnEngine(game, level)
    assert "attitude" not in eng.state.variables


def test_leaf_is_solid_only_in_its_attitude():
    from engines.python._models import Pos
    game = _make_game()
    # west pan, neutral, east pan, and a hinge_west leaf beyond the east pan
    level = _level([[_W, _N, _E, "void"]], avatar=[0, 0],
                   objects=[{"position": [3, 0], "kind": "hinge_west"}])
    eng = TurnEngine(game, level)
    # avatar on the west pan -> west down -> the leaf bridges
    assert eng.state.board.get_entity("ground", Pos(3, 0)).kind == "leaf_plate"
    eng.execute_turn("move", {"direction": "right"})   # onto neutral -> level
    assert eng.state.board.get_entity("ground", Pos(3, 0)).kind == "void"


def test_leaf_swap_emits_cell_transformed():
    from engines.python._models import Pos
    game = _make_game()
    level = _level([[_W, _N, _E, "void"]], avatar=[0, 0],
                   objects=[{"position": [3, 0], "kind": "hinge_west"}])
    eng = TurnEngine(game, level)
    result = eng.execute_turn("move", {"direction": "right"})
    swaps = [e for e in result.events if e["type"] == "cell_transformed"]
    assert len(swaps) == 1, swaps
    assert swaps[0]["fromKind"] == "leaf_plate" and swaps[0]["toKind"] == "void"
    assert swaps[0]["position"] == Pos(3, 0)


def test_load_settle_corrects_a_board_authored_in_the_wrong_state():
    from engines.python._models import Pos
    game = _make_game()
    # The level authors the leaf cell as plate, but the opening attitude is
    # level (avatar on neutral floor), so it must be void before turn 1.
    level = _level([[_W, _N, _E, "leaf_plate"]], avatar=[1, 0],
                   objects=[{"position": [3, 0], "kind": "hinge_west"}])
    eng = TurnEngine(game, level)
    assert eng.state.board.get_entity("ground", Pos(3, 0)).kind == "void"


def test_avatar_cannot_walk_onto_an_open_leaf():
    game = _make_game()
    level = _level([[_W, _N, _E, "void"]], avatar=[2, 0],
                   objects=[{"position": [3, 0], "kind": "hinge_west"}])
    eng = TurnEngine(game, level)
    before = eng.state.avatar.position
    eng.execute_turn("move", {"direction": "right"})
    assert eng.state.avatar.position == before


def test_machine_on_a_closing_leaf_is_destroyed():
    from engines.python._models import Pos
    game = _make_game()
    # Avatar on the west pan holds the leaf solid; a carriage sits on the leaf.
    level = _level([[_W, _N, _E, "leaf_plate"]], avatar=[0, 0],
                   objects=[{"position": [3, 0], "kind": "hinge_west"}],
                   actors=[{"position": [3, 0], "kind": "carriage"}])
    eng = TurnEngine(game, level)
    assert eng.state.board.get_entity("actors", Pos(3, 0)) is not None
    result = eng.execute_turn("move", {"direction": "right"})   # step to neutral
    assert eng.state.board.get_entity("actors", Pos(3, 0)) is None
    falls = [e for e in result.events if e["type"] == "entity_fell"]
    assert len(falls) == 1 and falls[0]["kind"] == "carriage", falls


def test_avatar_on_a_closing_leaf_increments_fell_and_loses():
    game = _make_game()
    # A level-leaf under the avatar, and a carriage alone on the west pan: the
    # opening attitude is "west", so the leaf is open and the load settle drops
    # the avatar before turn 1.
    level = _level([[_W, _N, _E, "leaf_plate"]], avatar=[3, 0],
                   objects=[{"position": [3, 0], "kind": "hinge_level"}],
                   actors=[{"position": [0, 0], "kind": "carriage"}],
                   lose=[{"type": "variable_threshold",
                          "config": {"variable": "fell", "target": 1, "comparison": "gte"}}])
    eng = TurnEngine(game, level)
    assert eng.state.variables["fell"] == 1, eng.state.variables
    result = eng.execute_turn("wait", {})
    assert result.is_lost, result.lose_reason


def test_leaf_state_always_agrees_with_the_final_attitude():
    from engines.python._models import Pos
    game = _make_game()
    level = _level([[_W, _N, _E, _E, "leaf_plate"]], avatar=[1, 0],
                   objects=[{"position": [4, 0], "kind": "hinge_west"}],
                   actors=[{"position": [2, 0], "kind": "carriage"}])
    eng = TurnEngine(game, level)
    attitude = eng.state.variables["attitude"]
    ground = eng.state.board.get_entity("ground", Pos(4, 0)).kind
    assert (attitude == -1) == (ground == "leaf_plate"), (attitude, ground)


def run_all() -> bool:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    print(f"Running {len(tests)} balance_regions tests\n{'='*50}")
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  ok {t.__name__}")
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            import traceback
            print(f"  ERROR {t.__name__}: {exc}")
            traceback.print_exc()
            failed += 1
    print(f"\n{'='*50}\nResults: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
