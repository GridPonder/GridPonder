"""push_objects.blockingLayers — layers besides `objects` that stop a push.

Only the objects and ground layers were ever consulted, so a pack that keeps
its NPCs on `actors` had crates pushed straight through them. Pairs with
`blockingTags` the same way `sliding_blocks` and `line_of_sight` do.

Run from the repo root:  python engines/python/test_push_blocking_layers.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._models import Pos
from engines.python._turn_engine import TurnEngine


def _game(config: dict) -> GameDef:
    return GameDef.from_dict(
        {
            "layers": [
                {"id": "ground", "occupancy": "exactly_one", "default": "floor"},
                {"id": "objects", "occupancy": "zero_or_one"},
                {"id": "actors", "occupancy": "zero_or_one"},
            ],
            "entityKinds": {
                "floor": {"layer": "ground", "tags": ["walkable"], "symbol": "."},
                # `solid` too, or navigation walks onto it instead of delegating.
                "crate": {"layer": "objects", "tags": ["pushable", "solid"],
                          "symbol": "c"},
                "guard": {"layer": "actors", "tags": ["npc", "solid"], "symbol": "G"},
                "ghost": {"layer": "actors", "tags": ["npc"], "symbol": "g"},
            },
            "actions": [
                {
                    "id": "move",
                    "params": {
                        "direction": {
                            "type": "direction",
                            "values": ["up", "down", "left", "right"],
                        }
                    },
                }
            ],
            "systems": [
                {"id": "nav", "type": "avatar_navigation",
                 "config": {"solidHandling": "delegate"}},
                {"id": "push", "type": "push_objects", "config": config},
            ],
            "rules": [],
        },
        id="test_push_blocking_layers",
    )


def _level(actor_kind: str | None, actor_x: int = 2) -> dict:
    # A row of five: avatar, crate, then whatever is standing in the way.
    actors = ([{"position": [actor_x, 0], "kind": actor_kind}]
              if actor_kind else [])
    return {
        "id": "test_level",
        "board": {
            "size": [5, 1],
            "layers": {
                "objects": {"format": "sparse",
                            "entries": [{"position": [1, 0], "kind": "crate"}]},
                "actors": {"format": "sparse", "entries": actors},
            },
        },
        "state": {"avatar": {"enabled": True, "position": [0, 0]}},
        "goals": [],
        "loseConditions": [],
    }


def _push_right(game: GameDef, level: dict) -> int | None:
    """X of the crate after one push, or None if it left the board."""
    engine = TurnEngine(game, level)
    engine.execute_turn("move", {"direction": "right"})
    board = engine.state.board
    for x in range(5):
        entity = board.get_entity("objects", Pos(x, 0))
        if entity is not None and entity.kind == "crate":
            return x
    return None


def test_without_the_field_a_crate_goes_through_an_actor() -> None:
    """The behaviour before the field existed, kept as the baseline."""
    assert _push_right(_game({}), _level("guard")) == 2
    print("  OK  without_the_field_a_crate_goes_through_an_actor")


def test_a_solid_actor_blocks_the_push() -> None:
    game = _game({"blockingLayers": ["actors"]})
    assert _push_right(game, _level("guard")) == 1
    print("  OK  a_solid_actor_blocks_the_push")


def test_an_untagged_actor_does_not_block() -> None:
    """`blockingTags` defaults to ["solid"], as in the sibling systems."""
    game = _game({"blockingLayers": ["actors"]})
    assert _push_right(game, _level("ghost")) == 2
    print("  OK  an_untagged_actor_does_not_block")


def test_empty_blocking_tags_means_any_entity_blocks() -> None:
    game = _game({"blockingLayers": ["actors"], "blockingTags": []})
    assert _push_right(game, _level("ghost")) == 1
    print("  OK  empty_blocking_tags_means_any_entity_blocks")


def test_an_empty_cell_on_a_blocking_layer_is_no_obstacle() -> None:
    game = _game({"blockingLayers": ["actors"]})
    assert _push_right(game, _level(None)) == 2
    print("  OK  an_empty_cell_on_a_blocking_layer_is_no_obstacle")


def test_listing_objects_is_a_no_op() -> None:
    """The push logic owns that layer; a generic check would break chainPush."""
    game = _game({"blockingLayers": ["objects", "actors"], "chainPush": True})
    level = _level(None)
    level["board"]["layers"]["objects"]["entries"].append(
        {"position": [2, 0], "kind": "crate"})
    # Two crates in a row: the chain push still works rather than being refused.
    assert _push_right(game, level) == 2
    print("  OK  listing_objects_is_a_no_op")


def test_the_chain_destination_is_checked_too() -> None:
    game = _game({"blockingLayers": ["actors"], "chainPush": True})
    level = _level("guard", actor_x=3)
    level["board"]["layers"]["objects"]["entries"].append(
        {"position": [2, 0], "kind": "crate"})
    # The lead crate would land on the guard, so nothing moves.
    assert _push_right(game, level) == 1
    print("  OK  the_chain_destination_is_checked_too")


TESTS = [
    test_without_the_field_a_crate_goes_through_an_actor,
    test_a_solid_actor_blocks_the_push,
    test_an_untagged_actor_does_not_block,
    test_empty_blocking_tags_means_any_entity_blocks,
    test_an_empty_cell_on_a_blocking_layer_is_no_obstacle,
    test_listing_objects_is_a_no_op,
    test_the_chain_destination_is_checked_too,
]


def run_all() -> bool:
    print("push_objects.blockingLayers tests")
    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}")
            failed += 1
    print(f"\nResults: {len(TESTS) - failed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
