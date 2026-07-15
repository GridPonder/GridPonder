"""Shared claim application for the actor systems.

Single home for the `claim` config block (`{layer, map, overwrite}`) so that
`coupled_actors` and `individual_actors` cannot drift apart. See
docs/dsl/04_systems.md.
"""
from __future__ import annotations

from .._models import Entity
from .. import _events as ev


def _is_overwritable(board, game, pos, claim, ground_layer_id) -> bool:
    overwrite = claim.get("overwrite") or {}
    mode = overwrite.get("mode", "never")
    if mode == "always":
        return True
    if mode == "tagged":
        tag = overwrite.get("tag")
        if not tag:
            return False
        layer_id = overwrite.get("layer", ground_layer_id)
        return board.has_tag_at(layer_id, pos, tag, game.entity_kinds)
    return False


def apply_claim(board, game, claim, ground_layer_id, target, actor_kind):
    """Claim `target` for `actor_kind`. Returns a cell_claimed event or None.

    - empty cell                         -> claimed
    - owned by another, overwritable     -> repainted
    - owned by another, not overwritable -> untouched (a transit)
    - already owned by this kind         -> untouched, no event
    """
    if claim is None:
        return None
    claim_kind = claim.get("map", {}).get(actor_kind)
    if claim_kind is None:
        return None

    claim_layer_id = claim["layer"]
    current = board.get_entity(claim_layer_id, target)
    if current is not None:
        if current.kind == claim_kind:
            return None
        if not _is_overwritable(board, game, target, claim, ground_layer_id):
            return None

    board.set_entity(claim_layer_id, target, Entity(claim_kind))
    return ev.cell_claimed(target, claim_layer_id, claim_kind, actor_kind)
