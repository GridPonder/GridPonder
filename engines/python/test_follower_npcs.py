"""
Tests for the `follower_npcs` system that a gold path cannot express.

The escape and sight-gate cases live in the follower_npcs_smoke fixture and are
covered by test_gold_paths.py. The cases here end in a loss or assert on
internal state, so they need to drive TurnEngine directly.

Run from the repo root:  python3 engines/python/test_follower_npcs.py
"""
from __future__ import annotations
import sys
from pathlib import Path

# Make engines/ importable
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engines.python._game_def import GameDef
from engines.python._turn_engine import TurnEngine


def _make_game(behavior: dict, extra_nav_config: dict | None = None) -> GameDef:
    data = {
        "id": "com.gridponder.test_follower_npcs",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "objects", "occupancy": "zero_or_one"},
            {"id": "actors", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"]},
            "flag": {"layer": "objects", "tags": ["goal"]},
            "watcher": {"layer": "actors", "tags": ["npc", "solid"]},
        },
        "actions": [
            {"id": "move", "params": {"direction": {"type": "direction", "values": ["up", "down", "left", "right"]}}},
        ],
        "systems": [
            {"id": "navigation", "type": "avatar_navigation", "config": extra_nav_config or {}},
            {"id": "npcs", "type": "follower_npcs", "config": {"behaviors": {"hunt": behavior}}},
        ],
    }
    return GameDef.from_dict(data, id="test_follower_npcs")


def _make_level(avatar: tuple[int, int], watcher: tuple[int, int], width: int = 5) -> dict:
    return {
        "id": "test_level",
        "board": {
            "size": [width, 3],
            "layers": {
                "actors": {
                    "format": "sparse",
                    "entries": [
                        {"position": list(watcher), "kind": "watcher", "behavior": "hunt"},
                    ],
                },
            },
        },
        "state": {"avatar": {"enabled": True, "position": list(avatar)}},
        "goals": [],
        "loseConditions": [
            {"type": "variable_threshold",
             "config": {"variable": "caught", "target": 1, "comparison": "gte"}},
        ],
    }


def test_lethal_contact_loses_the_level():
    game = _make_game({"type": "toward_avatar", "requiresLineOfSight": True, "lethalContact": True})
    engine = TurnEngine(game, _make_level(avatar=(1, 1), watcher=(3, 1)))

    # Avatar steps to (2,1), adjacent to the watcher on a clear row. The watcher
    # then steps onto the avatar's cell instead of refusing the move.
    result = engine.execute_turn("move", {"direction": "right"})

    caught_events = [e for e in result.events if e["type"] == "avatar_caught"]
    assert len(caught_events) == 1, f"expected one avatar_caught event, got {result.events}"
    assert caught_events[0]["npcKind"] == "watcher"
    assert engine.state.variables["caught"] == 1, engine.state.variables
    assert result.is_lost, "level should be lost once the contact counter trips"
    assert result.lose_reason == "variable_threshold:caught", result.lose_reason


def test_contact_is_refused_without_lethal_contact():
    game = _make_game({"type": "toward_avatar", "requiresLineOfSight": True})
    engine = TurnEngine(game, _make_level(avatar=(1, 1), watcher=(3, 1)))

    result = engine.execute_turn("move", {"direction": "right"})

    assert not any(e["type"] == "avatar_caught" for e in result.events)
    assert not any(e["type"] == "npc_moved" for e in result.events), (
        "the watcher's only distance-reducing step is the avatar's cell, so it "
        f"should not move at all: {result.events}"
    )
    assert "caught" not in engine.state.variables
    assert not result.is_lost


def test_contact_variable_name_is_configurable():
    game = _make_game({"type": "toward_avatar", "lethalContact": True})
    game.systems[1]["config"]["contactVariable"] = "doom"
    level = _make_level(avatar=(1, 1), watcher=(3, 1))
    level["loseConditions"] = [
        {"type": "variable_threshold",
         "config": {"variable": "doom", "target": 1, "comparison": "gte"}},
    ]
    engine = TurnEngine(game, level)

    result = engine.execute_turn("move", {"direction": "right"})

    assert engine.state.variables["doom"] == 1, engine.state.variables
    assert result.lose_reason == "variable_threshold:doom", result.lose_reason


def test_npc_blocks_the_avatar_when_actors_layer_is_solid():
    game = _make_game(
        {"type": "toward_avatar", "requiresLineOfSight": True},
        extra_nav_config={"solidLayers": ["objects", "actors"]},
    )
    engine = TurnEngine(game, _make_level(avatar=(1, 1), watcher=(2, 1)))

    # The watcher sits directly to the right; walking into it must not move the
    # avatar. Note the turn is still spent — `accepted` only goes False for an
    # unknown action or an explicit veto, not for a blocked move.
    result = engine.execute_turn("move", {"direction": "right"})

    assert engine.state.avatar.position.x == 1, engine.state.avatar.position
    assert not any(e["type"] == "avatar_entered" for e in result.events), result.events
    # Facing still turns, so the player can see the blocked move registered.
    assert engine.state.avatar.facing == "right", engine.state.avatar.facing


def test_npc_does_not_block_the_avatar_by_default():
    game = _make_game({"type": "toward_avatar", "requiresLineOfSight": True})
    engine = TurnEngine(game, _make_level(avatar=(1, 1), watcher=(2, 1)))

    result = engine.execute_turn("move", {"direction": "right"})

    assert result.accepted, "default solidLayers only covers objects"
    assert engine.state.avatar.position.x == 2, engine.state.avatar.position


def test_a_blocked_move_still_advances_the_turn():
    """A move into a wall is not free: NPCs still act.

    This is load-bearing for level design — it means walking into an obstacle is
    a usable wait action, so a level cannot force the player to stall by moving.
    """
    game = _make_game({"type": "toward_avatar", "requiresLineOfSight": True})
    # Avatar at the left edge, watcher three cells away on the same clear row.
    engine = TurnEngine(game, _make_level(avatar=(0, 1), watcher=(3, 1)))

    result = engine.execute_turn("move", {"direction": "left"})  # into the edge

    assert engine.state.avatar.position.x == 0, "the avatar should not have moved"
    moves = [e for e in result.events if e["type"] == "npc_moved"]
    assert len(moves) == 1, f"the watcher should still have acted: {result.events}"
    assert engine.state.turn_count == 1, engine.state.turn_count


def test_gaze_param_tracks_sight():
    """The gaze param is a render hint, but it must be exact.

    It names the direction of the avatar while the NPC can see it, and `rest`
    the moment sight is lost — that is what drives the eye sprite.
    """
    game = _make_game({
        "type": "toward_avatar",
        "requiresLineOfSight": True,
        "gazeParam": "gaze",
    })
    # Avatar left of the watcher on a clear row, three cells apart.
    engine = TurnEngine(game, _make_level(avatar=(0, 1), watcher=(3, 1)))

    def watcher_gaze():
        for _, entity in engine.state.board.layers["actors"].entries():
            if entity.kind == "watcher":
                return entity.param("gaze")
        return None

    engine.execute_turn("move", {"direction": "right"})  # avatar to (1,1)
    assert watcher_gaze() == "left", watcher_gaze()

    engine.execute_turn("move", {"direction": "up"})  # leaves row 1
    assert watcher_gaze() == "rest", watcher_gaze()

    engine.execute_turn("move", {"direction": "down"})  # back onto row 1
    assert watcher_gaze() == "left", watcher_gaze()


def test_sight_is_published_as_an_event():
    """Seeing the avatar must reach rules, not stay inside the system.

    The other packs react to being seen through the standalone `line_of_sight`
    system. A game whose watcher is a `follower_npcs` NPC could not, because the
    same geometric test was computed here and thrown away.
    """
    game = _make_game({
        "type": "toward_avatar",
        "requiresLineOfSight": True,
    })
    engine = TurnEngine(game, _make_level(avatar=(0, 1), watcher=(3, 1)))

    def sightings(result):
        return [e for e in result.events if e["type"] == "line_of_sight_detected"]

    seen = sightings(engine.execute_turn("move", {"direction": "right"}))
    assert len(seen) == 1, seen
    assert seen[0]["kind"] == "avatar"
    assert seen[0]["sourceKind"] == "watcher"
    assert seen[0]["position"] == engine.state.avatar.position
    # The source is where the watcher stood when it looked, not where it landed.
    assert seen[0]["sourcePosition"] != seen[0]["position"]

    # Out of the line, nothing is reported.
    assert sightings(engine.execute_turn("move", {"direction": "up"})) == []


def test_a_patrol_never_reports_a_sightline():
    """A behavior that never tests a line must not claim to have seen one."""
    game = _make_game({"type": "patrol"})
    engine = TurnEngine(game, _make_level(avatar=(0, 1), watcher=(3, 1)))
    result = engine.execute_turn("move", {"direction": "right"})
    assert [e for e in result.events if e["type"] == "line_of_sight_detected"] == []


def test_rules_receive_npc_events():
    """`npc_moved` is documented as rule-triggerable, so a rule must see it."""
    game = _make_game({"type": "toward_avatar", "requiresLineOfSight": True})
    level = _make_level(avatar=(0, 1), watcher=(3, 1))
    level["board"]["layers"]["objects"] = {
        "format": "sparse",
        "entries": [{"position": [4, 2], "kind": "flag"}],
    }
    level["rules"] = [
        {
            "id": "clear_flag_when_watcher_walks",
            "on": "npc_moved",
            "then": [{"destroy": {"position": [4, 2], "layer": "objects"}}],
        },
    ]
    engine = TurnEngine(game, level)

    from engines.python._models import Pos
    assert engine.state.board.get_entity("objects", Pos(4, 2)) is not None

    result = engine.execute_turn("move", {"direction": "right"})

    assert any(e["type"] == "npc_moved" for e in result.events), result.events
    assert engine.state.board.get_entity("objects", Pos(4, 2)) is None, (
        "the rule never fired, so NPC events are still invisible to rules"
    )


def _patrol_game(lethal: bool) -> GameDef:
    data = {
        "id": "com.gridponder.test_follower_npcs_patrol",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "actors", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"]},
            "sentry": {"layer": "actors", "tags": ["npc"]},
        },
        "actions": [
            {"id": "move", "params": {"direction": {"type": "direction", "values": ["up", "down", "left", "right"]}}},
        ],
        "systems": [
            {"id": "navigation", "type": "avatar_navigation", "config": {}},
            {"id": "npcs", "type": "follower_npcs", "config": {"behaviors": {
                "march": {"type": "patrol", "lethalContact": lethal},
            }}},
        ],
    }
    return GameDef.from_dict(data, id="test_follower_npcs_patrol")


def _patrol_level() -> dict:
    """Sentry two cells right of the avatar on a 1-row board, marching left."""
    return {
        "id": "test_level",
        "board": {
            "size": [5, 1],
            "layers": {
                "actors": {
                    "format": "sparse",
                    "entries": [
                        {"position": [2, 0], "kind": "sentry", "behavior": "march", "facing": "left"},
                    ],
                },
            },
        },
        "state": {"avatar": {"enabled": True, "position": [0, 0]}},
        "goals": [],
        "loseConditions": [
            {"type": "variable_threshold",
             "config": {"variable": "caught", "target": 1, "comparison": "gte"}},
        ],
    }


def _sentry_pos(engine: TurnEngine):
    for pos, entity in engine.state.board.layers["actors"].entries():
        if entity.kind == "sentry":
            return pos
    return None


def test_lethal_contact_governs_patrol_too():
    """A patrolling sentry kills on contact only when it opts in.

    The flag used to be read on the avatar-seeking path only, which left every
    other behavior lethal with no way to say so or to turn it off.
    """
    engine = TurnEngine(_patrol_game(lethal=True), _patrol_level())

    engine.execute_turn("move", {"direction": "up"})  # blocked; avatar holds (0,0)
    assert _sentry_pos(engine).x == 1, _sentry_pos(engine)

    result = engine.execute_turn("move", {"direction": "up"})

    assert any(e["type"] == "avatar_caught" for e in result.events), result.events
    assert result.is_lost
    assert result.lose_reason == "variable_threshold:caught", result.lose_reason


def test_a_harmless_patrol_bounces_off_the_avatar():
    engine = TurnEngine(_patrol_game(lethal=False), _patrol_level())

    engine.execute_turn("move", {"direction": "up"})  # sentry marches to (1,0)
    assert _sentry_pos(engine).x == 1

    result = engine.execute_turn("move", {"direction": "up"})

    assert not result.is_lost, "a non-lethal sentry must not end the level"
    assert not any(e["type"] == "avatar_caught" for e in result.events)
    # The avatar blocks it, so patrol reverses instead of walking through.
    assert _sentry_pos(engine).x == 2, _sentry_pos(engine)


TESTS = [
    test_lethal_contact_loses_the_level,
    test_contact_is_refused_without_lethal_contact,
    test_contact_variable_name_is_configurable,
    test_npc_blocks_the_avatar_when_actors_layer_is_solid,
    test_npc_does_not_block_the_avatar_by_default,
    test_a_blocked_move_still_advances_the_turn,
    test_gaze_param_tracks_sight,
    test_sight_is_published_as_an_event,
    test_a_patrol_never_reports_a_sightline,
    test_rules_receive_npc_events,
    test_lethal_contact_governs_patrol_too,
    test_a_harmless_patrol_bounces_off_the_avatar,
]


def run_all() -> bool:
    print("follower_npcs tests")
    passed = failed = 0
    for t in TESTS:
        try:
            t()
            passed += 1
            print(f"  ✓ {t.__name__}")
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
    sys.exit(0 if run_all() else 1)
