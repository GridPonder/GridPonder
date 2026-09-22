"""Synchronous threshold cascades over parameterised board cells.

One position-carrying action adds charge to a configured cell.  Every unstable
cell then explodes once per wave from the same snapshot: subtract its threshold,
sum all outgoing contributions, apply them together, and repeat until stable.

The whole transition runs inside action resolution.  This is deliberate: a
malformed non-terminating cascade can veto the action transactionally instead
of leaking the partially settled board that an outer cascade-depth cutoff would
leave behind.
"""
from __future__ import annotations

from .. import _events as ev
from .._game_def import GameDef
from .._models import Entity, GameState, Pos
from ._base import GameSystem


_DEFAULT_KERNELS: dict[str, tuple[tuple[int, int], ...]] = {
    "plus": ((0, -1), (1, 0), (0, 1), (-1, 0)),
    "x": ((-1, -1), (1, -1), (1, 1), (-1, 1)),
    "h": ((-1, 0), (1, 0)),
    "v": ((0, -1), (0, 1)),
}


class CascadeCellsSystem(GameSystem):
    def __init__(self, sys_id: str, config: dict | None = None):
        super().__init__(sys_id, "cascade_cells")
        self._config = config

    def execute_action_resolution(
        self, action: dict, state: GameState, game: GameDef
    ) -> list[dict]:
        config = self._config if self._config is not None else game.system_config(self.id)
        action_id = config.get("action", "tap_cell")
        if action.get("actionId") != action_id:
            return []

        raw_position = action.get("params", {}).get("position")
        try:
            clicked = Pos.from_json(raw_position)
        except (KeyError, TypeError, ValueError, IndexError):
            return [ev.action_vetoed()]
        if not state.board.is_in_bounds(clicked):
            return [ev.action_vetoed()]

        layer_id = config.get("cellLayer", "objects")
        cell_tag = config.get("cellTag", "cascade_cell")
        charge_param = config.get("chargeParam", "charge")
        threshold_param = config.get("thresholdParam", "threshold")
        kernel_param = config.get("kernelParam", "kernel")
        if not all(
            isinstance(value, str) and value
            for value in (layer_id, cell_tag, charge_param, threshold_param, kernel_param)
        ):
            return [ev.action_vetoed()]

        click_delta = config.get("clickDelta", 1)
        max_waves = config.get("maxWaves", 1000)
        if not _is_int(click_delta) or click_delta <= 0:
            return [ev.action_vetoed()]
        if not _is_int(max_waves) or max_waves <= 0:
            return [ev.action_vetoed()]

        kernels = _parse_kernels(config.get("kernels"))
        if kernels is None:
            return [ev.action_vetoed()]

        layer = state.board.layers.get(layer_id)
        if layer is None:
            return [ev.action_vetoed()]

        cells: dict[Pos, tuple[Entity, int, int, str]] = {}
        for position, entity in layer.entries():
            if not game.has_tag(entity.kind, cell_tag):
                continue
            charge = entity.param(charge_param)
            threshold = entity.param(threshold_param)
            kernel = entity.param(kernel_param)
            if (
                not _is_int(charge)
                or charge < 0
                or not _is_int(threshold)
                or threshold <= 0
                or not isinstance(kernel, str)
                or kernel not in kernels
            ):
                return [ev.action_vetoed()]
            cells[position] = (entity, charge, threshold, kernel)

        clicked_data = cells.get(clicked)
        if clicked_data is None:
            return [ev.action_vetoed()]

        events: list[dict] = []
        clicked_entity, clicked_charge, _, _ = clicked_data
        new_clicked_charge = clicked_charge + click_delta
        _set_charge(
            state, layer_id, clicked, clicked_entity, charge_param, new_clicked_charge
        )
        events.append(
            ev.cell_charged(
                clicked,
                before_charge=clicked_charge,
                after_charge=new_clicked_charge,
                delta=click_delta,
                wave=0,
                source="click",
                layer=layer_id,
            )
        )

        completed_waves = 0
        while True:
            snapshot = _snapshot_cells(
                state, layer_id, cell_tag, charge_param, threshold_param,
                kernel_param, kernels, game,
            )
            if snapshot is None:
                return [ev.action_vetoed()]

            unstable = [
                position
                for position, (_, charge, threshold, _) in snapshot.items()
                if charge >= threshold
            ]
            unstable.sort(key=lambda p: (p.y, p.x))
            if not unstable:
                events.append(ev.cascade_settled(completed_waves))
                return events
            if completed_waves >= max_waves:
                return [ev.action_vetoed()]

            wave = completed_waves + 1
            events.append(ev.cascade_wave_started(wave, unstable))

            # All outgoing contributions are computed from one immutable
            # pre-wave snapshot.  Writes happen only after every source has
            # contributed, so iteration order cannot affect the result.
            incoming: dict[Pos, int] = {}
            after_subtraction: dict[Pos, int] = {
                position: charge
                for position, (_, charge, _, _) in snapshot.items()
            }
            for position in unstable:
                entity, charge, threshold, kernel = snapshot[position]
                remainder = charge - threshold
                after_subtraction[position] = remainder
                events.append(
                    ev.cell_exploded(
                        position,
                        before_charge=charge,
                        after_charge=remainder,
                        threshold=threshold,
                        kernel=kernel,
                        wave=wave,
                        layer=layer_id,
                    )
                )
                for dx, dy in kernels[kernel]:
                    destination = Pos(position.x + dx, position.y + dy)
                    if destination in snapshot:
                        incoming[destination] = incoming.get(destination, 0) + 1

            for position in sorted(snapshot, key=lambda p: (p.y, p.x)):
                entity, _charge, _threshold, _kernel = snapshot[position]
                base = after_subtraction[position]
                delta = incoming.get(position, 0)
                after = base + delta
                _set_charge(state, layer_id, position, entity, charge_param, after)
                if delta:
                    events.append(
                        ev.cell_charged(
                            position,
                            before_charge=base,
                            after_charge=after,
                            delta=delta,
                            wave=wave,
                            source="cascade",
                            layer=layer_id,
                        )
                    )

            events.append(ev.cascade_wave_completed(wave, unstable))
            completed_waves = wave


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_kernels(raw) -> dict[str, tuple[tuple[int, int], ...]] | None:
    if raw is None:
        return dict(_DEFAULT_KERNELS)
    if not isinstance(raw, dict) or not raw:
        return None
    parsed: dict[str, tuple[tuple[int, int], ...]] = {}
    for name, offsets in raw.items():
        if not isinstance(name, str) or not name or not isinstance(offsets, list):
            return None
        converted: list[tuple[int, int]] = []
        for offset in offsets:
            if (
                not isinstance(offset, (list, tuple))
                or len(offset) != 2
                or not _is_int(offset[0])
                or not _is_int(offset[1])
            ):
                return None
            converted.append((offset[0], offset[1]))
        parsed[name] = tuple(converted)
    return parsed


def _snapshot_cells(
    state: GameState,
    layer_id: str,
    cell_tag: str,
    charge_param: str,
    threshold_param: str,
    kernel_param: str,
    kernels: dict[str, tuple[tuple[int, int], ...]],
    game: GameDef,
) -> dict[Pos, tuple[Entity, int, int, str]] | None:
    layer = state.board.layers.get(layer_id)
    if layer is None:
        return None
    cells: dict[Pos, tuple[Entity, int, int, str]] = {}
    for position, entity in layer.entries():
        if not game.has_tag(entity.kind, cell_tag):
            continue
        charge = entity.param(charge_param)
        threshold = entity.param(threshold_param)
        kernel = entity.param(kernel_param)
        if (
            not _is_int(charge)
            or charge < 0
            or not _is_int(threshold)
            or threshold <= 0
            or not isinstance(kernel, str)
            or kernel not in kernels
        ):
            return None
        cells[position] = (entity, charge, threshold, kernel)
    return cells


def _set_charge(
    state: GameState,
    layer_id: str,
    position: Pos,
    entity: Entity,
    charge_param: str,
    charge: int,
) -> None:
    params = dict(entity.params)
    params[charge_param] = charge
    state.board.set_entity(layer_id, position, Entity(entity.kind, params))
