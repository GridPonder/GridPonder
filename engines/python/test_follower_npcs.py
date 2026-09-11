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
from engines.python._models import Pos
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
        extra_nav_config={
            "solidLayers": ["objects", "actors"],
            "faceOnBlockedMove": True,
        },
    )
    engine = TurnEngine(game, _make_level(avatar=(1, 1), watcher=(2, 1)))

    # The watcher sits directly to the right; walking into it must not move the
    # avatar. Note the turn is still spent — `accepted` only goes False for an
    # unknown action or an explicit veto, not for a blocked move.
    result = engine.execute_turn("move", {"direction": "right"})

    assert engine.state.avatar.position.x == 1, engine.state.avatar.position
    assert not any(e["type"] == "avatar_entered" for e in result.events), result.events
    # Opted in, so facing turns and the player can see the blocked move register.
    assert engine.state.avatar.facing == "right", engine.state.avatar.facing


def test_a_blocked_move_leaves_facing_alone_by_default():
    """`facing` is part of state identity, so turning on a refused move makes it
    a fresh search node instead of a no-op. Packs pay that only on request."""
    game = _make_game(
        {"type": "toward_avatar", "requiresLineOfSight": True},
        extra_nav_config={"solidLayers": ["objects", "actors"]},
    )
    engine = TurnEngine(game, _make_level(avatar=(1, 1), watcher=(2, 1)))
    engine.execute_turn("move", {"direction": "down"})   # settle facing away
    facing_before = engine.state.avatar.facing
    engine.execute_turn("move", {"direction": "up"})     # back to the start cell
    before = engine.state_key()

    engine.execute_turn("move", {"direction": "right"})  # into the watcher

    assert engine.state.avatar.facing == "up", engine.state.avatar.facing
    assert facing_before == "down", facing_before
    # The watcher cannot close (its only step is the avatar's cell), so the
    # whole turn has to collapse back onto the state it started from.
    assert engine.state_key() == before


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
    assert seen[0]["sourcePosition"] != seen[0]["position"]

    # Out of the line, nothing is reported.
    assert sightings(engine.execute_turn("move", {"direction": "up"})) == []


def test_the_sightline_is_reported_from_where_the_npc_lands():
    """The beam is drawn on the board the turn ends with.

    A chaser steps along the very line it just traced, so reporting the cell it
    looked from leaves the drawn beam trailing one segment behind the monster.
    The shortened line is a sub-segment of the same unobstructed sightline, so
    it is no less true.
    """
    game = _make_game({
        "type": "toward_avatar",
        "requiresLineOfSight": True,
    })
    engine = TurnEngine(game, _make_level(avatar=(0, 1), watcher=(3, 1)))
    result = engine.execute_turn("move", {"direction": "right"})

    seen = [e for e in result.events if e["type"] == "line_of_sight_detected"]
    moved = [e for e in result.events if e["type"] == "npc_moved"]
    assert len(seen) == 1 and len(moved) == 1, (seen, moved)
    assert seen[0]["sourcePosition"] == moved[0]["toPosition"], seen[0]
    assert seen[0]["sourcePosition"] != moved[0]["fromPosition"]
    # The id still names the cell it started from, so the two events correlate.
    assert seen[0]["sourceId"] == moved[0]["npcId"]


def test_a_still_npc_reports_from_where_it_stands():
    """Nothing moved, so there is no old position to confuse it with."""
    game = _make_game({
        "type": "toward_avatar",
        "requiresLineOfSight": True,
        "frequency": 2,
    })
    engine = TurnEngine(game, _make_level(avatar=(0, 1), watcher=(3, 1)))
    # Turn one is the acting turn (the counter starts at zero); turn two is the
    # one the gate skips. Bump the edge so the avatar holds still for both.
    engine.execute_turn("move", {"direction": "left"})
    resting = _watcher_position(engine)
    result = engine.execute_turn("move", {"direction": "left"})

    seen = [e for e in result.events if e["type"] == "line_of_sight_detected"]
    assert [e for e in result.events if e["type"] == "npc_moved"] == [], result.events
    # Sight is still reported on a skipped turn: it saw, it just did not act.
    assert len(seen) == 1, seen
    assert seen[0]["sourcePosition"] == resting, (seen[0], resting)


def _watcher_position(engine):
    for pos, entity in engine.state.board.layers["actors"].entries():
        if entity.kind == "watcher":
            return pos
    return None


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


# -- shafts (linked machines) ------------------------------------------------
#
# The fixtures above take a single behavior and a 5x3 board; trains need two
# behaviors, a system-level config key and room for two separate tracks, so
# these are a second pair rather than a rewrite of the first.


def _shaft_game(behaviors: dict | None = None, config_extra: dict | None = None) -> GameDef:
    npc_config = {
        "npcTags": ["npc"],
        "contactVariable": "crushed",
        "behaviors": behaviors or {
            "walker": {"type": "patrol", "lethalContact": False, "solidBlocking": True},
        },
    }
    npc_config.update(config_extra or {})
    data = {
        "id": "com.gridponder.test_follower_shaft",
        "layers": [
            {"id": "ground", "occupancy": "exactly_one", "default": "empty"},
            {"id": "actors", "occupancy": "zero_or_one"},
        ],
        "entityKinds": {
            "empty": {"layer": "ground", "tags": ["walkable"]},
            "void": {"layer": "ground", "tags": []},
            "machine": {"layer": "actors", "tags": ["npc", "solid"]},
        },
        "actions": [
            {"id": "move", "params": {"direction": {"type": "direction", "values": ["up", "down", "left", "right"]}}},
        ],
        "systems": [
            {"id": "navigation", "type": "avatar_navigation", "config": {}},
            {"id": "machines", "type": "follower_npcs", "config": npc_config},
        ],
    }
    return GameDef.from_dict(data, id="test_follower_shaft")


def _shaft_level(machines: list, walls: tuple = ()) -> dict:
    """8x5 board. Machines are (x, y, behavior, facing[, shaft]) tuples.

    The avatar parks at (0, 4) and spends beats by walking into the bottom edge:
    a blocked move is still a beat, which is how the other patrol tests here
    advance the world too.
    """
    entries = []
    for m in machines:
        entry = {"position": [m[0], m[1]], "kind": "machine", "behavior": m[2], "facing": m[3]}
        if len(m) > 4 and m[4] is not None:
            entry["shaft"] = m[4]
        entries.append(entry)
    return {
        "id": "test_level",
        "board": {
            "size": [8, 5],
            "layers": {
                "ground": {"format": "sparse",
                           "entries": [{"position": [x, y], "kind": "void"} for x, y in walls]},
                "actors": {"format": "sparse", "entries": entries},
            },
        },
        "state": {"avatar": {"enabled": True, "position": [0, 4]}},
        "goals": [],
        "loseConditions": [
            {"type": "variable_threshold",
             "config": {"variable": "crushed", "target": 1, "comparison": "gte"}},
        ],
    }


def _beat(engine: TurnEngine):
    """Spend one beat without moving: the bottom edge blocks the avatar."""
    return engine.execute_turn("move", {"direction": "down"})


def _machines(engine: TurnEngine) -> list:
    return sorted((pos.x, pos.y) for pos, _ in engine.state.board.layers["actors"].entries())


def _facing_at(engine: TurnEngine, x: int, y: int) -> str:
    return str(engine.state.board.get_entity("actors", Pos(x, y)).param("facing"))


def test_unshafted_board_is_unchanged_by_the_shaft_feature():
    """Guard for Firebreak and Blind Spot: no shaft params -> today's path.

    Two independent patrols on separate rows. One is walled in front and
    reverses; the other's path is clear and it simply walks on. This is today's
    behaviour, recorded literally so the train pass cannot drift it.
    """
    engine = TurnEngine(_shaft_game(), _shaft_level(
        [(4, 0, "walker", "right"), (1, 2, "walker", "right")], walls=((5, 0),),
    ))

    _beat(engine)

    # (4,0) faces a wall at (5,0): it reverses to (3,0). (1,2) is clear: it
    # walks on to (2,2), entirely unaffected by the other machine's wall.
    assert _machines(engine) == [(2, 2), (3, 0)], _machines(engine)
    assert _facing_at(engine, 3, 0) == "left"
    assert _facing_at(engine, 2, 2) == "right"


def test_shafted_pair_steps_in_lockstep():
    engine = TurnEngine(_shaft_game(), _shaft_level(
        [(1, 0, "walker", "right", "a"), (1, 2, "walker", "right", "a")],
    ))

    _beat(engine)

    assert _machines(engine) == [(2, 0), (2, 2)], _machines(engine)


def test_blocking_one_member_reverses_the_whole_train():
    """The remote turn: a wall in front of one member turns the other one.

    (1,2)'s own path is clear all the way to the east edge. It reverses anyway,
    because the shaft carries (4,0)'s wall to it.
    """
    engine = TurnEngine(_shaft_game(), _shaft_level(
        [(4, 0, "walker", "right", "a"), (1, 2, "walker", "right", "a")],
        walls=((5, 0),),
    ))

    _beat(engine)

    assert _machines(engine) == [(0, 2), (3, 0)], _machines(engine)
    assert _facing_at(engine, 3, 0) == "left"
    assert _facing_at(engine, 0, 2) == "left"


def test_train_blocked_both_ways_freezes_and_keeps_facings():
    """Engine fact #5, applied to the train: freeze, keep facing, resume later."""
    engine = TurnEngine(_shaft_game(), _shaft_level(
        [(4, 0, "walker", "right", "a"), (1, 2, "walker", "right", "a")],
        walls=((5, 0), (3, 0)),
    ))

    _beat(engine)

    assert _machines(engine) == [(1, 2), (4, 0)], _machines(engine)
    assert _facing_at(engine, 4, 0) == "right"
    assert _facing_at(engine, 1, 2) == "right"


def _seize_game(**config_extra) -> GameDef:
    return _shaft_game(config_extra=config_extra)


def test_load_settle_records_each_trains_size():
    engine = TurnEngine(_seize_game(shaftSeizeOnLoss=True), _shaft_level([
        (1, 0, "walker", "right", "a"),
        (1, 2, "walker", "right", "a"),
        (6, 3, "walker", "up", "b"),
    ]))

    assert engine.state.variables["shaft_a_size"] == 2
    assert engine.state.variables["shaft_b_size"] == 1


def test_train_seizes_permanently_when_a_member_is_destroyed():
    """The capstone verb: subtraction becomes a permanent remote freeze."""
    engine = TurnEngine(_seize_game(shaftSeizeOnLoss=True), _shaft_level([
        (1, 0, "walker", "right", "a"),
        (1, 2, "walker", "right", "a"),
    ]))

    _beat(engine)
    assert _machines(engine) == [(2, 0), (2, 2)], _machines(engine)

    # Something else removes one member — a leaf opening under it, in the pack.
    engine.state.board.set_entity("actors", Pos(2, 0), None)

    for _ in range(4):
        _beat(engine)
    assert _machines(engine) == [(2, 2)], "survivor must be frozen forever"


def test_seizure_is_off_by_default():
    engine = TurnEngine(_shaft_game(), _shaft_level([
        (1, 0, "walker", "right", "a"),
        (1, 2, "walker", "right", "a"),
    ]))

    engine.state.board.set_entity("actors", Pos(1, 0), None)
    _beat(engine)

    assert _machines(engine) == [(2, 2)], "survivor keeps running"


def test_seizure_flag_is_read_strictly():
    """Matches the `cycle` precedent in coupled_actors: only True enables it."""
    engine = TurnEngine(_seize_game(shaftSeizeOnLoss=1), _shaft_level([
        (1, 0, "walker", "right", "a"),
        (1, 2, "walker", "right", "a"),
    ]))

    engine.state.board.set_entity("actors", Pos(1, 0), None)
    _beat(engine)

    assert _machines(engine) == [(2, 2)], _machines(engine)


def _rejects(game, level, word: str) -> None:
    try:
        TurnEngine(game, level)
    except ValueError as exc:
        assert word in str(exc), f"expected {word!r} in {exc!r}"
    else:
        raise AssertionError(f"expected a ValueError mentioning {word!r}")


def test_non_patrol_member_is_rejected_at_load():
    game = _shaft_game(behaviors={
        "walker": {"type": "patrol", "lethalContact": False},
        "ringer": {"type": "clockwise", "lethalContact": False},
    })
    _rejects(game, _shaft_level([
        (1, 0, "walker", "right", "a"),
        (1, 2, "ringer", "right", "a"),
    ]), "patrol")


def test_members_sharing_a_traversal_line_are_rejected_at_load():
    """Self-blocking would make lockstep meaningless: the train jams at t=0."""
    _rejects(_shaft_game(), _shaft_level([
        (1, 0, "walker", "right", "a"),
        (4, 0, "walker", "right", "a"),
    ]), "traversal")


# -- ratio shafts (geared trains) ---------------------------------------------
#
# A train may mix frequencies. Each member runs on its own beat; only the
# members whose gate opens are probed and step, but a reversal turns the WHOLE
# train, because facing is train-level state.
#
# turn_count starts at 0 and is read BEFORE it increments, so a frequency-2
# member is active on the 1st, 3rd, 5th beat and idle on the 2nd and 4th.

_GEARED = {
    "walker": {"type": "patrol", "lethalContact": False, "solidBlocking": True},
    "slow": {"type": "patrol", "lethalContact": False, "solidBlocking": True,
             "frequency": 2},
}


def test_mixed_frequency_train_loads():
    """The whole point of the arc: a geared train is no longer rejected."""
    TurnEngine(_shaft_game(_GEARED), _shaft_level(
        [(1, 0, "walker", "right", "a"), (1, 2, "slow", "right", "a")],
    ))


def test_geared_members_step_at_their_own_rates():
    """turn_count 0: both step. turn_count 1: only the fast one."""
    engine = TurnEngine(_shaft_game(_GEARED), _shaft_level(
        [(1, 0, "walker", "right", "a"), (1, 2, "slow", "right", "a")],
    ))

    _beat(engine)
    assert _machines(engine) == [(2, 0), (2, 2)], _machines(engine)

    _beat(engine)
    # The slow member is off-beat and stays put; the fast one walks on alone.
    assert _machines(engine) == [(2, 2), (3, 0)], _machines(engine)

    _beat(engine)
    assert _machines(engine) == [(3, 2), (4, 0)], _machines(engine)


def test_reversal_turns_the_member_that_did_not_step():
    """The arc's core fact: an off-beat member turns without moving.

    Beat 1 (turn_count 0): both active, both walk east.
    Beat 2 (turn_count 1): only the fast member is active. It faces the wall at
    (5,0), so the train reverses — and the slow member at (2,2), which took no
    step at all this beat, is now facing left.
    """
    engine = TurnEngine(_shaft_game(_GEARED), _shaft_level(
        [(3, 0, "walker", "right", "a"), (1, 2, "slow", "right", "a")],
        walls=((5, 0),),
    ))

    _beat(engine)
    assert _machines(engine) == [(2, 2), (4, 0)], _machines(engine)

    _beat(engine)
    assert _machines(engine) == [(2, 2), (3, 0)], _machines(engine)
    assert _facing_at(engine, 3, 0) == "left"
    assert _facing_at(engine, 2, 2) == "left"


def test_the_slow_wheel_steers_the_fast_one():
    """A geared train: the member you cannot reach turns
    the member you can, on a beat the fast one had every reason to walk on."""
    engine = TurnEngine(_shaft_game(_GEARED), _shaft_level(
        [(1, 0, "walker", "right", "a"), (3, 2, "slow", "right", "a")],
        walls=((5, 2),),
    ))

    _beat(engine)   # turn_count 0: both step east
    assert _machines(engine) == [(2, 0), (4, 2)], _machines(engine)

    _beat(engine)   # turn_count 1: fast alone, clear road
    assert _machines(engine) == [(3, 0), (4, 2)], _machines(engine)

    _beat(engine)   # turn_count 2: slow hits (5,2) and drags the fast one back
    assert _machines(engine) == [(2, 0), (3, 2)], _machines(engine)
    assert _facing_at(engine, 2, 0) == "left"
    assert _facing_at(engine, 3, 2) == "left"


def test_all_members_off_beat_is_a_noop_not_a_freeze():
    """An empty active set must emit nothing and turn nothing.

    Both members are frequency 2, so turn_count 1 has no active member at all.
    Facings must survive untouched: a no-op is not a blocked train.
    """
    engine = TurnEngine(_shaft_game(_GEARED), _shaft_level(
        [(1, 0, "slow", "right", "a"), (1, 2, "slow", "right", "a")],
    ))

    _beat(engine)
    assert _machines(engine) == [(2, 0), (2, 2)], _machines(engine)

    result = _beat(engine)
    assert _machines(engine) == [(2, 0), (2, 2)], _machines(engine)
    assert _facing_at(engine, 2, 0) == "right"
    assert _facing_at(engine, 2, 2) == "right"
    moved = [e for e in result.events if e["type"] == "entity_moved"]
    assert moved == [], moved


def test_same_frequency_train_is_unchanged():
    """Regression guard: an ungeared train still moves in lockstep at its own
    rate, on exactly the beats it did before the ratio change."""
    engine = TurnEngine(_shaft_game(_GEARED), _shaft_level(
        [(1, 0, "slow", "right", "a"), (1, 2, "slow", "right", "a")],
    ))

    _beat(engine)
    assert _machines(engine) == [(2, 0), (2, 2)], _machines(engine)
    _beat(engine)
    assert _machines(engine) == [(2, 0), (2, 2)], _machines(engine)
    _beat(engine)
    assert _machines(engine) == [(3, 0), (3, 2)], _machines(engine)


def test_zero_frequency_member_is_rejected():
    game = _shaft_game(behaviors={
        "walker": {"type": "patrol", "lethalContact": False, "solidBlocking": True},
        "stuck": {"type": "patrol", "lethalContact": False, "solidBlocking": True,
                  "frequency": 0},
    })
    _rejects(game, _shaft_level([
        (1, 0, "walker", "right", "a"),
        (1, 2, "stuck", "right", "a"),
    ]), "positive integer")


def test_members_crossing_tracks_never_share_a_cell():
    """Two members whose tracks cross must not both be given the crossing.

    (2,0) walks east along row 0; (4,2) walks north up column 4. On the second
    beat both want (4,0). Before this was fixed they both got it, the second
    write erased the first, and the train silently lost a member — which then
    read as a seizure, because the size recorded at load no longer matched.
    Both machines must still be on the board.
    """
    behaviors = {
        "walker": {"type": "patrol", "lethalContact": False, "solidBlocking": True},
    }
    engine = TurnEngine(_shaft_game(behaviors), _shaft_level([
        (2, 0, "walker", "right", "a"),
        (4, 2, "walker", "up", "a"),
    ]))

    for _ in range(3):
        _beat(engine)
        live = _machines(engine)
        assert len(live) == 2, f"a member vanished: {live}"


TESTS_SHAFT = [
    test_unshafted_board_is_unchanged_by_the_shaft_feature,
    test_shafted_pair_steps_in_lockstep,
    test_blocking_one_member_reverses_the_whole_train,
    test_train_blocked_both_ways_freezes_and_keeps_facings,
    test_load_settle_records_each_trains_size,
    test_train_seizes_permanently_when_a_member_is_destroyed,
    test_seizure_is_off_by_default,
    test_seizure_flag_is_read_strictly,
    test_mixed_frequency_train_loads,
    test_geared_members_step_at_their_own_rates,
    test_reversal_turns_the_member_that_did_not_step,
    test_the_slow_wheel_steers_the_fast_one,
    test_all_members_off_beat_is_a_noop_not_a_freeze,
    test_same_frequency_train_is_unchanged,
    test_zero_frequency_member_is_rejected,
    test_members_crossing_tracks_never_share_a_cell,
    test_non_patrol_member_is_rejected_at_load,
    test_members_sharing_a_traversal_line_are_rejected_at_load,
]


TESTS = [
    test_lethal_contact_loses_the_level,
    test_contact_is_refused_without_lethal_contact,
    test_contact_variable_name_is_configurable,
    test_npc_blocks_the_avatar_when_actors_layer_is_solid,
    test_a_blocked_move_leaves_facing_alone_by_default,
    test_npc_does_not_block_the_avatar_by_default,
    test_a_blocked_move_still_advances_the_turn,
    test_gaze_param_tracks_sight,
    test_sight_is_published_as_an_event,
    test_the_sightline_is_reported_from_where_the_npc_lands,
    test_a_still_npc_reports_from_where_it_stands,
    test_a_patrol_never_reports_a_sightline,
    test_rules_receive_npc_events,
    test_lethal_contact_governs_patrol_too,
    test_a_harmless_patrol_bounces_off_the_avatar,
] + TESTS_SHAFT


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
