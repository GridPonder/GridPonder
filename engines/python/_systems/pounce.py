"""Hunters run down a clear line to prey and capture it."""
from __future__ import annotations

from .. import _events as ev
from .._game_def import GameDef
from .._models import GameState, Pos
from ._base import GameSystem, config_list


class PounceSystem(GameSystem):
    """Mirror of ``engines/dart/lib/src/systems/pounce_system.dart``."""

    def __init__(self, sys_id: str, config: dict | None = None):
        super().__init__(sys_id, "pounce")
        self._config = config

    def execute_cascade_resolution(
        self, trigger_events: list[dict], state: GameState, game: GameDef
    ) -> list[dict]:
        cfg = self._config if self._config is not None else game.system_config(self.id)
        triggers = {
            str(t) for t in config_list(cfg, "triggerEvents", ["multi_cell_object_moved"])
        }
        if not any(e.get("type") in triggers for e in trigger_events):
            return []
        return self._hunt(state, game, cfg)

    def _hunt(self, state: GameState, game: GameDef, cfg: dict) -> list[dict]:
        hunter_roles = {str(r) for r in config_list(cfg, "hunterRoles", [])}
        prey_roles = {str(r) for r in config_list(cfg, "preyRoles", [])}
        if not hunter_roles or not prey_roles:
            return []
        directions = {str(d) for d in config_list(cfg, "directions", ["left", "right"])}
        variable = cfg.get("variable")
        events: list[dict] = []

        captured = True
        while captured:
            captured = False
            hunters = sorted(
                (
                    o
                    for o in state.board.multi_cell_objects
                    if o.params.get("role") is not None
                    and str(o.params["role"]) in hunter_roles
                ),
                key=lambda o: o.id,
            )
            for hunter in hunters:
                prey = self._nearest_prey(hunter, prey_roles, directions, state, game, cfg)
                if prey is None:
                    continue
                from_cells = list(hunter.cells)
                target = prey.cells[0]
                dx = target.x - hunter.cells[0].x
                to_cells = [Pos(c.x + dx, c.y) for c in from_cells]
                state.board.multi_cell_objects = [
                    m for m in state.board.multi_cell_objects if m.id != prey.id
                ]
                hunter.cells = to_cells
                events.append(
                    {
                        "type": "multi_cell_object_moved",
                        "id": hunter.id,
                        "kind": hunter.kind,
                        "fromCells": from_cells,
                        "toCells": to_cells,
                        "direction": "left" if dx < 0 else "right",
                    }
                )
                events.append(
                    {
                        "type": "multi_cell_object_captured",
                        "id": prey.id,
                        "kind": prey.kind,
                        "hunterId": hunter.id,
                        "position": target,
                    }
                )
                if variable is not None:
                    old_value = state.variables.get(str(variable), 0)
                    state.variables[str(variable)] = old_value + 1
                    events.append(
                        ev.variable_changed(str(variable), old_value, old_value + 1)
                    )
                captured = True
                break  # board changed: re-scan from scratch
        return events

    def _nearest_prey(self, hunter, prey_roles, directions, state, game, cfg):
        origin = hunter.cells[0]
        best = None
        best_distance = 1 << 30
        for name, step in (("left", -1), ("right", 1)):
            if name not in directions:
                continue
            x = origin.x + step
            while state.board.is_in_bounds(Pos(x, origin.y)):
                pos = Pos(x, origin.y)
                if state.board.is_void(pos):
                    break
                here = [
                    o
                    for o in state.board.multi_cell_objects
                    if o.id != hunter.id and pos in o.cells
                ]
                if here:
                    obj = here[0]
                    distance = abs(x - origin.x)
                    role = obj.params.get("role")
                    if (
                        role is not None
                        and str(role) in prey_roles
                        and distance < best_distance
                    ):
                        best, best_distance = obj, distance
                    break  # any object ends the line of sight
                if self._blocked_by_entity(pos, state, game, cfg):
                    break
                x += step
        return best

    @staticmethod
    def _blocked_by_entity(pos, state, game, cfg) -> bool:
        tags = [str(t) for t in config_list(cfg, "blockingTags", ["solid"])]
        for layer_id in config_list(cfg, "blockingLayers", ["objects"]):
            entity = state.board.get_entity(str(layer_id), pos)
            if entity is None:
                continue
            if not tags or any(game.has_tag(entity.kind, t) for t in tags):
                return True
        return False
