"""SlidingBlocksSystem — direct movement for rigid multi-cell objects."""
from __future__ import annotations

from .._models import Pos, Entity, GameState, dir_delta
from .._game_def import GameDef
from .. import _events as ev
from ._base import GameSystem


class SlidingBlocksSystem(GameSystem):
    def __init__(self, sys_id: str, config: dict | None = None):
        super().__init__(sys_id, "sliding_blocks")
        self._config = config

    def execute_action_resolution(self, action: dict, state: GameState, game: GameDef) -> list[dict]:
        config = self._config if self._config is not None else game.system_config(self.id)
        if action.get("actionId") != config.get("moveAction", "move"):
            return []

        params = action.get("params", {})
        direction = params.get("direction")
        start = _parse_pos(params.get("position"))
        if direction is None or start is None:
            return [ev.action_vetoed()]

        block = _block_at(state, start)
        if block is None:
            return [ev.action_vetoed()]

        if not _axis_allows(block.params.get("axis", "both"), direction):
            return [ev.action_vetoed()]

        dx, dy = dir_delta(direction)
        old_cells = list(block.cells)
        new_cells = [Pos(p.x + dx, p.y + dy) for p in old_cells]
        old_set = set(old_cells)
        events: list[dict] = []

        if any(not state.board.is_in_bounds(p) for p in new_cells):
            if not _can_escape(block, old_cells, direction, state, game, config):
                return [ev.action_vetoed()]
            state.board.multi_cell_objects = [
                m for m in state.board.multi_cell_objects if m.id != block.id
            ]
            variable = config.get("escapedVariable", "escapedCount")
            old_value = state.variables.get(variable, 0)
            new_value = old_value + 1
            state.variables[variable] = new_value
            return [
                {
                    "type": "multi_cell_object_exited",
                    "id": block.id,
                    "kind": block.kind,
                    "direction": direction,
                },
                ev.variable_changed(variable, old_value, new_value),
            ]

        events.extend(_resolve_object_interactions(new_cells, state, game, config))

        for cell in new_cells:
            if not _is_valid_destination(cell, old_set, state, game, config):
                return [ev.action_vetoed()]

        block.cells = new_cells
        events.append(
            {
                "type": "multi_cell_object_moved",
                "id": block.id,
                "kind": block.kind,
                "fromCells": old_cells,
                "toCells": new_cells,
                "direction": direction,
            }
        )
        events.extend(_collect_on_enter(block, new_cells, state, game, config))
        events.extend(_reveal_uncovered(state, config))
        events.extend(_line_of_sight_collect(block, state, game, config))
        return events


def _parse_pos(raw) -> Pos | None:
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return Pos(int(raw[0]), int(raw[1]))
    return None


def _block_at(state: GameState, pos: Pos):
    for block in state.board.multi_cell_objects:
        if pos in block.cells:
            return block
    return None


def _axis_allows(axis: str, direction: str) -> bool:
    if axis == "horizontal":
        return direction in {"left", "right"}
    if axis == "vertical":
        return direction in {"up", "down"}
    if axis == "both":
        return direction in {"up", "down", "left", "right"}
    return False


def _is_valid_destination(
    pos: Pos,
    moving_block_cells: set[Pos],
    state: GameState,
    game: GameDef,
    config: dict,
) -> bool:
    if not state.board.is_in_bounds(pos) or state.board.is_void(pos):
        return False

    ground = state.board.get_entity("ground", pos)
    valid_ground_tags = [str(t) for t in config.get("validGroundTags", ["walkable"])]
    if ground is None or not any(game.has_tag(ground.kind, tag) for tag in valid_ground_tags):
        return False

    for other in state.board.multi_cell_objects:
        for cell in other.cells:
            if cell == pos and cell not in moving_block_cells:
                return False

    blocking_layers = [str(t) for t in config.get("blockingLayers", ["objects"])]
    blocking_tags = [str(t) for t in config.get("blockingTags", ["solid"])]
    for layer_id in blocking_layers:
        entity = state.board.get_entity(layer_id, pos)
        if entity is None:
            continue
        if pos in moving_block_cells:
            continue
        if not blocking_tags or any(game.has_tag(entity.kind, tag) for tag in blocking_tags):
            return False

    return True


def _can_escape(block, old_cells: list[Pos], direction: str, state: GameState, game: GameDef, config: dict) -> bool:
    if block.params.get("role") != "escapee":
        return False

    exit_tags = [str(t) for t in config.get("exitTags", ["exit"])]
    if not exit_tags:
        return True

    if direction == "right":
        edge = max(p.x for p in old_cells)
        edge_cells = [p for p in old_cells if p.x == edge]
    elif direction == "left":
        edge = min(p.x for p in old_cells)
        edge_cells = [p for p in old_cells if p.x == edge]
    elif direction == "down":
        edge = max(p.y for p in old_cells)
        edge_cells = [p for p in old_cells if p.y == edge]
    elif direction == "up":
        edge = min(p.y for p in old_cells)
        edge_cells = [p for p in old_cells if p.y == edge]
    else:
        return False

    for cell in edge_cells:
        ground = state.board.get_entity("ground", cell)
        if ground is not None and any(game.has_tag(ground.kind, tag) for tag in exit_tags):
            return True
    return False


def _reveal_uncovered(state: GameState, config: dict) -> list[dict]:
    events: list[dict] = []
    for item in config.get("revealOnUncovered", []):
        pos = _parse_pos(item.get("position"))
        kind = item.get("kind")
        if pos is None or kind is None:
            continue

        variable = item.get("revealedVariable")
        if variable and state.variables.get(variable):
            continue
        if _block_at(state, pos) is not None:
            continue

        layer_id = str(item.get("layer", "objects"))
        if state.board.get_entity(layer_id, pos) is not None:
            continue

        state.board.set_entity(layer_id, pos, Entity(str(kind)))
        events.append(ev.object_placed(pos, str(kind)))
        if variable:
            old_value = state.variables.get(variable, False)
            state.variables[variable] = True
            events.append(ev.variable_changed(str(variable), old_value, True))

    return events


def _collect_on_enter(block, new_cells: list[Pos], state: GameState, game: GameDef, config: dict) -> list[dict]:
    events: list[dict] = []
    for item in config.get("collectOnEnter", []):
        roles = {str(r) for r in item.get("roles", [])}
        if roles and str(block.params.get("role")) not in roles:
            continue
        layer_id = str(item.get("layer", "objects"))
        collect_kinds = {str(k) for k in item.get("kinds", [])}
        collect_tags = {str(t) for t in item.get("tags", [])}
        variable = item.get("variable")
        remove = item.get("remove", True)
        for pos in new_cells:
            entity = state.board.get_entity(layer_id, pos)
            if entity is None:
                continue
            if collect_kinds and entity.kind not in collect_kinds:
                continue
            if collect_tags and not any(game.has_tag(entity.kind, tag) for tag in collect_tags):
                continue
            if remove:
                state.board.set_entity(layer_id, pos, None)
                events.append(ev.object_removed(pos, entity.kind))
            if variable:
                old_value = state.variables.get(variable, 0)
                new_value = old_value + 1
                state.variables[variable] = new_value
                events.append(ev.variable_changed(str(variable), old_value, new_value))
    return events


def _resolve_object_interactions(new_cells: list[Pos], state: GameState, game: GameDef, config: dict) -> list[dict]:
    events: list[dict] = []
    for item in config.get("objectInteractions", []):
        layer_id = str(item.get("layer", "objects"))
        target_kinds = {str(k) for k in item.get("targetKinds", [])}
        target_tags = {str(t) for t in item.get("targetTags", [])}
        required_variable = item.get("requiredVariable")
        if required_variable is not None:
            min_value = item.get("minValue", 1)
            if state.variables.get(str(required_variable), 0) < min_value:
                continue
        to_kind = item.get("toKind")
        remove = item.get("remove", False)
        for pos in new_cells:
            entity = state.board.get_entity(layer_id, pos)
            if entity is None:
                continue
            if target_kinds and entity.kind not in target_kinds:
                continue
            if target_tags and not any(game.has_tag(entity.kind, tag) for tag in target_tags):
                continue
            if remove:
                state.board.set_entity(layer_id, pos, None)
                events.append(ev.object_removed(pos, entity.kind))
            elif to_kind is not None:
                state.board.set_entity(layer_id, pos, Entity(str(to_kind)))
                events.append(ev.cell_transformed(pos, entity.kind, str(to_kind), layer_id))
    return events


def _line_of_sight_collect(block, state: GameState, game: GameDef, config: dict) -> list[dict]:
    events: list[dict] = []
    for item in config.get("lineOfSightCollect", []):
        roles = {str(r) for r in item.get("roles", [])}
        if roles and str(block.params.get("role")) not in roles:
            continue
        layer_id = str(item.get("layer", "objects"))
        layer = state.board.layers.get(layer_id)
        if layer is None:
            continue
        collect_kinds = {str(k) for k in item.get("kinds", [])}
        collect_tags = {str(t) for t in item.get("tags", [])}
        variable = item.get("variable")
        remove = item.get("remove", True)
        blocking_layers = [str(t) for t in item.get("blockingLayers", config.get("blockingLayers", ["objects"]))]
        blocking_tags = [str(t) for t in item.get("blockingTags", config.get("blockingTags", ["solid"]))]

        for key_pos, entity in list(layer.entries()):
            if collect_kinds and entity.kind not in collect_kinds:
                continue
            if collect_tags and not any(game.has_tag(entity.kind, tag) for tag in collect_tags):
                continue
            if not any(_has_clear_line(cell, key_pos, block, state, game, blocking_layers, blocking_tags) for cell in block.cells):
                continue
            if remove:
                state.board.set_entity(layer_id, key_pos, None)
                events.append(ev.object_removed(key_pos, entity.kind))
            if variable:
                old_value = state.variables.get(variable, 0)
                new_value = old_value + 1
                state.variables[variable] = new_value
                events.append(ev.variable_changed(str(variable), old_value, new_value))
            break
    return events


def _has_clear_line(
    source: Pos,
    target: Pos,
    source_block,
    state: GameState,
    game: GameDef,
    blocking_layers: list[str],
    blocking_tags: list[str],
) -> bool:
    if source.x != target.x and source.y != target.y:
        return False
    dx = 0 if source.x == target.x else (1 if target.x > source.x else -1)
    dy = 0 if source.y == target.y else (1 if target.y > source.y else -1)
    pos = Pos(source.x + dx, source.y + dy)
    while pos != target:
        if state.board.is_void(pos):
            return False
        blocker = _block_at(state, pos)
        if blocker is not None and blocker.id != source_block.id:
            return False
        for layer_id in blocking_layers:
            entity = state.board.get_entity(layer_id, pos)
            if entity is None:
                continue
            if not blocking_tags or any(game.has_tag(entity.kind, tag) for tag in blocking_tags):
                return False
        pos = Pos(pos.x + dx, pos.y + dy)
    return True
