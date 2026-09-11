"""FollowerNpcsSystem — see docs/dsl/04_systems.md."""
from __future__ import annotations
from typing import Optional

from .._models import Pos, Entity, GameState, dir_opposite
from .._game_def import GameDef
from .. import _events as ev
from ._base import GameSystem, config_list
from ._sight import has_clear_line

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
        behaviors = config.get("behaviors", {}) or {}
        contact_variable = config.get("contactVariable", "caught")

        if state.board.layers.get("actors") is None:
            return []

        # Collect NPC positions first so the board can be mutated while iterating.
        npc_entries = self._npc_entries(state, game, config)

        # Cells occupied by NPCs after this turn's moves, seeded with every NPC
        # that has not moved yet, so two NPCs cannot land on the same cell.
        occupied_after_move: set[Pos] = {pos for pos, _ in npc_entries}

        events: list[dict] = []

        # Trains resolve as units, before the singletons, so a train's members
        # can never be interleaved with another machine's claim on a cell.
        for shaft_id, members in self._partition_trains(npc_entries):
            if self._train_seized(shaft_id, members, state, config):
                continue
            # Per-member frequency: a geared train's members run at their own
            # rates. The active set is those whose gate opens this beat; the
            # rest are not probed and do not step — but they still turn, in
            # _resolve_train, because facing is train-level state.
            active = [
                (pos, entity) for pos, entity in members
                if self._member_is_active(entity, behaviors, state)
            ]
            if not active:
                continue  # every wheel off-beat: a no-op, NOT a freeze
            for npc_pos, npc_entity, next_pos in self._resolve_train(
                members, active, behaviors, state, game, occupied_after_move,
            ):
                self._apply_npc_move(
                    npc_pos, next_pos, npc_entity, state, contact_variable,
                    occupied_after_move, events,
                )

        for npc_pos, npc_entity in npc_entries:
            if self._shaft_of(npc_entity) is not None:
                continue  # already resolved in the train pass
            behavior_name = npc_entity.param("behavior")
            if behavior_name is None:
                continue
            behavior_def = behaviors.get(str(behavior_name))
            if not isinstance(behavior_def, dict):
                continue
            behavior_type = behavior_def.get("type")
            if behavior_type is None:
                continue

            # Gaze is about seeing, not moving, so it is refreshed before the
            # frequency gate and regardless of whether a step happens.
            sight = None
            if behavior_type == "toward_avatar":
                sight = self._avatar_in_sight(
                    npc_pos, behavior_def, state, game,
                )
                gaze_param = behavior_def.get("gazeParam")
                if gaze_param:
                    avatar_pos = state.avatar.position
                    npc_entity.params[str(gaze_param)] = (
                        _cardinal_toward(npc_pos, avatar_pos)
                        if sight and avatar_pos is not None
                        else "rest"
                    )

            # Reported from wherever the NPC ends the turn, not from where it
            # looked: a chaser steps along the line it just traced.
            npc_id = f"spirit_{npc_pos.x}_{npc_pos.y}"
            report_sight = (
                behavior_type == "toward_avatar"
                and bool(sight)
                and behavior_def.get("requiresLineOfSight", False)
                and state.avatar.position is not None
            )

            def _report_sight_from(pos: Pos) -> None:
                if report_sight:
                    events.append(
                        ev.line_of_sight_detected(
                            pos,
                            state.avatar.position,
                            "avatar",
                            npc_id,
                            npc_entity.kind,
                        )
                    )

            # The turn counter lives on the state, not in the variables map, and
            # is incremented in the goal-evaluation phase after this one — so the
            # first turn sees 0 and a frequency of N acts on turn 1, then every
            # Nth turn after it.
            frequency = behavior_def.get("frequency", 1)
            if frequency > 1 and state.turn_count % frequency != 0:
                _report_sight_from(npc_pos)
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
                sight=sight,
            )

            if next_pos is None or next_pos == npc_pos:
                _report_sight_from(npc_pos)
                continue

            _report_sight_from(next_pos)
            self._apply_npc_move(
                npc_pos, next_pos, npc_entity, state, contact_variable,
                occupied_after_move, events,
            )

        return events

    def _apply_npc_move(
        self, npc_pos: Pos, next_pos: Pos, npc_entity: Entity, state: GameState,
        contact_variable: str, occupied_after_move: set, events: list[dict],
    ) -> None:
        """Commit one NPC step: board, occupancy, npc_moved, and contact.

        Shared by the train pass and the per-NPC loop so both emit identical
        events for identical motion.
        """
        npc_id = f"spirit_{npc_pos.x}_{npc_pos.y}"
        caught = state.avatar.position == next_pos

        occupied_after_move.discard(npc_pos)
        occupied_after_move.add(next_pos)

        state.board.set_entity("actors", npc_pos, None)
        state.board.set_entity("actors", next_pos, npc_entity)

        events.append(ev.npc_moved(npc_id, npc_pos, next_pos))

        if caught:
            # Goal and lose evaluation both run in the phase after this one, so
            # bumping the counter here is enough for a variable_threshold lose
            # condition to fire on the same turn.
            current = state.variables.get(contact_variable, 0)
            state.variables[contact_variable] = int(current) + 1
            events.append(ev.avatar_caught(next_pos, npc_entity.kind, npc_id))

    # -- shafts (linked machines) -------------------------------------------

    def _shaft_of(self, npc_entity: Entity) -> Optional[str]:
        shaft = npc_entity.param("shaft")
        return None if shaft is None else str(shaft)

    def _member_is_active(
        self, npc_entity: Entity, behaviors: dict, state: GameState,
    ) -> bool:
        """True when this member's own frequency gate opens on this turn.

        A train may be geared, so the gate is per member rather than per train.
        A member whose behavior is unknown is inactive rather than fatal: load
        settle has already rejected that board.
        """
        behavior_def = behaviors.get(str(npc_entity.param("behavior")))
        if not isinstance(behavior_def, dict):
            return False
        frequency = behavior_def.get("frequency", 1)
        return frequency <= 1 or state.turn_count % frequency == 0

    def _partition_trains(
        self, npc_entries: list[tuple[Pos, Entity]],
    ) -> list[tuple[str, list[tuple[Pos, Entity]]]]:
        """Shafted NPCs grouped by shaft id, ordered by each train's first member.

        Board order is the order ``actors.entries()`` yields, which is what the
        per-NPC loop already uses — so a board of singletons is unaffected, and a
        board with trains resolves them in the order their first members appear.
        """
        trains: dict[str, list[tuple[Pos, Entity]]] = {}
        for pos, entity in npc_entries:
            shaft = self._shaft_of(entity)
            if shaft is None:
                continue
            trains.setdefault(shaft, []).append((pos, entity))
        return list(trains.items())

    def _resolve_train(
        self, members: list[tuple[Pos, Entity]], active: list[tuple[Pos, Entity]],
        behaviors: dict, state: GameState, game: GameDef, occupied_after_move: set,
    ) -> list[tuple[Pos, Entity, Pos]]:
        """The active members all step forward, else all reverse, else freeze.

        Only ``active`` — the members whose own frequency gate opened this beat —
        is probed and moved. ``members`` is the whole train and matters for
        exactly one thing: a reversal flips EVERY member's facing, on-beat or
        not, because the shaft is rigid in direction.

        Probes without mutating: ``facing`` is written only once the all-reverse
        branch is known to be legal for every active member, so a train that
        freezes resumes its original direction the beat the obstruction leaves.
        """
        def _legal(pos: Pos, entity: Entity, facing: str,
                   claimed: set) -> Optional[Pos]:
            behavior_def = behaviors.get(str(entity.param("behavior")))
            if not isinstance(behavior_def, dict):
                return None
            candidate = pos.moved(facing)
            # Two members whose tracks cross can both reach the crossing on the
            # same beat. Without `claimed` they would both be handed the cell,
            # the second write would overwrite the first, and the train would
            # lose a member with no event to say so — which then reads as a
            # seizure, because the size recorded at load no longer matches.
            if candidate in claimed:
                return None
            ok = self._can_move_to(
                candidate, state, game,
                behavior_def.get("solidBlocking", True),
                occupied_after_move,
                block_avatar=not behavior_def.get("lethalContact", False),
            )
            return candidate if ok else None

        def _probe(reversed_: bool) -> Optional[list[Pos]]:
            """Candidate cells for the whole active set, or None if any is stuck.

            Sequential, so each member's claim blocks the next. The train is
            all-or-nothing, so a collision between two members is simply a
            failed direction: it falls through to the reverse, then to a freeze.
            """
            claimed: set = set()
            out: list[Pos] = []
            for pos, entity in active:
                facing = self._facing_of(entity)
                if reversed_:
                    facing = dir_opposite(facing)
                candidate = _legal(pos, entity, facing, claimed)
                if candidate is None:
                    return None
                claimed.add(candidate)
                out.append(candidate)
            return out

        forward = _probe(False)
        if forward is not None:
            return [(pos, e, c) for (pos, e), c in zip(active, forward)]

        reverse = _probe(True)
        if reverse is not None:
            for _, entity in members:  # the WHOLE train turns, not just the active
                entity.params["facing"] = dir_opposite(self._facing_of(entity))
            return [(pos, e, c) for (pos, e), c in zip(active, reverse)]

        return []

    def _npc_entries(
        self, state: GameState, game: GameDef, config: dict,
    ) -> list[tuple[Pos, Entity]]:
        """Every NPC on the actors layer, in board order.

        Shared by the turn pass and load settle so both agree on what an NPC is.
        """
        actors = state.board.layers.get("actors")
        if actors is None:
            return []
        npc_tags = [str(t) for t in config_list(config, "npcTags", ["npc"])]
        return [
            (pos, entity)
            for pos, entity in actors.entries()
            if any(game.has_tag(entity.kind, tag) for tag in npc_tags)
        ]

    def execute_load_settle(self, state: GameState, game: GameDef) -> list[dict]:
        """Record each train's size once, and reject a train that cannot work.

        Sizing at load is what lets seizure be a pure function of the board: the
        system compares live membership against a constant, so no new mutable
        state enters the state key and solver dedup, undo and preview are all
        unaffected.
        """
        config = game.system_config(self.id)
        behaviors = config.get("behaviors", {}) or {}
        for shaft_id, members in self._partition_trains(
            self._npc_entries(state, game, config)
        ):
            self._validate_train(shaft_id, members, behaviors)
            state.variables[f"shaft_{shaft_id}_size"] = len(members)
        return []

    def _validate_train(
        self, shaft_id: str, members: list[tuple[Pos, Entity]], behaviors: dict,
    ) -> None:
        for pos, entity in members:
            behavior_def = behaviors.get(str(entity.param("behavior")))
            if not isinstance(behavior_def, dict):
                raise ValueError(
                    f"shaft '{shaft_id}': member at {pos} has no known behavior"
                )
            if behavior_def.get("type") != "patrol":
                raise ValueError(
                    f"shaft '{shaft_id}': every member must be a patrol behavior; "
                    f"member at {pos} is '{behavior_def.get('type')}'"
                )
            # Members MAY differ in frequency — that is the ratio shaft, and a
            # geared train is the point. What they may not do is carry a
            # frequency the modulo gate cannot read. `bool` is checked first
            # because it subclasses `int`, so True would otherwise pass as 1.
            frequency = behavior_def.get("frequency", 1)
            if (isinstance(frequency, bool) or not isinstance(frequency, int)
                    or frequency < 1):
                raise ValueError(
                    f"shaft '{shaft_id}': member at {pos} has frequency "
                    f"{frequency!r}; every member's frequency must be a "
                    f"positive integer"
                )
        # A patrol never leaves its facing axis, so its traversal line is its own
        # row or column. Two members sharing one would block each other and the
        # train would jam at t=0 with no way for the player to see why. The test
        # runs against BOTH members' axes: a horizontal member standing on a
        # vertical member's column is on that member's line even though the
        # vertical one is not on the horizontal one's row, and board order must
        # not decide which of the two gets checked.
        def on_line_of(pos: Pos, entity: Entity, other: Pos) -> bool:
            if self._facing_of(entity) in ("left", "right"):
                return pos.y == other.y
            return pos.x == other.x

        for i, (pos_a, entity_a) in enumerate(members):
            for pos_b, entity_b in members[i + 1:]:
                if (on_line_of(pos_a, entity_a, pos_b)
                        or on_line_of(pos_b, entity_b, pos_a)):
                    raise ValueError(
                        f"shaft '{shaft_id}': members at {pos_a} and {pos_b} "
                        f"share a traversal line"
                    )

    def _train_seized(
        self, shaft_id: str, members: list, state: GameState, config: dict,
    ) -> bool:
        """A train that has lost a member never moves again.

        Read strictly: only the boolean True enables seizure, matching the
        `cycle` precedent in coupled_actors.
        """
        if config.get("shaftSeizeOnLoss") is not True:
            return False
        size = state.variables.get(f"shaft_{shaft_id}_size")
        return size is not None and len(members) < int(size)

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
        sight: Optional[bool] = None,
    ) -> Optional[Pos]:
        # One flag governs every behavior: without it the avatar's cell is
        # impassable, so an NPC with no other option stands still or, for the
        # circuit behaviors, turns around.
        lethal_contact = behavior_def.get("lethalContact", False)
        block_avatar = not lethal_contact

        if behavior_type == "toward_avatar":
            avatar_pos = state.avatar.position
            if avatar_pos is None:
                return None
            if sight is None:
                sight = self._avatar_in_sight(npc_pos, behavior_def, state, game)
            if not sight:
                return None
            return self._ranked_step(
                npc_pos, avatar_pos, state, game, solid_blocking,
                occupied_after_move, block_avatar=block_avatar,
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
            return self._ranked_step(
                npc_pos, target, state, game, solid_blocking,
                occupied_after_move, block_avatar=block_avatar,
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
            return self._ranked_step(
                npc_pos, target, state, game, solid_blocking,
                occupied_after_move, block_avatar=block_avatar,
            )

        if behavior_type == "clockwise":
            return self._behavior_clockwise(
                npc_pos, npc_entity, state, game, solid_blocking,
                occupied_after_move, block_avatar,
            )

        if behavior_type == "patrol":
            return self._behavior_patrol(
                npc_pos, npc_entity, state, game, solid_blocking,
                occupied_after_move, block_avatar,
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

    def _avatar_in_sight(
        self, npc_pos: Pos, behavior_def: dict, state: GameState, game: GameDef,
    ) -> bool:
        """Whether this behavior currently considers the avatar visible.

        A behavior without `requiresLineOfSight` chases unconditionally, so it
        always counts as seeing the avatar.
        """
        avatar_pos = state.avatar.position
        if avatar_pos is None:
            return False
        if not behavior_def.get("requiresLineOfSight", False):
            return True
        blocking_layers = [
            str(l) for l in config_list(behavior_def, "blockingLayers", ["objects"])
        ]
        blocking_tags = {
            str(t) for t in config_list(behavior_def, "blockingTags", ["solid"])
        }
        return has_clear_line(
            npc_pos,
            avatar_pos,
            None,
            state,
            game,
            blocking_layers,
            blocking_tags,
            bool(behavior_def.get("multiCellObjectsBlock", True)),
        )

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
        self, npc_pos, npc_entity, state, game, solid_blocking,
        occupied_after_move, block_avatar=True,
    ) -> Optional[Pos]:
        facing = self._facing_of(npc_entity)
        for _ in range(len(_CLOCKWISE_ORDER)):
            candidate = npc_pos.moved(facing)
            if self._can_move_to(
                candidate, state, game, solid_blocking, occupied_after_move,
                block_avatar=block_avatar,
            ):
                npc_entity.params["facing"] = facing
                return candidate
            facing = _rotate_clockwise(facing)
        return None

    def _behavior_patrol(
        self, npc_pos, npc_entity, state, game, solid_blocking,
        occupied_after_move, block_avatar=True,
    ) -> Optional[Pos]:
        facing = self._facing_of(npc_entity)

        candidate = npc_pos.moved(facing)
        if self._can_move_to(
            candidate, state, game, solid_blocking, occupied_after_move,
            block_avatar=block_avatar,
        ):
            return candidate

        reversed_facing = dir_opposite(facing)
        reversed_candidate = npc_pos.moved(reversed_facing)
        if self._can_move_to(
            reversed_candidate, state, game, solid_blocking, occupied_after_move,
            block_avatar=block_avatar,
        ):
            npc_entity.params["facing"] = reversed_facing
            return reversed_candidate

        return None
