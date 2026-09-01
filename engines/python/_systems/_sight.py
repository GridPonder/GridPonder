"""The orthogonal sightline relation, shared by `line_of_sight` and
`follower_npcs` so the two cannot disagree about the same pair of cells."""
from __future__ import annotations

from .._game_def import GameDef
from .._models import GameState, Pos


def covered_by_other_multi_cell_object(
    position: Pos,
    source_multi_cell_object_id: str | None,
    state: GameState,
) -> bool:
    return any(
        item.id != source_multi_cell_object_id and position in item.cells
        for item in state.board.multi_cell_objects
    )


def has_clear_line(
    source: Pos,
    target: Pos,
    source_multi_cell_object_id: str | None,
    state: GameState,
    game: GameDef,
    blocking_layers: list[str],
    blocking_tags: set[str],
    multi_cell_objects_block: bool,
) -> bool:
    if source == target:
        return False
    if source.x != target.x and source.y != target.y:
        return False

    dx = 0 if source.x == target.x else (1 if target.x > source.x else -1)
    dy = 0 if source.y == target.y else (1 if target.y > source.y else -1)
    position = Pos(source.x + dx, source.y + dy)
    while position != target:
        if state.board.is_void(position):
            return False
        if multi_cell_objects_block and covered_by_other_multi_cell_object(
            position,
            source_multi_cell_object_id,
            state,
        ):
            return False
        for layer_id in blocking_layers:
            entity = state.board.get_entity(layer_id, position)
            if entity is None:
                continue
            if not blocking_tags or any(
                game.has_tag(entity.kind, tag) for tag in blocking_tags
            ):
                return False
        position = Pos(position.x + dx, position.y + dy)
    return True
