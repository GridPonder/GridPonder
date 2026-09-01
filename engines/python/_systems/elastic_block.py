"""Inflate and collapse one rectangular multi-cell object."""
from __future__ import annotations

from dataclasses import dataclass

from .. import _events as ev
from .._game_def import GameDef
from .._models import Entity, GameState, MultiCellObject, Pos, dir_delta
from ._base import GameSystem, config_list


_CARDINAL_DIRECTIONS = {"up", "down", "left", "right"}


def _cfg(config: dict, key: str, default):
    value = config.get(key)
    return default if value is None else value


@dataclass(frozen=True)
class _Push:
    layer: str
    source: Pos
    destination: Pos
    entity: Entity


class ElasticBlockSystem(GameSystem):
    def __init__(self, sys_id: str, config: dict | None = None):
        super().__init__(sys_id, "elastic_block")
        self._config = config

    def execute_action_resolution(
        self,
        action: dict,
        state: GameState,
        game: GameDef,
    ) -> list[dict]:
        config = (
            self._config
            if self._config is not None
            else game.system_config(self.id)
        )
        if action.get("actionId") != _cfg(config, "moveAction", "move"):
            return []

        direction = action.get("params", {}).get("direction")
        directions = {
            str(value)
            for value in config_list(
                config, "directions", ["up", "down", "left", "right"]
            )
        }
        if (
            not isinstance(direction, str)
            or direction not in _CARDINAL_DIRECTIONS
            or direction not in directions
        ):
            return [ev.action_vetoed()]

        object_kind = str(_cfg(config, "objectKind", "elastic_block"))
        blocks = [
            item for item in state.board.multi_cell_objects
            if item.kind == object_kind
        ]
        if len(blocks) != 1 or not _is_rectangle(blocks[0].cells):
            return [ev.action_vetoed()]

        block = blocks[0]
        old_cells = list(block.cells)
        next_line = _leading_line(old_cells, direction, 1)
        pushes = _line_pushes(next_line, direction, block, state, game, config)
        events: list[dict] = []

        if pushes is None:
            if not bool(_cfg(config, "collapseWhenBlocked", True)):
                return _no_op(config)
            thickness = max(1, int(_cfg(config, "collapseThickness", 1)))
            new_cells = _collapsed_cells(old_cells, direction, thickness)
            if set(new_cells) == set(old_cells):
                return _no_op(config)
            block.cells = new_cells
            events.append({
                "type": "elastic_block_collapsed",
                "id": block.id,
                "kind": block.kind,
                "fromCells": old_cells,
                "toCells": list(new_cells),
                "direction": direction,
            })
        else:
            inflate_mode = str(_cfg(config, "inflateMode", "to_obstacle"))
            if inflate_mode not in {"to_obstacle", "single_step"}:
                return [ev.action_vetoed()]

            added_cells: list[Pos] = []
            distance = 0
            while pushes is not None:
                _apply_pushes(pushes, state, direction, events)
                added_cells.extend(next_line)
                block.cells.extend(next_line)
                distance += 1
                if inflate_mode == "single_step":
                    break
                next_line = _leading_line(block.cells, direction, 1)
                pushes = _line_pushes(next_line, direction, block, state, game, config)

            events.append({
                "type": "elastic_block_inflated",
                "id": block.id,
                "kind": block.kind,
                "fromCells": old_cells,
                "toCells": list(block.cells),
                "addedCells": added_cells,
                "direction": direction,
                "distance": distance,
            })

        events.extend(_update_targets(block, state, config))
        return events


def _no_op(config: dict) -> list[dict]:
    return [ev.action_vetoed()] if bool(_cfg(config, "rejectNoOpMoves", True)) else []


def _is_rectangle(cells: list[Pos]) -> bool:
    if not cells or len(set(cells)) != len(cells):
        return False
    min_x = min(pos.x for pos in cells)
    max_x = max(pos.x for pos in cells)
    min_y = min(pos.y for pos in cells)
    max_y = max(pos.y for pos in cells)
    expected = {
        Pos(x, y)
        for y in range(min_y, max_y + 1)
        for x in range(min_x, max_x + 1)
    }
    return set(cells) == expected


def _leading_line(cells: list[Pos], direction: str, offset: int) -> list[Pos]:
    min_x = min(pos.x for pos in cells)
    max_x = max(pos.x for pos in cells)
    min_y = min(pos.y for pos in cells)
    max_y = max(pos.y for pos in cells)
    if direction == "left":
        return [Pos(min_x - offset, y) for y in range(min_y, max_y + 1)]
    if direction == "right":
        return [Pos(max_x + offset, y) for y in range(min_y, max_y + 1)]
    if direction == "up":
        return [Pos(x, min_y - offset) for x in range(min_x, max_x + 1)]
    return [Pos(x, max_y + offset) for x in range(min_x, max_x + 1)]


def _collapsed_cells(cells: list[Pos], direction: str, thickness: int) -> list[Pos]:
    min_x = min(pos.x for pos in cells)
    max_x = max(pos.x for pos in cells)
    min_y = min(pos.y for pos in cells)
    max_y = max(pos.y for pos in cells)
    if direction == "left":
        max_x = min(max_x, min_x + thickness - 1)
    elif direction == "right":
        min_x = max(min_x, max_x - thickness + 1)
    elif direction == "up":
        max_y = min(max_y, min_y + thickness - 1)
    else:
        min_y = max(min_y, max_y - thickness + 1)
    return [
        Pos(x, y)
        for y in range(min_y, max_y + 1)
        for x in range(min_x, max_x + 1)
    ]


def _line_pushes(
    line: list[Pos],
    direction: str,
    block: MultiCellObject,
    state: GameState,
    game: GameDef,
    config: dict,
) -> list[_Push] | None:
    pushes: list[_Push] = []
    for pos in line:
        if not _valid_ground(pos, state, game, config):
            return None
        if any(
            pos in other.cells
            for other in state.board.multi_cell_objects
            if other.id != block.id
        ):
            return None

        blockers = _blocking_entities(pos, state, game, config)
        if not blockers:
            continue
        if len(blockers) != 1:
            return None
        layer, entity = blockers[0]
        pushable_tags = [
            str(tag) for tag in config_list(config, "pushableTags", ["pushable"])
        ]
        if not any(game.has_tag(entity.kind, tag) for tag in pushable_tags):
            return None
        dx, dy = dir_delta(direction)
        destination = Pos(pos.x + dx, pos.y + dy)
        if not _push_destination_clear(
            destination, layer, block, state, game, config
        ):
            return None
        pushes.append(_Push(layer, pos, destination, entity))

    destinations = [push.destination for push in pushes]
    if len(set(destinations)) != len(destinations):
        return None
    return pushes


def _valid_ground(pos: Pos, state: GameState, game: GameDef, config: dict) -> bool:
    if not state.board.is_in_bounds(pos) or state.board.is_void(pos):
        return False
    ground_layer = str(_cfg(config, "groundLayer", "ground"))
    ground = state.board.get_entity(ground_layer, pos)
    valid_tags = [
        str(tag) for tag in config_list(config, "validGroundTags", ["walkable"])
    ]
    return ground is not None and any(
        game.has_tag(ground.kind, tag) for tag in valid_tags
    )


def _blocking_entities(
    pos: Pos, state: GameState, game: GameDef, config: dict
) -> list[tuple[str, Entity]]:
    layers = [
        str(layer) for layer in config_list(config, "blockingLayers", ["objects"])
    ]
    tags = [str(tag) for tag in config_list(config, "blockingTags", ["solid"])]
    found: list[tuple[str, Entity]] = []
    for layer in layers:
        entity = state.board.get_entity(layer, pos)
        if entity is not None and (
            not tags or any(game.has_tag(entity.kind, tag) for tag in tags)
        ):
            found.append((layer, entity))
    return found


def _push_destination_clear(
    pos: Pos,
    push_layer: str,
    block: MultiCellObject,
    state: GameState,
    game: GameDef,
    config: dict,
) -> bool:
    if not _valid_ground(pos, state, game, config):
        return False
    if any(
        pos in other.cells
        for other in state.board.multi_cell_objects
        if other.id != block.id
    ):
        return False
    if state.board.get_entity(push_layer, pos) is not None:
        return False
    if _blocking_entities(pos, state, game, config):
        return False
    return True


def _apply_pushes(
    pushes: list[_Push], state: GameState, direction: str, events: list[dict]
) -> None:
    for push in pushes:
        state.board.set_entity(push.layer, push.source, None)
    for push in pushes:
        state.board.set_entity(push.layer, push.destination, push.entity)
        events.append(
            ev.object_pushed(
                push.entity.kind, push.source, push.destination, direction
            )
        )


def _target_cells(state: GameState, layer_id: str, marker_kind: str) -> set[Pos]:
    layer = state.board.layers.get(layer_id)
    if layer is None:
        return set()
    return {pos for pos, entity in layer.entries() if entity.kind == marker_kind}


def _string_set(value) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value}


def _update_targets(
    block: MultiCellObject, state: GameState, config: dict
) -> list[dict]:
    raw_targets = config_list(config, "targets", [])
    if not raw_targets:
        return []

    completed_key = str(
        _cfg(config, "completedTargetIdsVariable", "completedTargetIds")
    )
    consumed_key = str(
        _cfg(config, "consumedTargetIdsVariable", "consumedTargetIds")
    )
    count_key = str(_cfg(config, "completedTargetsVariable", "completedTargetCount"))
    completed = _string_set(state.variables.get(completed_key, []))
    consumed = _string_set(state.variables.get(consumed_key, []))
    block_cells = set(block.cells)
    target_layer = str(_cfg(config, "targetLayer", "markers"))
    events: list[dict] = []

    for raw in raw_targets:
        if not isinstance(raw, dict):
            continue
        marker_kind = str(_cfg(raw, "markerKind", ""))
        target_id = str(_cfg(raw, "id", marker_kind))
        if not target_id or not marker_kind:
            continue
        marker_layer = str(_cfg(raw, "markerLayer", target_layer))
        cells = _target_cells(state, marker_layer, marker_kind)
        if not cells:
            continue

        if (
            target_id in completed
            and target_id not in consumed
            and block_cells.isdisjoint(cells)
        ):
            on_leave = str(_cfg(raw, "onLeave", "none"))
            _consume_target(
                cells, marker_kind, marker_layer, on_leave, raw, state, events
            )
            consumed.add(target_id)
            events.append({
                "type": "target_consumed",
                "targetId": target_id,
                "mode": on_leave,
            })

        if target_id not in completed and block_cells == cells:
            completed.add(target_id)
            events.append({"type": "target_completed", "targetId": target_id})

    old_completed = state.variables.get(completed_key, [])
    old_consumed = state.variables.get(consumed_key, [])
    old_count = state.variables.get(count_key, 0)
    new_completed = sorted(completed)
    new_consumed = sorted(consumed)
    if old_completed != new_completed:
        state.variables[completed_key] = new_completed
        events.append(ev.variable_changed(completed_key, old_completed, new_completed))
    if old_consumed != new_consumed:
        state.variables[consumed_key] = new_consumed
        events.append(ev.variable_changed(consumed_key, old_consumed, new_consumed))
    if old_count != len(completed):
        state.variables[count_key] = len(completed)
        events.append(ev.variable_changed(count_key, old_count, len(completed)))
    return events


def _consume_target(
    cells: set[Pos],
    marker_kind: str,
    marker_layer: str,
    mode: str,
    target: dict,
    state: GameState,
    events: list[dict],
) -> None:
    if mode == "void":
        layer = str(_cfg(target, "groundLayer", "ground"))
        kind = str(_cfg(target, "voidKind", "void"))
    elif mode == "wall":
        layer = str(_cfg(target, "wallLayer", "objects"))
        kind = str(_cfg(target, "wallKind", "wall"))
    else:
        layer = ""
        kind = ""

    for pos in sorted(cells, key=lambda cell: (cell.y, cell.x)):
        state.board.set_entity(marker_layer, pos, None)
        events.append(ev.cell_cleared(pos, marker_kind, marker_layer))
        if layer:
            previous = state.board.get_entity(layer, pos)
            state.board.set_entity(layer, pos, Entity(kind))
            events.append(
                ev.cell_transformed(
                    pos,
                    previous.kind if previous is not None else "empty",
                    kind,
                    layer,
                )
            )
