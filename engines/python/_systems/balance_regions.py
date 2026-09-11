"""BalanceRegionsSystem — see docs/dsl/04_systems.md."""
from __future__ import annotations
from typing import Optional

from .._models import Pos, Entity, GameState
from .._game_def import GameDef
from .. import _events as ev
from ._base import GameSystem, config_list

#: A settle pass can only repeat because a body fell, and a fall strictly
#: removes weight, so the loop terminates after (bodies + 1) passes. The cap is
#: a guard against a malformed level, not part of the semantics.
_MAX_SETTLE_PASSES = 4


class BalanceRegionsSystem(GameSystem):
    """Terrain driven by where bodies stand.

    Each group owns two *pans* — floor regions identified by ground tags. Every
    body standing on a pan contributes its weight; the heavier pan is down and
    equal weight is level. The resulting *attitude* is written to
    ``stateVariable`` as ``-1`` (first pan down), ``0`` (level) or ``+1``
    (second pan down).

    *Leaves* are cells marked by an inert marker entity. The ground under a
    marker is set to the leaf's ``solidKind`` while the attitude is one of its
    ``solidWhen`` values and to ``openKind`` (default ``"void"``) otherwise.
    Passability then flows through the existing tag machinery: the avatar is
    stopped by ground without its navigation tag, and NPCs are stopped by
    ``void``. A body standing on a leaf that opens falls — actors are removed
    from the board, and the avatar increments ``fallVariable`` so an ordinary
    ``variable_threshold`` lose condition fires in the same turn.

    Leaves are found through their markers rather than by scanning the ground
    for leaf kinds, because an open leaf *is* ``void`` — indistinguishable from
    every wall in the level — and could never be found again.

    Phase: ``npc_resolution``, so declare it *after* the NPC system; the
    attitude then reflects both the avatar's move and the machines'. It also
    runs once at level load, so an authored board cannot contradict its own
    opening attitude.

    Tolerance contract (both engines must agree): a missing or non-dict
    ``groups`` makes the system inert. A group whose ``pans`` is not a list of
    exactly two entries is skipped. Weights that are not integers are ignored,
    as is a marker naming no leaf spec. Ground under a marker that is neither
    ``solidKind`` nor ``openKind`` is left untouched — the level meant it.
    Objects on a falling leaf do not fall; only ``weightLayers`` entities and
    the avatar do.
    """

    def __init__(self, sys_id: str):
        super().__init__(sys_id, "balance_regions")

    def execute_npc_resolution(self, state: GameState, game: GameDef) -> list[dict]:
        return self._settle_all(state, game)

    def execute_load_settle(self, state: GameState, game: GameDef) -> list[dict]:
        return self._settle_all(state, game)

    # -- internals ----------------------------------------------------------

    def _groups(self, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        groups = config.get("groups")
        if not isinstance(groups, dict):
            return []
        return [groups[name] for name in sorted(groups) if isinstance(groups[name], dict)]

    def _settle_all(self, state: GameState, game: GameDef) -> list[dict]:
        events: list[dict] = []
        for group in self._groups(game):
            events.extend(self._settle_group(group, state, game))
        return events

    def _settle_group(self, group: dict, state: GameState, game: GameDef) -> list[dict]:
        pans = group.get("pans")
        if not isinstance(pans, list) or len(pans) != 2:
            return []
        events: list[dict] = []
        for _ in range(_MAX_SETTLE_PASSES):
            attitude, name = self._attitude(group, pans, state, game)
            variable = group.get("stateVariable")
            if isinstance(variable, str) and variable:
                state.variables[variable] = attitude
            if not self._apply_leaves(group, name, state, game, events):
                break
        return events

    def _pan_index(self, group: dict, pans: list, pos: Pos,
                   state: GameState, game: GameDef) -> Optional[int]:
        ground_layer = group.get("groundLayer", "ground")
        ground = state.board.get_entity(str(ground_layer), pos)
        if ground is None:
            return None
        for index, pan in enumerate(pans):
            if not isinstance(pan, dict):
                continue
            for tag in config_list(pan, "groundTags", []):
                if game.has_tag(ground.kind, str(tag)):
                    return index
        return None

    def _attitude(self, group: dict, pans: list,
                  state: GameState, game: GameDef) -> tuple[int, str]:
        weights = group.get("weights")
        weights = weights if isinstance(weights, dict) else {}
        totals = [0, 0]
        for layer_id in config_list(group, "weightLayers", ["actors"]):
            layer = state.board.layers.get(str(layer_id))
            if layer is None:
                continue
            for pos, entity in layer.entries():
                weight = weights.get(entity.kind)
                if not isinstance(weight, int) or isinstance(weight, bool) or weight == 0:
                    continue
                index = self._pan_index(group, pans, pos, state, game)
                if index is not None:
                    totals[index] += weight

        avatar_weight = group.get("avatarWeight", 1)
        avatar = state.avatar
        if (isinstance(avatar_weight, int) and not isinstance(avatar_weight, bool)
                and avatar_weight and avatar.enabled and avatar.position is not None):
            index = self._pan_index(group, pans, avatar.position, state, game)
            if index is not None:
                totals[index] += avatar_weight

        if totals[0] > totals[1]:
            return -1, str(pans[0].get("name", "first"))
        if totals[1] > totals[0]:
            return 1, str(pans[1].get("name", "second"))
        return 0, "level"

    def _leaf_spec(self, leaves: list, marker_kind: str) -> Optional[dict]:
        for spec in leaves:
            if isinstance(spec, dict) and spec.get("marker") == marker_kind:
                return spec
        return None

    def _apply_leaves(self, group: dict, attitude_name: str, state: GameState,
                      game: GameDef, events: list[dict]) -> bool:
        leaves = group.get("leaves")
        if not isinstance(leaves, list) or not leaves:
            return False
        marker_layer = str(group.get("markerLayer", "objects"))
        ground_layer = str(group.get("groundLayer", "ground"))
        layer = state.board.layers.get(marker_layer)
        if layer is None:
            return False

        changed = False
        for pos, marker in list(layer.entries()):
            spec = self._leaf_spec(leaves, marker.kind)
            if spec is None:
                continue
            solid_kind = spec.get("solidKind")
            open_kind = spec.get("openKind", "void")
            if not isinstance(solid_kind, str) or not isinstance(open_kind, str):
                continue
            solid_when = [str(a) for a in config_list(spec, "solidWhen", [])]
            wanted = solid_kind if attitude_name in solid_when else open_kind

            ground = state.board.get_entity(ground_layer, pos)
            current = ground.kind if ground is not None else None
            if current == wanted or current not in (solid_kind, open_kind):
                continue

            params = dict(ground.params) if ground is not None else {}
            state.board.set_entity(ground_layer, pos, Entity(wanted, params))
            events.append(ev.cell_transformed(pos, current, wanted, ground_layer))
            changed = True
            if wanted == open_kind:
                events.extend(self._drop_bodies(group, pos, state))
        return changed

    def _drop_bodies(self, group: dict, pos: Pos, state: GameState) -> list[dict]:
        """Remove whatever was standing on a leaf that just opened."""
        out: list[dict] = []
        for layer_id in config_list(group, "weightLayers", ["actors"]):
            layer_id = str(layer_id)
            entity = state.board.get_entity(layer_id, pos)
            if entity is None:
                continue
            state.board.set_entity(layer_id, pos, None)
            out.append(ev.entity_fell(pos, entity.kind, layer_id))
        avatar = state.avatar
        if avatar.enabled and avatar.position == pos:
            variable = str(group.get("fallVariable", "fell"))
            state.variables[variable] = int(state.variables.get(variable, 0)) + 1
            out.append(ev.entity_fell(pos, "avatar", "avatar"))
        return out
