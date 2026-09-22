"""AvatarNavigationSystem — see docs/dsl/04_systems.md."""
from __future__ import annotations
from collections import deque
from typing import Any, Optional

from .._models import (
    Pos, Entity, GameState, PendingMove, OverlayCursor,
    dir_delta, dir_opposite, is_cardinal, CARDINALS,
)
from .._game_def import GameDef
from .. import _events as ev
from ._base import GameSystem, config_list
from .follower_npcs import facing_of, predict_circuit_step

# Behavior types whose next step depends only on the NPC's own
# position/facing and the board — never on where the avatar ends up this
# turn. Only these are safe to predict from `execute_action_resolution`,
# which runs before the avatar's own move is even decided. `toward_avatar`,
# `toward_tag` and `toward_color` explicitly chase a target, so predicting
# them here would be a real circular dependency (the avatar's move would
# depend on the NPC's move, which depends on the avatar's move) and must
# never be attempted — see `_npc_is_vacating` below.
_PREDICTABLE_BEHAVIOR_TYPES = frozenset({"patrol", "clockwise"})


class AvatarNavigationSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "avatar_navigation")

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        move_action = config.get("moveAction", "move")
        if action.get("actionId") != move_action:
            return []
        allowed = config.get("directions", list(CARDINALS))
        dir_str = action.get("params", {}).get("direction")
        if not dir_str or dir_str not in allowed:
            return []

        avatar = state.avatar
        if not avatar.enabled or avatar.position is None:
            return []

        pos = avatar.position
        board = state.board
        dx, dy = dir_delta(dir_str)
        target = Pos(pos.x + dx, pos.y + dy)

        # Only the moves that never land; a successful step turns further down.
        if config.get("faceOnBlockedMove") is True:
            state.avatar.facing = dir_str

        if not board.is_in_bounds(target):
            return []
        if board.is_void(target):
            return []

        valid_ground_tags = config_list(config, "validGroundTags", [])
        if valid_ground_tags:
            ground_layer = config.get("groundLayer", "ground")
            ground_entity = board.get_entity(ground_layer, target)
            if ground_entity is None or not any(
                game.has_tag(ground_entity.kind, tag) for tag in valid_ground_tags
            ):
                return []

        solid_handling = config.get("solidHandling", "block")
        solid_layers = config_list(config, "solidLayers", ["objects"])
        # Layers where a block is a genuine non-move, not a wait: the press
        # never had a legal outcome (e.g. the avatar's own trailing body sits
        # wherever it just came from, so pressing straight back into it can
        # never succeed). Distinct from an ordinary solid block, which is
        # still a meaningful spent turn — bumping a wall to wait out a
        # hazard is a real, deliberately-supported move elsewhere on this
        # platform. Empty by default, so this changes nothing for a pack
        # that never sets it.
        veto_layers = set(config_list(config, "vetoLayers", []))
        # Layers where a blocking `patrol`/`clockwise` follower_npcs NPC that
        # is genuinely about to step off this cell this same turn should not
        # cost the player a wasted press. Empty by default, so this changes
        # nothing for a pack that never sets it. See `_npc_is_vacating` for
        # the exact rule, its scope (never chasing behaviors), and a note on
        # when its start-of-turn board snapshot can go stale.
        yielding_layers = set(config_list(config, "yieldingLayers", []))
        entity_at_target = None
        entity_layer = None
        for layer_id in solid_layers:
            candidate = board.get_entity(str(layer_id), target)
            if candidate is not None and game.has_tag(candidate.kind, "solid"):
                entity_at_target = candidate
                entity_layer = str(layer_id)
                break

        if entity_at_target is not None:
            yielding = (
                entity_layer is not None
                and entity_layer in yielding_layers
                and _npc_is_vacating(entity_at_target, target, state, game)
            )
            if not yielding:
                if entity_layer is not None and entity_layer in veto_layers:
                    return [ev.action_vetoed()]
                if solid_handling == "block":
                    return []
                elif solid_handling == "delegate":
                    state.pending_move = PendingMove(pos, target, dir_str)
                    return [ev.move_blocked(target, pos, dir_str, entity_at_target.kind)]
                return []
            # else: the NPC is vacating `target` this turn — fall through and
            # let the avatar move in exactly as if the cell were empty.

        state.avatar.position = target
        state.avatar.facing = dir_str
        return [ev.avatar_exited(pos), ev.avatar_entered(target, pos, dir_str)]


def _npc_is_vacating(
    npc_entity: Entity, npc_pos: Pos, state: GameState, game: GameDef,
) -> bool:
    """Whether a `patrol`/`clockwise` follower_npcs NPC blocking [npc_pos] is
    genuinely about to step off it this same turn.

    Resolves [npc_entity]'s `behavior` param against every `follower_npcs`
    system on the level (there can be more than one instance) to find the
    behavior definition, then — only for `patrol`/`clockwise`, never for a
    chasing behavior (`toward_avatar`/`toward_tag`/`toward_color`), and never
    for a shaft (train) member — predicts its next step with
    `follower_npcs.predict_circuit_step`, the exact same function
    `FollowerNpcsSystem` itself uses. `True` only when that prediction lands
    somewhere other than [npc_pos]. Note the *predicted* landing cell can
    differ from where the NPC actually lands: this prediction still sees the
    avatar at its pre-move position (the real move hasn't happened yet), so a
    candidate step that happens to be the avatar's own starting cell reads as
    blocked here but may be free by the time `npc_resolution` actually runs,
    after the avatar has moved off it. That can steer the NPC's real step to
    a different cell than predicted — but never changes the vacate/stay
    conclusion this function reports, which is all the caller needs:
    block_avatar only ever goes from "blocked" (prediction) to "open"
    (reality) as the avatar vacates its own old cell, never the reverse, so
    this can only make the prediction more conservative, never less.

    Chasing behaviors are excluded on purpose: their step depends on where
    the avatar ends up this turn, so predicting them here — before the
    avatar's own move is even decided — would be a real circular dependency.
    Shaft members are excluded because they resolve as a unit through
    `FollowerNpcsSystem._resolve_train` (cross-member "claimed cell"
    probing), a different algorithm than the standalone `predict_circuit_step`
    used here; predicting one member in isolation could disagree with how the
    train actually moves together.

    Staleness note (read before reusing this elsewhere): this reads board
    state as it stands at the very start of the turn, before the avatar's own
    move, `movement_resolution`, or `cascade_resolution` have run. That is
    safe exactly when nothing in those later phases can add or remove a
    `solid`-tagged entity on the `objects` layer (or, when the behavior sets
    `movementBlockingLayers`, any of those additional layers — the only layers a
    patrol/clockwise NPC's `solidBlocking` check reads) at a cell this
    prediction depends on. It does NOT hold in general: `push_objects`
    (`movement_resolution`) and cascade-phase systems such as `ice_slide` and
    `portals` all move or remove solid entities on the `objects` layer as a
    direct consequence of this same turn's action, so a pack that combines
    `yieldingLayers` with any of those against a patrol/clockwise NPC's path
    could see this prediction go stale by the time `npc_resolution` actually
    runs. It IS safe for a pack (such as Hitch) whose only interaction here
    is `follower_npcs` itself with no push/slide/portal mechanic touching the
    `objects` layer (or a configured `movementBlockingLayers` layer) near the
    yielding NPC's path.
    """
    behavior_name = npc_entity.param("behavior")
    if behavior_name is None:
        return False

    behavior_def: Optional[dict] = None
    npc_tags: list[str] = []
    for system in game.systems:
        if system.get("type") != "follower_npcs" or not system.get("enabled", True):
            continue
        sys_config = system.get("config") or {}
        behaviors = sys_config.get("behaviors", {}) or {}
        candidate = behaviors.get(str(behavior_name))
        if isinstance(candidate, dict):
            behavior_def = candidate
            npc_tags = [str(t) for t in config_list(sys_config, "npcTags", ["npc"])]
            break

    if behavior_def is None:
        return False
    behavior_type = behavior_def.get("type")
    if behavior_type not in _PREDICTABLE_BEHAVIOR_TYPES:
        return False
    if npc_entity.param("shaft") is not None:
        return False

    facing = facing_of(npc_entity)
    solid_blocking = behavior_def.get("solidBlocking", True)
    movement_blocking_layers = [
        str(l) for l in config_list(behavior_def, "movementBlockingLayers", [])
    ]
    block_avatar = not behavior_def.get("lethalContact", False)

    # Mirrors the initial `occupied_after_move` follower_npcs itself seeds at
    # the top of `execute_npc_resolution` for this same system instance:
    # every NPC matching its npcTags, at its current (not-yet-moved) position.
    occupied_after_move: set[Pos] = set()
    actors_layer = state.board.layers.get("actors")
    if actors_layer is not None:
        occupied_after_move = {
            pos for pos, entity in actors_layer.entries()
            if any(game.has_tag(entity.kind, tag) for tag in npc_tags)
        }

    next_pos, _ = predict_circuit_step(
        behavior_type, npc_pos, facing, state, game, solid_blocking,
        occupied_after_move, block_avatar, movement_blocking_layers,
    )
    return next_pos is not None and next_pos != npc_pos

