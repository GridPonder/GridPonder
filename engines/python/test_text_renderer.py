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
from engines.python._models import Entity, Pos
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


def test_whitespace_symbol_is_rendered_visibly() -> None:
    game = GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "void"}
            ],
            "entityKinds": {
                "void": {
                    "layer": "ground",
                    "symbol": " ",
                    "uiName": "Open air",
                }
            },
        }
    )
    level = {
        "board": {"size": [2, 1], "layers": {}},
        "state": {"avatar": {"enabled": False}},
        "goals": [],
    }

    rendered = text_renderer.render(
        TurnEngine(game, level).state, game, include_legend=False
    )
    assert rendered.splitlines()[0] == "··"


def test_entity_state_includes_non_symbol_parameters() -> None:
    game = GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
                {"id": "actors", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "empty": {"layer": "ground", "symbol": "."},
                "watcher": {
                    "layer": "actors",
                    "symbol": "W",
                    "uiName": "Watcher",
                },
            },
        }
    )
    level = {
        "board": {
            "size": [2, 1],
            "layers": {
                "actors": {
                    "format": "sparse",
                    "entries": [
                        {
                            "position": [1, 0],
                            "kind": "watcher",
                            "behavior": "stalk",
                            "gaze": "left",
                        }
                    ],
                }
            },
        },
        "state": {"avatar": {"enabled": False}},
        "goals": [],
    }

    rendered = text_renderer.render(TurnEngine(game, level).state, game)
    assert "(1,0) Watcher: behavior=stalk, gaze=left" in rendered


def test_anonymous_entity_state_preserves_dynamics_without_kind_name() -> None:
    game = GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
                {"id": "actors", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "empty": {"layer": "ground", "symbol": "."},
                "watcher": {
                    "layer": "actors",
                    "symbol": "W",
                    "uiName": "Watcher",
                },
            },
        }
    )
    level = {
        "board": {
            "size": [2, 1],
            "layers": {
                "actors": {
                    "format": "sparse",
                    "entries": [
                        {
                            "position": [1, 0],
                            "kind": "watcher",
                            "behavior": "stalk",
                            "gaze": "left",
                        }
                    ],
                }
            },
        },
        "state": {"avatar": {"enabled": False}},
        "goals": [],
    }

    rendered = text_renderer.render(
        TurnEngine(game, level).state,
        game,
        kind_symbol_overrides={"watcher": "A"},
    )
    assert "(1,0) A: behavior=stalk, gaze=left" in rendered
    assert "Watcher" not in rendered


def _make_elastic_game() -> GameDef:
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
                {"id": "markers", "occupancy": "zero_or_one"},
                {"id": "objects", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "floor": {"layer": "ground", "symbol": "."},
                "target": {
                    "layer": "markers",
                    "symbol": "1",
                    "uiName": "Target 1",
                },
                "wall": {
                    "layer": "objects",
                    "symbol": "X",
                    "uiName": "Completed target wall",
                },
                "elastic_block": {
                    "layer": "structures",
                    "symbol": "B",
                    "uiName": "Bellows",
                },
            },
            "systems": [
                {
                    "id": "bellows_motion",
                    "type": "elastic_block",
                    "config": {
                        "objectKind": "elastic_block",
                        "targets": [
                            {
                                "id": "target_1",
                                "markerKind": "target",
                                "onLeave": "wall",
                                "wallKind": "wall",
                            }
                        ],
                    },
                }
            ],
        }
    )


def _make_elastic_level() -> dict:
    return {
        "id": "elastic",
        "board": {
            "size": [3, 1],
            "layers": {
                "markers": {
                    "format": "sparse",
                    "entries": [{"position": [1, 0], "kind": "target"}],
                }
            },
            "multiCellObjects": [
                {
                    "id": "bellows",
                    "kind": "elastic_block",
                    "cells": [[1, 0]],
                }
            ],
        },
        "state": {
            "variables": {
                "completedTargetIds": ["target_1"],
                "consumedTargetIds": [],
                "completedTargetCount": 1,
            },
            "avatar": {"enabled": False},
        },
        "goals": [],
    }


def test_multi_cell_legend_and_overlap_use_public_game_identity() -> None:
    game = _make_elastic_game()
    level = _make_elastic_level()
    engine = TurnEngine(game, level)
    rendered = text_renderer.render(
        engine.state, game, level_def=level
    )
    assert "║/═/╬=Bellows body" in rendered
    assert "pipe body" not in rendered
    assert "pipe exit" not in rendered
    assert "1(Target 1) + ╬(Bellows)" in rendered
    assert "completed, still occupied by Bellows" in rendered
    assert "becomes a wall only after the Bellows fully vacates it" in rendered


def test_consumed_target_reports_original_geometry_and_wall_state() -> None:
    game = _make_elastic_game()
    level = _make_elastic_level()
    engine = TurnEngine(game, level)
    engine.state.board.set_entity("markers", Pos(1, 0), None)
    engine.state.board.set_entity("objects", Pos(1, 0), Entity("wall"))
    engine.state.board.multi_cell_objects[0].cells = [Pos(2, 0)]
    engine.state.variables["consumedTargetIds"] = ["target_1"]
    rendered = text_renderer.render(
        engine.state, game, level_def=level
    )
    assert "Target 1 [1]: cells (1,0)" in rendered
    assert "completed and converted to Completed target wall" in rendered


def _make_occlusion_game() -> GameDef:
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
                {"id": "objects", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "floor": {"layer": "ground", "symbol": ".", "uiName": "Open floor"},
                "parking": {
                    "layer": "ground",
                    "symbol": ":",
                    "uiName": "Hidden parking floor",
                },
                "key": {
                    "layer": "objects",
                    "symbol": "K",
                    "uiName": "Yellow key",
                },
                "door": {
                    "layer": "objects",
                    "symbol": "L",
                    "uiName": "Locked door",
                },
                "slab": {
                    "layer": "structures",
                    "tags": ["observation_occluder", "public_piece"],
                    "symbol": "B",
                    "uiName": "Blue slab",
                },
            },
        }
    )


def _make_occlusion_level() -> dict:
    return {
        "board": {
            "size": [4, 1],
            "layers": {
                "ground": {
                    "format": "sparse",
                    "entries": [
                        {"position": [0, 0], "kind": "parking"},
                        {"position": [1, 0], "kind": "parking"},
                    ],
                },
                "objects": {
                    "format": "sparse",
                    "entries": [
                        {
                            "position": [0, 0],
                            "kind": "key",
                            "owner": "yellow",
                        },
                        {"position": [1, 0], "kind": "door"},
                    ],
                },
            },
            "multiCellObjects": [
                {
                    "id": "slab_f_yellow_key",
                    "kind": "slab",
                    "cells": [[0, 0], [1, 0]],
                    "params": {"axis": "horizontal"},
                }
            ],
        },
        "state": {"avatar": {"enabled": False}},
        "goals": [],
    }


def test_occluding_public_piece_hides_then_reveals_board_contents() -> None:
    game = _make_occlusion_game()
    engine = TurnEngine(game, _make_occlusion_level())

    concealed = text_renderer.render(engine.state, game)
    assert concealed.splitlines()[0] == "══.."
    for leaked in (
        "Yellow key",
        "Locked door",
        "Hidden parking floor",
        "owner=yellow",
        "slab_f_yellow_key",
    ):
        assert leaked not in concealed, f"concealed observation leaked {leaked!r}"
    assert "Piece 1 [Blue slab]" in concealed
    assert "axis: horizontal" in concealed
    assert "footprint: (0,0) (1,0)" in concealed

    engine.state.board.multi_cell_objects[0].cells = [Pos(2, 0), Pos(3, 0)]
    revealed = text_renderer.render(engine.state, game)
    assert revealed.splitlines()[0] == "KL══"
    assert "Yellow key" in revealed
    assert "Locked door" in revealed
    assert "Hidden parking floor" in revealed
    assert "owner=yellow" in revealed

    engine.state.board.set_entity("objects", Pos(0, 0), None)
    collected = text_renderer.render(engine.state, game)
    assert collected.splitlines()[0] == ":L══"
    assert "Yellow key" not in collected
    assert "owner=yellow" not in collected


def run_all() -> bool:
    tests = [
        test_territory_symbol_shown_on_owned_empty_cell_and_hidden_under_actor,
        test_whitespace_symbol_is_rendered_visibly,
        test_entity_state_includes_non_symbol_parameters,
        test_anonymous_entity_state_preserves_dynamics_without_kind_name,
        test_multi_cell_legend_and_overlap_use_public_game_identity,
        test_consumed_target_reports_original_geometry_and_wall_state,
        test_occluding_public_piece_hides_then_reveals_board_contents,
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
