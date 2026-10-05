"""Rigid multi-cell objects with a configured role fall until they rest."""
from __future__ import annotations

from .._game_def import GameDef
from .. import _events as ev
from .._models import Entity, GameState, Pos, dir_delta
from ._base import GameSystem, config_list


class GravitySystem(GameSystem):
    """Mirror of ``engines/dart/lib/src/systems/gravity_system.dart``."""

    def __init__(self, sys_id: str, config: dict | None = None):
        super().__init__(sys_id, "gravity")
        self._config = config

    def _cfg(self, game: GameDef) -> dict:
        return self._config if self._config is not None else game.system_config(self.id)

    def execute_cascade_resolution(
        self, trigger_events: list[dict], state: GameState, game: GameDef
    ) -> list[dict]:
        cfg = self._cfg(game)
        triggers = {
            str(t) for t in config_list(cfg, "triggerEvents", ["multi_cell_object_moved"])
        }
        if not any(e.get("type") in triggers for e in trigger_events):
            return []
        return self._settle(state, game, cfg, full=False)

    def execute_load_settle(self, state: GameState, game: GameDef) -> list[dict]:
        return self._settle(state, game, self._cfg(game), full=True)

    def execute_derive_state(self, state: GameState, game: GameDef) -> None:
        cfg = self._cfg(game)
        ground_layer = str(cfg.get("groundLayer", "ground"))
        for spec in config_list(cfg, "groundTagVariables", []):
            role, tag, variable = spec.get("role"), spec.get("groundTag"), spec.get("variable")
            if role is None or tag is None or variable is None:
                continue
            count = 0
            for obj in state.board.multi_cell_objects:
                if str(obj.params.get("role")) != str(role):
                    continue
                for cell in obj.cells:
                    ground = state.board.get_entity(ground_layer, cell)
                    if ground is not None and game.has_tag(ground.kind, str(tag)):
                        count += 1
                        break
            state.variables[str(variable)] = count

    def _settle(
        self, state: GameState, game: GameDef, cfg: dict, *, full: bool
    ) -> list[dict]:
        """Fall, then absorb.

        With ``stepsPerPass`` set (and ``full`` false) objects fall that many
        cells per cascade pass instead of all the way, so other systems —
        ``pounce`` — see every intermediate board. Objects that moved this pass
        are not yet at rest, so ``absorb`` skips them; they are absorbed on the
        pass after their last step. Level load always settles fully.
        """
        fall_roles = {str(r) for r in config_list(cfg, "fallRoles", [])}
        if not fall_roles:
            return []
        step_limit = 0 if full else int(cfg.get("stepsPerPass") or 0)
        moved_ids: set[str] = set()
        events = self._fall(state, game, cfg, fall_roles, step_limit, moved_ids)
        events.extend(
            self._absorb(state, game, cfg, moved_ids if step_limit > 0 else set())
        )
        return events

    def _fall(
        self,
        state: GameState,
        game: GameDef,
        cfg: dict,
        fall_roles: set[str],
        step_limit: int,
        moved_ids: set[str],
    ) -> list[dict]:
        direction = str(cfg.get("direction", "down"))
        dx, dy = dir_delta(direction)

        fallers = [
            o
            for o in state.board.multi_cell_objects
            if o.params.get("role") is not None and str(o.params["role"]) in fall_roles
        ]
        if not fallers:
            return []

        def lead(o) -> int:
            return max(p.x * dx + p.y * dy for p in o.cells)

        # Front-most first, id as tiebreak (matches Dart).
        fallers.sort(key=lambda o: o.id)
        fallers.sort(key=lead, reverse=True)

        origin = {o.id: list(o.cells) for o in fallers}
        moved = True
        steps = 0
        while moved and (step_limit == 0 or steps < step_limit):
            moved = False
            steps += 1
            for obj in fallers:
                nxt = [Pos(p.x + dx, p.y + dy) for p in obj.cells]
                if all(self._can_occupy(p, obj, state, game, cfg) for p in nxt):
                    obj.cells = nxt
                    moved_ids.add(obj.id)
                    moved = True

        events = []
        for obj in fallers:
            if origin[obj.id] == obj.cells:
                continue
            events.append(
                {
                    "type": "multi_cell_object_moved",
                    "id": obj.id,
                    "kind": obj.kind,
                    "fromCells": origin[obj.id],
                    "toCells": list(obj.cells),
                    "direction": direction,
                }
            )
        return events

    def _absorb(
        self, state: GameState, game: GameDef, cfg: dict, still_moving: set[str]
    ) -> list[dict]:
        """Objects resting on ``absorb`` ground are consumed by it.

        The object is removed, the ground cell may change kind (optionally
        playing one of the old ground kind's animations) and a counter variable
        goes up. Mirror of ``_absorb`` in the Dart system.
        """
        ground_layer = str(cfg.get("groundLayer", "ground"))
        events: list[dict] = []
        for spec in config_list(cfg, "absorb", []):
            role, tag = spec.get("role"), spec.get("groundTag")
            if role is None or tag is None:
                continue
            to_kind = spec.get("toGroundKind")
            animation = spec.get("animation")
            variable = spec.get("variable")
            for obj in list(state.board.multi_cell_objects):
                if str(obj.params.get("role")) != str(role):
                    continue
                if obj.id in still_moving:
                    continue
                at = None
                for cell in obj.cells:
                    ground = state.board.get_entity(ground_layer, cell)
                    if ground is not None and game.has_tag(ground.kind, str(tag)):
                        at = cell
                        break
                if at is None:
                    continue
                state.board.multi_cell_objects = [
                    m for m in state.board.multi_cell_objects if m.id != obj.id
                ]
                old_kind = state.board.get_entity(ground_layer, at).kind
                events.append(
                    {
                        "type": "multi_cell_object_absorbed",
                        "id": obj.id,
                        "kind": obj.kind,
                        "position": at,
                    }
                )
                if to_kind is not None and str(to_kind) != old_kind:
                    state.board.set_entity(ground_layer, at, Entity(str(to_kind)))
                    events.append(
                        ev.cell_transformed(at, old_kind, str(to_kind), ground_layer)
                    )
                if animation is not None:
                    events.append(ev.object_removed(at, old_kind, str(animation)))
                if variable is not None:
                    old_value = state.variables.get(str(variable), 0)
                    state.variables[str(variable)] = old_value + 1
                    events.append(
                        ev.variable_changed(str(variable), old_value, old_value + 1)
                    )
        return events

    def _can_occupy(
        self, pos: Pos, obj, state: GameState, game: GameDef, cfg: dict
    ) -> bool:
        if not state.board.is_in_bounds(pos) or state.board.is_void(pos):
            return False
        ground = state.board.get_entity(str(cfg.get("groundLayer", "ground")), pos)
        valid = [str(t) for t in config_list(cfg, "validGroundTags", ["walkable"])]
        if ground is None or not any(game.has_tag(ground.kind, t) for t in valid):
            return False
        for other in state.board.multi_cell_objects:
            if other.id != obj.id and pos in other.cells:
                return False
        tags = [str(t) for t in config_list(cfg, "blockingTags", ["solid"])]
        for layer_id in config_list(cfg, "blockingLayers", ["objects"]):
            entity = state.board.get_entity(str(layer_id), pos)
            if entity is None or pos in obj.cells:
                continue
            if not tags or any(game.has_tag(entity.kind, t) for t in tags):
                return False
        return True
