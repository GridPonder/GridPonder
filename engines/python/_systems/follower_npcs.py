"""FollowerNpcsSystem — see docs/dsl/04_systems.md."""
from __future__ import annotations
from collections import deque
from typing import Any, Optional

from .._models import (
    Pos, Entity, GameState, PendingMove, OverlayCursor,
    dir_delta, dir_opposite, is_cardinal, CARDINALS,
)
from .._game_def import GameDef
from .. import _events as ev
from ._base import GameSystem

# Cardinal scan order used when ranking candidate steps.
_CARDINAL_ORDER = ("up", "down", "left", "right")

# Clockwise rotation order: right -> down -> left -> up -> right
_CLOCKWISE_ORDER = ("right", "down", "left", "up")

_DIR_KEYS = frozenset({
    "up", "down", "left", "right",
    "up_left", "up_right", "down_left", "down_right",
})


def _manhattan(a: Pos, b: Pos) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def _cardinal_toward(from_pos: Pos, target: Pos) -> str:
    """Dominant-axis step direction, x-axis preferred on ties."""
    dx = target.x - from_pos.x
    dy = target.y - from_pos.y
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "down" if dy > 0 else "up"


def _rotate_clockwise(current: str) -> str:
    try:
        idx = _CLOCKWISE_ORDER.index(current)
    except ValueError:
        return "right"
    return _CLOCKWISE_ORDER[(idx + 1) % len(_CLOCKWISE_ORDER)]


class FollowerNpcsSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "follower_npcs")

    def execute_npc_resolution(self, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        npc_tags = [str(t) for t in config.get("npcTags", ["npc"])]
        behaviors = config.get("behaviors", {}) or {}

        board = state.board
        actors = board.layers.get("actors")
        if actors is None:
            return []

        # Collect NPC positions first so the board can be mutated while iterating.
        npc_entries = [
            (pos, entity)
            for pos, entity in actors.entries()
            if any(game.has_tag(entity.kind, tag) for tag in npc_tags)
        ]

        # Cells occupied by NPCs after this turn's moves, seeded with every NPC
        # that has not moved yet, so two NPCs cannot land on the same cell.
        occupied_after_move: set[Pos] = {pos for pos, _ in npc_entries}

        events: list[dict] = []

        for npc_pos, npc_entity in npc_entries:
            behavior_name = npc_entity.param("behavior")
            if behavior_name is None:
                continue
            behavior_def = behaviors.get(str(behavior_name))
            if not isinstance(behavior_def, dict):
                continue
            behavior_type = behavior_def.get("type")
            if behavior_type is None:
                continue

            # The turn counter lives on the state, not in the variables map, and
            # is incremented in the goal-evaluation phase after this one — so the
            # first turn sees 0 and a frequency of N acts on turn 1, then every
            # Nth turn after it.
            frequency = behavior_def.get("frequency", 1)
            if frequency > 1 and state.turn_count % frequency != 0:
                continue

            solid_blocking = behavior_def.get("solidBlocking", True)

            next_pos = self._compute_next_position(
                npc_pos=npc_pos,
                npc_entity=npc_entity,
                behavior_type=behavior_type,
                behavior_def=behavior_def,
                state=state,
                game=game,
                solid_blocking=solid_blocking,
                occupied_after_move=occupied_after_move,
            )

            if next_pos is None or next_pos == npc_pos:
                continue

            occupied_after_move.discard(npc_pos)
            occupied_after_move.add(next_pos)

            board.set_entity("actors", npc_pos, None)
            board.set_entity("actors", next_pos, npc_entity)

            npc_id = f"spirit_{npc_pos.x}_{npc_pos.y}"
            events.append(ev.npc_moved(npc_id, npc_pos, next_pos))

        return events

    # -- behavior dispatch ---------------------------------------------------

    def _compute_next_position(
        self,
        npc_pos: Pos,
        npc_entity: Entity,
        behavior_type: str,
        behavior_def: dict,
        state: GameState,
        game: GameDef,
        solid_blocking: bool,
        occupied_after_move: set,
    ) -> Optional[Pos]:
        if behavior_type == "toward_avatar":
            avatar_pos = state.avatar.position
            if avatar_pos is None:
                return None
            if behavior_def.get("requiresLineOfSight", False):
                blocking_layers = [
                    str(l) for l in behavior_def.get("blockingLayers", ["objects"])
                ]
                blocking_tags = [
                    str(t) for t in behavior_def.get("blockingTags", ["solid"])
                ]
                if not self._has_line_of_sight(
                    npc_pos, avatar_pos, state, game, blocking_layers, blocking_tags,
                ):
                    return None
            return self._step_toward(
                npc_pos, avatar_pos, state, game, solid_blocking, occupied_after_move,
            )

        if behavior_type == "toward_tag":
            target_tag = behavior_def.get("targetTag")
            if target_tag is None:
                return None
            target = self._nearest_tagged(
                npc_pos, str(target_tag), ("objects", "markers"), state, game,
            )
            if target is None:
                return None
            return self._step_toward_unguarded(
                npc_pos, target, state, game, solid_blocking, occupied_after_move,
            )

        if behavior_type == "toward_color":
            target_color = behavior_def.get("targetColor")
            if target_color is None:
                return None
            target = self._nearest_colored(
                npc_pos, str(target_color), ("objects", "actors"), state,
            )
            if target is None:
                return None
            return self._step_toward_unguarded(
                npc_pos, target, state, game, solid_blocking, occupied_after_move,
            )

        if behavior_type == "clockwise":
            return self._behavior_clockwise(
                npc_pos, npc_entity, state, game, solid_blocking, occupied_after_move,
            )

        if behavior_type == "patrol":
            return self._behavior_patrol(
                npc_pos, npc_entity, state, game, solid_blocking, occupied_after_move,
            )

        return None

    # -- passability --------------------------------------------------------

    def _no_solid_object(self, state: GameState, game: GameDef, pos: Pos) -> bool:
        entity = state.board.get_entity("objects", pos)
        if entity is None:
            return True
        return not game.has_tag(entity.kind, "solid")

    def _can_move_to(
        self,
        pos: Pos,
        state: GameState,
        game: GameDef,
        solid_blocking: bool,
        occupied_after_move: set,
        block_avatar: bool,
    ) -> bool:
        board = state.board
        if not board.is_in_bounds(pos):
            return False
        if board.is_void(pos):
            return False
        # NOTE: only the avatar-seeking path refuses to enter the avatar's cell.
        # The Dart implementation omits this check in the tag/color/clockwise/
        # patrol branches, so the port keeps the asymmetry to stay in parity.
        if block_avatar and state.avatar.position == pos:
            return False
        if pos in occupied_after_move:
            return False
        if solid_blocking and not self._no_solid_object(state, game, pos):
            return False
        return True

    # -- sight --------------------------------------------------------------

    def _has_line_of_sight(
        self,
        from_pos: Pos,
        to_pos: Pos,
        state: GameState,
        game: GameDef,
        blocking_layers: list,
        blocking_tags: list,
    ) -> bool:
        """Same relation the line_of_sight system detects.

        Source and target must share a row or column, differ in position, and
        every strictly-intermediate cell must be clear. Void ground breaks the
        line, as does any entity on a blocking layer carrying a blocking tag —
        an empty tag list means every entity on those layers blocks.
        """
        if from_pos == to_pos:
            return False
        if from_pos.x != to_pos.x and from_pos.y != to_pos.y:
            return False

        if from_pos.x == to_pos.x:
            step = 1 if to_pos.y > from_pos.y else -1
            between = [
                Pos(from_pos.x, y)
                for y in range(from_pos.y + step, to_pos.y, step)
            ]
        else:
            step = 1 if to_pos.x > from_pos.x else -1
            between = [
                Pos(x, from_pos.y)
                for x in range(from_pos.x + step, to_pos.x, step)
            ]

        board = state.board
        for pos in between:
            if board.is_void(pos):
                return False
            for layer_id in blocking_layers:
                entity = board.get_entity(layer_id, pos)
                if entity is None:
                    continue
                if not blocking_tags or any(
                    game.has_tag(entity.kind, tag) for tag in blocking_tags
                ):
                    return False
        return True

    # -- stepping -----------------------------------------------------------

    def _ranked_step(
        self,
        npc_pos: Pos,
        target: Pos,
        state: GameState,
        game: GameDef,
        solid_blocking: bool,
        occupied_after_move: set,
        block_avatar: bool,
    ) -> Optional[Pos]:
        """First passable step that strictly reduces Manhattan distance.

        Directions are tried with the dominant axis first, then the remaining
        cardinals in fixed order. Because every distance-reducing cardinal step
        reduces the distance by exactly one, the first accepted candidate also
        ends up being the best one.
        """
        preferred = _cardinal_toward(npc_pos, target)
        ordered = [preferred] + [d for d in _CARDINAL_ORDER if d != preferred]

        best: Optional[Pos] = None
        best_dist = _manhattan(npc_pos, target)

        for direction in ordered:
            candidate = npc_pos.moved(direction)
            dist = _manhattan(candidate, target)
            if dist >= best_dist:
                continue
            if self._can_move_to(
                candidate, state, game, solid_blocking, occupied_after_move,
                block_avatar,
            ):
                best_dist = dist
                best = candidate

        return best

    def _step_toward(
        self, npc_pos, target, state, game, solid_blocking, occupied_after_move,
    ) -> Optional[Pos]:
        return self._ranked_step(
            npc_pos, target, state, game, solid_blocking, occupied_after_move,
            block_avatar=True,
        )

    def _step_toward_unguarded(
        self, npc_pos, target, state, game, solid_blocking, occupied_after_move,
    ) -> Optional[Pos]:
        return self._ranked_step(
            npc_pos, target, state, game, solid_blocking, occupied_after_move,
            block_avatar=False,
        )

    # -- target search ------------------------------------------------------

    def _nearest_tagged(
        self, npc_pos: Pos, tag: str, layer_ids: tuple, state: GameState, game: GameDef,
    ) -> Optional[Pos]:
        nearest: Optional[Pos] = None
        nearest_dist = 999999
        for layer_id in layer_ids:
            layer = state.board.layers.get(layer_id)
            if layer is None:
                continue
            for pos, entity in layer.entries():
                if not game.has_tag(entity.kind, tag):
                    continue
                dist = _manhattan(npc_pos, pos)
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest = pos
        return nearest

    def _nearest_colored(
        self, npc_pos: Pos, color: str, layer_ids: tuple, state: GameState,
    ) -> Optional[Pos]:
        nearest: Optional[Pos] = None
        nearest_dist = 999999
        for layer_id in layer_ids:
            layer = state.board.layers.get(layer_id)
            if layer is None:
                continue
            for pos, entity in layer.entries():
                if str(entity.param("color")) != color:
                    continue
                dist = _manhattan(npc_pos, pos)
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest = pos
        return nearest

    # -- circuit behaviors --------------------------------------------------

    def _facing_of(self, npc_entity: Entity) -> str:
        facing = npc_entity.param("facing")
        facing = "right" if facing is None else str(facing)
        return facing if facing in _DIR_KEYS else "right"

    def _behavior_clockwise(
        self, npc_pos, npc_entity, state, game, solid_blocking, occupied_after_move,
    ) -> Optional[Pos]:
        facing = self._facing_of(npc_entity)
        for _ in range(len(_CLOCKWISE_ORDER)):
            candidate = npc_pos.moved(facing)
            if self._can_move_to(
                candidate, state, game, solid_blocking, occupied_after_move,
                block_avatar=False,
            ):
                npc_entity.params["facing"] = facing
                return candidate
            facing = _rotate_clockwise(facing)
        return None

    def _behavior_patrol(
        self, npc_pos, npc_entity, state, game, solid_blocking, occupied_after_move,
    ) -> Optional[Pos]:
        facing = self._facing_of(npc_entity)

        candidate = npc_pos.moved(facing)
        if self._can_move_to(
            candidate, state, game, solid_blocking, occupied_after_move,
            block_avatar=False,
        ):
            return candidate

        reversed_facing = dir_opposite(facing)
        reversed_candidate = npc_pos.moved(reversed_facing)
        if self._can_move_to(
            reversed_candidate, state, game, solid_blocking, occupied_after_move,
            block_avatar=False,
        ):
            npc_entity.params["facing"] = reversed_facing
            return reversed_candidate

        return None
