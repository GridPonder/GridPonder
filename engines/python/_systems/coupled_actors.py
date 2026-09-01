"""CoupledActorsSystem — see docs/dsl/04_systems.md.

On the configured move action, shifts every actor entity on a layer (default
``actors``) one cell in the given direction, all together. Actors are
resolved front-first (the actor closest to the destination edge first) so
that a trailing actor can "train" into a cell the actor ahead of it just
vacated. An actor whose target cell is out of bounds, blocked by a wall
(tagged ``wallTag`` on ``groundLayer``), or still occupied by another actor
stays in place instead of moving — and because the ``occupied`` set is
updated live as each actor resolves, an actor blocked by a wall correctly
"traps" the actor behind it (its target cell never frees up).

Optionally, when the system config has a ``claim`` block (``{"layer": ...,
"map": {kind: territoryKind, ...}}``), an actor that successfully moves to a
new cell also claims that cell in the named territory layer — but only if the
cell is currently empty there; an already-owned territory cell is never
overwritten. Claiming applies only to cells reached by a move this turn, not
to blocked/staying actors or to actors' initial cells.

Optionally, a ``tape`` config block (``{"program": [...], "cycle": bool,
"indexVariable": str}``) drives the system from a stored programme instead of
from the action's direction. The index lives in ``state.variables``, so it is
part of the state key and undo, preview and solver dedup all work unchanged.
With ``cycle`` false the world stops stepping once the programme is exhausted;
with ``cycle`` true it repeats forever and the index stays bounded. ``cycle``
is read strictly — only the boolean ``True`` cycles, so a non-boolean value
(e.g. ``"cycle": 1``) behaves as ``False``.

Optionally, an ``excavate`` config block (``{"diggableTag": str,
"clearedKind": str, "backfillKind": str}``) lets actors cut through terrain
that would otherwise block them: the target cell is reduced to
``clearedKind``, the actor takes it, and the cell it left is backfilled with
``backfillKind`` unless another actor ends the turn standing there. See
``_excavate`` for the semantics and the tolerance contract.
"""
from __future__ import annotations

from .._models import Pos, GameState, dir_delta, transform_delta, CARDINALS, Entity
from .._game_def import GameDef
from .. import _events as ev
from ._base import GameSystem, config_list
from ._claim import apply_claim
from ._excavate import read_excavate, is_diggable, cut, backfill
from ._runtime_var import read_int_variable

# Buckets resolve in this fixed order so that a board whose actors travel in
# several directions at once is still fully deterministic.
_CANONICAL_BUCKETS = ((0, -1), (0, 1), (-1, 0), (1, 0))  # up, down, left, right


def _tape_direction(tape: dict, state: GameState) -> str | None:
    """Next instruction from the tape, advancing the stored index.

    A negative stored index (e.g. from a rewind rule using
    ``increment_variable`` with a negative amount) is clamped to 0 rather than
    wrapping — a rewind-past-the-start is inert, not surprising.

    Returns None when a non-cycling programme is exhausted, which stops the
    world stepping. A cycling programme wraps, so its index stays bounded by
    the programme length — that keeps the joint state space finite for a
    domain solver. ``cycle`` is checked with ``is True`` (not truthy) so a
    typo like ``"cycle": 1`` behaves as non-cycling rather than cycling.
    """
    program = config_list(tape, "program", [])
    if not program:
        return None
    idx_var = tape.get("indexVariable")
    if idx_var is None:
        idx_var = "tapeIndex"
    idx = read_int_variable(state, idx_var)
    if idx < 0:
        idx = 0
    if idx >= len(program):
        if tape.get("cycle") is not True:
            return None
        idx %= len(program)
    state.variables[idx_var] = idx + 1
    return program[idx]


class CoupledActorsSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "coupled_actors")

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        tape = config.get("tape")

        if tape is None:
            move_action = config.get("moveAction", "move")
            if action.get("actionId") != move_action:
                return []
            direction = action.get("params", {}).get("direction")
        else:
            # Tape-driven: the direction comes from the programme, so *any*
            # accepted action steps the world. A vetoed turn cannot leak the
            # advanced index, because the turn engine runs the whole turn on a
            # working copy and discards it on veto.
            direction = _tape_direction(tape, state)

        allowed = config_list(config, "directions", list(CARDINALS))
        if not direction or direction not in allowed:
            return []

        dx, dy = dir_delta(direction)
        if (dx, dy) == (0, 0):
            return []

        actor_layer_id = config.get("actorLayer", "actors")
        ground_layer_id = config.get("groundLayer", "ground")
        wall_tag = config.get("wallTag", "solid")
        claim = config.get("claim")
        excavate = read_excavate(config)

        board = state.board
        actor_layer = board.layers.get(actor_layer_id)
        if actor_layer is None:
            return []

        actors = list(actor_layer.entries())
        if not actors:
            return []

        transforms = config.get("directionTransforms", {}) or {}

        # Each actor travels in its own effective direction.
        triples = [
            (pos, entity, transform_delta((dx, dy), transforms.get(entity.kind)))
            for pos, entity in actors
        ]

        # Bucket by effective direction; buckets resolve in canonical order.
        # Within a bucket, front-first exactly as before: projection onto that
        # bucket's direction descending, then the other-axis coordinate, then
        # kind — fully deterministic. With all-identity transforms there is a
        # single bucket and this reproduces the pre-0.8 order exactly.
        ordered: list[tuple[Pos, Entity, tuple[int, int]]] = []
        for bucket in _CANONICAL_BUCKETS:
            bdx, bdy = bucket
            members = [t for t in triples if t[2] == bucket]
            members.sort(key=lambda t: (
                -(t[0].x * bdx + t[0].y * bdy),
                t[0].x * abs(bdy) + t[0].y * abs(bdx),
                t[1].kind,
            ))
            ordered.extend(members)

        occupied = {pos for pos, _ in actors}
        events: list[dict] = []
        pending_backfill: list[Pos] = []

        for pos, entity, (edx, edy) in ordered:
            target = Pos(pos.x + edx, pos.y + edy)
            in_bounds = board.is_in_bounds(target)
            solid = in_bounds and board.has_tag_at(
                ground_layer_id, target, wall_tag, game.entity_kinds)
            # Only a cell that is *both* solid and diggable is excavated, so
            # walking open ground stays an ordinary move and never backfills.
            digging = solid and is_diggable(
                board, game, ground_layer_id, target, excavate, entity.kind)
            blocked = (
                not in_bounds
                or (solid and not digging)
                or target in occupied
            )
            if blocked:
                events.append(ev.actor_blocked(entity.kind, pos))
                continue

            if digging:
                events.append(cut(board, ground_layer_id, target, excavate))
                pending_backfill.append(pos)

            occupied.discard(pos)
            occupied.add(target)
            board.set_entity(actor_layer_id, pos, None)
            board.set_entity(actor_layer_id, target, entity)
            events.append(ev.actor_moved(entity.kind, pos, target, direction))
            events.append(ev.actor_entered(entity.kind, target, pos, direction))

            claim_event = apply_claim(
                board, game, claim, ground_layer_id, target, entity.kind)
            if claim_event is not None:
                events.append(claim_event)

        # After every actor has resolved: `occupied` is now the final
        # positions for the turn, which is exactly what decides whether a
        # trailing partner hauled each excavator's spoil out.
        events.extend(backfill(
            board, ground_layer_id, pending_backfill, occupied, excavate))

        return events
