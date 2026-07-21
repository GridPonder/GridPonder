"""Direct movement for rigid multi-cell objects."""
from __future__ import annotations

from .. import _events as ev
from .._game_def import GameDef
from .._models import GameState, Pos, dir_delta
from ._base import GameSystem


class SlidingBlocksSystem(GameSystem):
    def __init__(self, sys_id: str, config: dict | None = None):
        super().__init__(sys_id, "sliding_blocks")
        self._config = config

    def execute_action_resolution(
        self,
        action: dict,
        state: GameState,
        game: GameDef,
    ) -> list[dict]:
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
        new_cells = [Pos(pos.x + dx, pos.y + dy) for pos in old_cells]
        old_cell_set = set(old_cells)

        if any(not state.board.is_in_bounds(pos) for pos in new_cells):
            if not _can_escape(block, old_cells, direction, state, game, config):
                return [ev.action_vetoed()]
            state.board.multi_cell_objects = [
                item for item in state.board.multi_cell_objects if item.id != block.id
            ]
            variable = str(config.get("escapedVariable", "escapedCount"))
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

        if any(
            not _is_valid_destination(
                pos,
                block,
                old_cell_set,
                state,
                game,
                config,
            )
            for pos in new_cells
        ):
            return [ev.action_vetoed()]

        block.cells = new_cells
        return [
            {
                "type": "multi_cell_object_moved",
                "id": block.id,
                "kind": block.kind,
                "fromCells": old_cells,
                "toCells": new_cells,
                "direction": direction,
            }
        ]


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
    moving_block,
    current_cells: set[Pos],
    state: GameState,
    game: GameDef,
    config: dict,
) -> bool:
    if not state.board.is_in_bounds(pos) or state.board.is_void(pos):
        return False

    ground_layer = str(config.get("groundLayer", "ground"))
    ground = state.board.get_entity(ground_layer, pos)
    valid_ground_tags = [
        str(tag) for tag in config.get("validGroundTags", ["walkable"])
    ]
    if ground is None or not any(
        game.has_tag(ground.kind, tag) for tag in valid_ground_tags
    ):
        return False

    for other in state.board.multi_cell_objects:
        if other.id == moving_block.id:
            continue
        if pos in other.cells:
            return False

    blocking_layers = [
        str(layer) for layer in config.get("blockingLayers", ["objects"])
    ]
    blocking_tags = [
        str(tag) for tag in config.get("blockingTags", ["solid"])
    ]
    coverable_tags = [
        str(tag) for tag in config.get("coverableTags", [])
    ]
    coverable_blocked_roles = {
        str(role)
        for role in config.get("coverableBlockedRoles", [])
    }
    moving_role = moving_block.params.get("role")

    for layer_id in blocking_layers:
        entity = state.board.get_entity(layer_id, pos)
        if entity is None:
            continue
        if pos in current_cells:
            continue
        if blocking_tags and not any(
            game.has_tag(entity.kind, tag) for tag in blocking_tags
        ):
            continue
        can_cover = any(
            game.has_tag(entity.kind, tag) for tag in coverable_tags
        ) and (
            moving_role is None
            or str(moving_role) not in coverable_blocked_roles
        )
        if not can_cover:
            return False

    return True


def _can_escape(
    block,
    old_cells: list[Pos],
    direction: str,
    state: GameState,
    game: GameDef,
    config: dict,
) -> bool:
    escape_roles = {
        str(role) for role in config.get("escapeRoles", [])
    }
    role = block.params.get("role")
    if role is None or str(role) not in escape_roles:
        return False

    exit_tags = [str(tag) for tag in config.get("exitTags", ["exit"])]
    if not exit_tags:
        return True

    if direction == "right":
        edge = max(pos.x for pos in old_cells)
        edge_cells = [pos for pos in old_cells if pos.x == edge]
    elif direction == "left":
        edge = min(pos.x for pos in old_cells)
        edge_cells = [pos for pos in old_cells if pos.x == edge]
    elif direction == "down":
        edge = max(pos.y for pos in old_cells)
        edge_cells = [pos for pos in old_cells if pos.y == edge]
    elif direction == "up":
        edge = min(pos.y for pos in old_cells)
        edge_cells = [pos for pos in old_cells if pos.y == edge]
    else:
        return False

    for cell in edge_cells:
        ground_layer = str(config.get("groundLayer", "ground"))
        ground = state.board.get_entity(ground_layer, cell)
        if ground is not None and any(
            game.has_tag(ground.kind, tag) for tag in exit_tags
        ):
            return True
    return False
