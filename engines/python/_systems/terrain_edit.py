"""TerrainEditSystem — see docs/dsl/04_systems.md.

Consumes a position-carrying action and writes one entity kind onto a layer,
optionally spending from a runtime budget and optionally guarding what may be
overwritten. This is the generic hook for player-driven terrain change: the
rules engine cannot express it, because there is no "player acted at position"
event — every action must be consumed by a system.

The position normally comes from the action's own `position` param, but when
that's absent and `config.positionVariable` is set, it's read from
`state.variables` instead — lets a zero-param button (e.g. a "place here"
action fired after a separate select/aim step) target whatever position
another action last wrote to that variable.
"""
from __future__ import annotations

from .._models import Pos, GameState, Entity
from .._game_def import GameDef
from .. import _events as ev
from ._base import GameSystem
from ._runtime_var import read_int_variable


def _parse_pos(raw) -> Pos | None:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None
    try:
        return Pos(int(raw[0]), int(raw[1]))
    except (TypeError, ValueError, OverflowError):
        return None


class TerrainEditSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "terrain_edit")

    def execute_action_resolution(
        self, action: dict, state: GameState, game: GameDef
    ) -> list[dict]:
        config = game.system_config(self.id)
        if action.get("actionId") != config.get("action", "place"):
            return []

        pos = _parse_pos(action.get("params", {}).get("position"))
        if pos is None:
            pos_var = config.get("positionVariable")
            if pos_var is not None:
                pos = _parse_pos(state.variables.get(pos_var))
        if pos is None:
            return []
        if not state.board.is_in_bounds(pos):
            return []

        budget_var = config.get("budgetVariable")
        remaining = 0
        if budget_var is not None:
            remaining = read_int_variable(state, budget_var)
            if remaining <= 0:
                return []

        layer_id = config["layer"]
        current = state.board.get_entity(layer_id, pos)
        from_kind = config.get("fromKind")
        if from_kind is not None and (current is None or current.kind != from_kind):
            return []

        to_kind = config["kind"]
        state.board.set_entity(layer_id, pos, Entity(to_kind))
        if budget_var is not None:
            state.variables[budget_var] = remaining - 1

        # "" rather than None for an empty cell, so the payload type matches
        # Dart's non-nullable `fromKind` and the two engines stay comparable.
        previous = current.kind if current is not None else ""
        return [ev.cell_transformed(pos, previous, to_kind, layer_id)]
