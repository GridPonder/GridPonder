"""CargoGateSystem — see docs/dsl/04_systems.md §2.28.

Colored gate cells that only admit a mover travelling light: an empty mover
may enter any gate, a mover carrying cargo only a gate whose color matches
every item it carries, and never with more than `maxCargo` items. The cargo
is the body of a `trailing_body` system, read from that system's state.

Runs in `action_resolution` and must be listed before the movement system
it guards: a refused move is vetoed, so the turn is not spent.
"""
from __future__ import annotations

from .._models import Pos, GameState, dir_delta
from .._game_def import GameDef
from .. import _events as ev
from ._base import GameSystem


class CargoGateSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "cargo_gate")

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        if action.get("actionId") != config.get("moveAction", "move"):
            return []
        dir_str = action.get("params", {}).get("direction")
        avatar = state.avatar
        if not dir_str or not avatar.enabled or avatar.position is None:
            return []
        dx, dy = dir_delta(dir_str)
        target = Pos(avatar.position.x + dx, avatar.position.y + dy)
        if not state.board.is_in_bounds(target):
            return []

        gate_layer = str(config.get("gateLayer", "ground"))
        gate = state.board.get_entity(gate_layer, target)
        if gate is None or not game.has_tag(gate.kind, str(config.get("gateTag", "cargo_gate"))):
            return []

        cargo = self._cargo_colors(state, config)
        gate_color = gate.param(str(config.get("gateParam", "color")))
        max_cargo = int(config.get("maxCargo", 1))
        allowed = not cargo or (
            len(cargo) <= max_cargo and all(c == gate_color for c in cargo)
        )
        if allowed:
            return []
        return [ev.action_vetoed(), ev.cell_blocked(target, gate_layer, "cargo", gate.kind)]

    @staticmethod
    def _cargo_colors(state: GameState, config: dict) -> list:
        """Colors of the items the mover carries, one per body segment."""
        body_system = config.get("cargoSystem")
        if not body_system:
            return []
        segments = state.variables.get(f"_trailingBody_{body_system}_segments") or []
        return [seg.get("color") for seg in segments]
