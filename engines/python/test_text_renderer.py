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
from engines.python.anon import build_anon_kind_to_label


def _make_game() -> GameDef:
    data = {
        "id": "com.gridponder.test_text_renderer",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "territory", "occupancy": "zero_or_one"},
            {"id": "actors", "occupancy": "zero_or_one"},
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
    assert "[markers] 1(Target 1) + [multi-cell] ╬(Bellows)" in rendered
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
            "systems": [{"id": "slide", "type": "sliding_blocks"}],
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


def test_declared_layer_order_and_stacks_preserve_circuit_state() -> None:
    game = GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
                {"id": "territory", "occupancy": "zero_or_one"},
                {"id": "markers", "occupancy": "zero_or_one"},
                {"id": "objects", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "floor": {"layer": "ground", "symbol": "."},
                "conduit": {
                    "layer": "territory",
                    "symbol": "c",
                    "uiName": "Powered conduit",
                },
                "contact": {
                    "layer": "markers",
                    "symbol": "A",
                    "uiName": "Closed contact",
                },
                "core": {
                    "layer": "markers",
                    "symbol": "O",
                    "uiName": "Powered core",
                },
                "prism": {
                    "layer": "objects",
                    "symbol": "P",
                    "uiName": "Prism",
                },
            },
        }
    )
    level = {
        "board": {
            "size": [2, 1],
            "layers": {
                "territory": {
                    "format": "sparse",
                    "entries": [
                        {"position": [0, 0], "kind": "conduit"},
                        {"position": [1, 0], "kind": "conduit"},
                    ],
                },
                "markers": {
                    "format": "sparse",
                    "entries": [
                        {"position": [0, 0], "kind": "contact"},
                        {"position": [1, 0], "kind": "core"},
                    ],
                },
                "objects": {
                    "format": "sparse",
                    "entries": [{"position": [0, 0], "kind": "prism"}],
                },
            },
        },
        "state": {"avatar": {"enabled": False}},
        "goals": [],
    }

    rendered = text_renderer.render(TurnEngine(game, level).state, game)
    assert rendered.splitlines()[0] == "PO"
    assert (
        "[objects] P(Prism) + [markers] A(Closed contact) + "
        "[territory] c(Powered conduit)"
    ) in rendered
    assert (
        "[markers] O(Powered core) + [territory] c(Powered conduit)"
    ) in rendered


def test_shared_observation_symbol_hides_internal_phase() -> None:
    game = GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
                {"id": "markers", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "floor": {"layer": "ground", "symbol": "."},
                "yellow_to_green": {
                    "layer": "markers",
                    "symbol": "A",
                    "observationSymbol": "Y",
                    "uiName": "Yellow signal",
                },
                "yellow_to_red": {
                    "layer": "markers",
                    "symbol": "B",
                    "observationSymbol": "Y",
                    "uiName": "Yellow signal",
                },
            },
        }
    )
    level = {
        "board": {
            "size": [2, 1],
            "layers": {
                "markers": {
                    "format": "sparse",
                    "entries": [
                        {"position": [0, 0], "kind": "yellow_to_green"},
                        {"position": [1, 0], "kind": "yellow_to_red"},
                    ],
                }
            },
        },
        "state": {"avatar": {"enabled": False}},
        "goals": [],
    }

    state = TurnEngine(game, level).state
    rendered = text_renderer.render(state, game)
    assert rendered.splitlines()[0] == "YY"
    assert rendered.count("Y=Yellow signal") == 1
    assert "yellow to green" not in rendered.lower()
    assert "yellow to red" not in rendered.lower()

    labels = build_anon_kind_to_label(game)
    assert labels["yellow_to_green"] == labels["yellow_to_red"]
    anonymous = text_renderer.render(state, game, kind_symbol_overrides=labels)
    letter = labels["yellow_to_green"]
    assert anonymous.splitlines()[0] == letter * 2
    assert anonymous.count(f"{letter}=?") == 1


# ── Review fixes: shared observation identity, anon concealment, stacks ─────

def _make_shared_symbol_game() -> GameDef:
    """Two kinds share observationSymbol Q; `ore` is declared first."""
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
                {"id": "markers", "occupancy": "zero_or_one"},
                {"id": "objects", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "floor": {"layer": "ground", "symbol": "."},
                "pad": {"layer": "markers", "symbol": "p", "uiName": "Pad"},
                "ore": {
                    "layer": "objects",
                    "symbol": "r",
                    "observationSymbol": "Q",
                    "uiName": "Lump",
                    "description": "a lump",
                },
                "pickaxe": {
                    "layer": "objects",
                    "symbol": "k",
                    "observationSymbol": "Q",
                    "uiName": "Pickaxe",
                    "description": "breaks rocks",
                },
            },
        }
    )


def _shared_symbol_level(kind: str) -> dict:
    return {
        "board": {
            "size": [2, 1],
            "layers": {
                "markers": {
                    "format": "sparse",
                    "entries": [{"position": [0, 0], "kind": "pad"}],
                },
                "objects": {
                    "format": "sparse",
                    "entries": [
                        {"position": [0, 0], "kind": kind, "charge": 1}
                    ],
                },
            },
        },
        "state": {"avatar": {"enabled": False}},
        "goals": [],
    }


def test_shared_observation_symbol_maps_to_one_anon_label() -> None:
    game = _make_shared_symbol_game()
    labels = build_anon_kind_to_label(game)
    assert labels["ore"] == labels["pickaxe"]
    # Alphabetical assignment over the remaining kinds is unchanged.
    assert labels == {"ore": "A", "pad": "B", "pickaxe": "A"}
    ore = text_renderer.render(
        TurnEngine(game, _shared_symbol_level("ore")).state,
        game,
        kind_symbol_overrides=labels,
    )
    pickaxe = text_renderer.render(
        TurnEngine(game, _shared_symbol_level("pickaxe")).state,
        game,
        kind_symbol_overrides=labels,
    )
    assert ore == pickaxe


def test_shared_observation_symbol_name_is_board_independent() -> None:
    game = _make_shared_symbol_game()
    ore = text_renderer.render(
        TurnEngine(game, _shared_symbol_level("ore")).state, game
    )
    pickaxe = text_renderer.render(
        TurnEngine(game, _shared_symbol_level("pickaxe")).state, game
    )
    assert ore == pickaxe
    assert "Q=Lump (a lump)" in pickaxe
    assert "[objects] Q(Lump) + [markers] p(Pad)" in pickaxe
    assert "(0,0) Lump: charge=1" in pickaxe
    assert "Pickaxe" not in pickaxe and "breaks rocks" not in pickaxe


def test_observation_symbol_validation_rejects_avatar_and_empty() -> None:
    for bad in ("@", ""):
        try:
            GameDef.from_dict(
                {
                    "layers": [],
                    "entityKinds": {
                        "x": {"layer": "objects", "symbol": "x", "observationSymbol": bad}
                    },
                }
            )
        except ValueError:
            continue
        raise AssertionError(f"observationSymbol {bad!r} was accepted")


def test_anonymous_stack_omits_layer_ids() -> None:
    game = _make_shared_symbol_game()
    labels = build_anon_kind_to_label(game)
    rendered = text_renderer.render(
        TurnEngine(game, _shared_symbol_level("pickaxe")).state,
        game,
        kind_symbol_overrides=labels,
    )
    assert "  (0,0): A(?) + B(?)" in rendered
    for vocabulary in ("[objects]", "[markers]", "objects", "markers", "Lump"):
        assert vocabulary not in rendered


def test_anonymous_occluder_and_public_piece_conceal_contents() -> None:
    game = _make_occlusion_game()
    labels = build_anon_kind_to_label(game)
    engine = TurnEngine(game, _make_occlusion_level())
    concealed = text_renderer.render(engine.state, game, kind_symbol_overrides=labels)
    assert concealed.splitlines()[0] == "══.."
    hidden = [labels["key"], labels["door"], labels["parking"]]
    for leaked in (
        *(f"{label}=" for label in hidden),
        *(f"{label}(" for label in hidden),
        *(f" {label}:" for label in hidden),
        "owner=yellow",
        "slab_f_yellow_key",
        "Blue slab",
        "slab",
    ):
        assert leaked not in concealed, leaked
    assert "Piece 1 [?]" in concealed
    assert "axis: horizontal" in concealed
    assert "footprint: (0,0) (1,0)" in concealed
    assert "multi-cell object body" in concealed

    engine.state.board.multi_cell_objects[0].cells = [Pos(2, 0), Pos(3, 0)]
    revealed = text_renderer.render(engine.state, game, kind_symbol_overrides=labels)
    assert revealed.splitlines()[0] == labels["key"] + labels["door"] + "══"
    assert "owner=yellow" in revealed


def test_empty_axis_is_not_printed() -> None:
    game = _make_occlusion_game()
    level = _make_occlusion_level()
    level["board"]["multiCellObjects"][0]["params"] = {"axis": ""}
    rendered = text_renderer.render(TurnEngine(game, level).state, game)
    assert "axis" not in rendered


def test_axis_needs_the_system_that_owns_it() -> None:
    game = _make_occlusion_game()
    game.systems = []
    rendered = text_renderer.render(
        TurnEngine(game, _make_occlusion_level()).state, game
    )
    assert "axis" not in rendered


def _make_pipe_game() -> GameDef:
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
                {"id": "objects", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "empty": {"layer": "ground", "symbol": "."},
                "void": {"layer": "ground", "symbol": "#"},
                "pipe": {"layer": "ground", "symbol": "|"},
                "number": {"layer": "objects", "symbol": "n", "symbolParam": "value"},
            },
        }
    )


def _pipe_level() -> dict:
    return {
        "board": {
            "size": [3, 1],
            "layers": {
                "ground": {
                    "format": "sparse",
                    "entries": [
                        {"position": [0, 0], "kind": "void"},
                        {"position": [1, 0], "kind": "void"},
                    ],
                },
                "objects": {
                    "format": "sparse",
                    "entries": [{"position": [1, 0], "kind": "number", "value": 2}],
                },
            },
            "multiCellObjects": [
                {
                    "id": "p1",
                    "kind": "pipe",
                    "cells": [[0, 0], [1, 0]],
                    "params": {"exitPosition": [0, 0], "exitDirection": "left"},
                }
            ],
        },
        "state": {"avatar": {"enabled": False}},
        "goals": [],
    }


def test_pipe_stack_follows_grid_order_without_background_noise() -> None:
    game = _make_pipe_game()
    rendered = text_renderer.render(TurnEngine(game, _pipe_level()).state, game)
    assert rendered.splitlines()[0] == "◄N."
    assert "║/═/╬=pipe body  ▲/▼/◄/►=pipe exit (arrow = exit direction)" in rendered
    # Ground under the pipe is background: the exit cell gets no stacked line.
    assert "(0,0):" not in rendered
    # An object over the pipe: object, then the pipe, then its ground.
    assert "  (1,0): [objects] N(number) + [multi-cell] ═(pipe) + [ground] #(void)" in rendered
    labels = build_anon_kind_to_label(game)
    anonymous = text_renderer.render(
        TurnEngine(game, _pipe_level()).state,
        game,
        kind_symbol_overrides=labels,
    )
    assert f"  (1,0): N(?) + ═(?) + {labels['void']}(?)" in anonymous
    assert "multi-cell object exit" in anonymous and "pipe" not in anonymous


def _two_bellows_game() -> GameDef:
    data = {
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
            {"id": "markers", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "floor": {"layer": "ground", "symbol": "."},
            "t_a": {"layer": "markers", "symbol": "1", "observationSymbol": "T", "uiName": "Pad"},
            "t_b": {"layer": "markers", "symbol": "2", "observationSymbol": "T", "uiName": "Secret"},
            "blob": {"layer": "structures", "symbol": "B", "uiName": "Blob"},
            "lump": {"layer": "structures", "symbol": "L", "uiName": "Lump"},
        },
        "systems": [
            {
                "id": "second_declared_first",
                "type": "elastic_block",
                "config": {"objectKind": "lump", "targets": [{"id": "b", "markerKind": "t_b"}]},
            },
            {
                "id": "blob_motion",
                "type": "elastic_block",
                "config": {"objectKind": "blob", "targets": [{"id": "a", "markerKind": "t_a"}]},
            },
        ],
    }
    return GameDef.from_dict(data)


def _two_bellows_level() -> dict:
    return {
        "board": {
            "size": [3, 1],
            "layers": {
                "markers": {
                    "format": "sparse",
                    "entries": [
                        {"position": [0, 0], "kind": "t_a"},
                        {"position": [2, 0], "kind": "t_b"},
                    ],
                }
            },
            "multiCellObjects": [
                {"id": "blob", "kind": "blob", "cells": [[0, 0]]},
                {"id": "lump", "kind": "lump", "cells": [[1, 0]]},
            ],
        },
        "state": {"avatar": {"enabled": False}},
        "goals": [],
    }


def test_system_status_blocks_follow_declaration_order() -> None:
    game = _two_bellows_game()
    level = _two_bellows_level()
    rendered = text_renderer.render(TurnEngine(game, level).state, game, level_def=level)
    lump = rendered.index("Target status (exact Lump footprint match required):")
    blob = rendered.index("Target status (exact Blob footprint match required):")
    assert lump < blob
    # Both targets share observationSymbol T: both print the first-declared name.
    assert "  Pad [T]: cells (2,0); unfinished (0/1 cells covered)" in rendered
    assert "  Pad [T]: cells (0,0); unfinished (1/1 cells covered)" in rendered
    assert "Secret" not in rendered
    anonymous = text_renderer.render(
        TurnEngine(game, level).state,
        game,
        level_def=level,
        kind_symbol_overrides=build_anon_kind_to_label(game),
    )
    assert "Target status" not in anonymous


def test_initial_board_is_built_once_per_render() -> None:
    from engines.python import _models

    game = _two_bellows_game()
    level = _two_bellows_level()
    state = TurnEngine(game, level).state
    original = _models.Board.from_json
    calls = []

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    _models.Board.from_json = counting
    try:
        text_renderer.render(state, game, level_def=level)
    finally:
        _models.Board.from_json = original
    assert len(calls) == 1


def run_all() -> bool:
    tests = [
        test_territory_symbol_shown_on_owned_empty_cell_and_hidden_under_actor,
        test_whitespace_symbol_is_rendered_visibly,
        test_entity_state_includes_non_symbol_parameters,
        test_anonymous_entity_state_preserves_dynamics_without_kind_name,
        test_multi_cell_legend_and_overlap_use_public_game_identity,
        test_consumed_target_reports_original_geometry_and_wall_state,
        test_occluding_public_piece_hides_then_reveals_board_contents,
        test_declared_layer_order_and_stacks_preserve_circuit_state,
        test_shared_observation_symbol_hides_internal_phase,
        test_shared_observation_symbol_maps_to_one_anon_label,
        test_shared_observation_symbol_name_is_board_independent,
        test_observation_symbol_validation_rejects_avatar_and_empty,
        test_anonymous_stack_omits_layer_ids,
        test_anonymous_occluder_and_public_piece_conceal_contents,
        test_empty_axis_is_not_printed,
        test_axis_needs_the_system_that_owns_it,
        test_pipe_stack_follows_grid_order_without_background_noise,
        test_system_status_blocks_follow_declaration_order,
        test_initial_board_is_built_once_per_render,
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
