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
"""
from __future__ import annotations

from .._models import Pos, GameState, dir_delta, CARDINALS, Entity
from .._game_def import GameDef
from .. import _events as ev
from ._base import GameSystem


class CoupledActorsSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "coupled_actors")

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        move_action = config.get("moveAction", "move")
        if action.get("actionId") != move_action:
            return []

        allowed = config.get("directions", list(CARDINALS))
        direction = action.get("params", {}).get("direction")
        if not direction or direction not in allowed:
            return []

        dx, dy = dir_delta(direction)
        if (dx, dy) == (0, 0):
            return []

        actor_layer_id = config.get("actorLayer", "actors")
        ground_layer_id = config.get("groundLayer", "ground")
        wall_tag = config.get("wallTag", "solid")
        claim = config.get("claim")

        board = state.board
        actor_layer = board.layers.get(actor_layer_id)
        if actor_layer is None:
            return []

        actors = list(actor_layer.entries())
        if not actors:
            return []

        # Front-first order: sort by the projection of position onto the
        # direction of travel, descending (the actor nearest the direction
        # of travel resolves first). Ties broken by the other-axis
        # coordinate then kind, for a fully deterministic order.
        actors.sort(key=lambda pe: (
            -(pe[0].x * dx + pe[0].y * dy),
            pe[0].x * abs(dy) + pe[0].y * abs(dx),
            pe[1].kind,
        ))

        occupied = {pos for pos, _ in actors}
        events: list[dict] = []

        for pos, entity in actors:
            target = Pos(pos.x + dx, pos.y + dy)
            blocked = (
                not board.is_in_bounds(target)
                or board.has_tag_at(ground_layer_id, target, wall_tag, game.entity_kinds)
                or target in occupied
            )
            if blocked:
                events.append(ev.actor_blocked(entity.kind, pos))
                continue

            occupied.discard(pos)
            occupied.add(target)
            board.set_entity(actor_layer_id, pos, None)
            board.set_entity(actor_layer_id, target, entity)
            events.append(ev.actor_moved(entity.kind, pos, target, direction))
            events.append(ev.actor_entered(entity.kind, target, pos, direction))

            if claim is not None:
                claim_layer_id = claim["layer"]
                claim_kind = claim.get("map", {}).get(entity.kind)
                if claim_kind is not None and board.get_entity(claim_layer_id, target) is None:
                    board.set_entity(claim_layer_id, target, Entity(claim_kind))
                    events.append(ev.cell_claimed(target, claim_layer_id, claim_kind, entity.kind))

        return events
