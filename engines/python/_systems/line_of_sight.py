"""Detect unobstructed orthogonal sightlines between board entities.

The system is read-only. It emits ``line_of_sight_detected`` and leaves the
meaning of that relation to declarative rules.
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import _events as ev
from .._game_def import GameDef
from .._models import GameState, Pos
from ._base import GameSystem


@dataclass(frozen=True)
class _SightSource:
    id: str
    kind: str
    positions: tuple[Pos, ...]
    multi_cell_object_id: str | None = None


class LineOfSightSystem(GameSystem):
    def __init__(self, sys_id: str, config: dict | None = None):
        super().__init__(sys_id, "line_of_sight")
        self._config = config

    def execute_cascade_resolution(
        self,
        trigger_events: list[dict],
        state: GameState,
        game: GameDef,
    ) -> list[dict]:
        config = self._config if self._config is not None else game.system_config(self.id)
        configured_triggers = {
            str(value)
            for value in config.get(
                "triggerEvents",
                ["multi_cell_object_moved"],
            )
        }
        if not any(
            event.get("type") in configured_triggers
            for event in trigger_events
        ):
            return []

        sources = _sources(state, game, config)
        if not sources:
            return []

        target_layer_id = str(config.get("targetLayer", "objects"))
        target_layer = state.board.layers.get(target_layer_id)
        if target_layer is None:
            return []

        target_kinds = {str(value) for value in config.get("targetKinds", [])}
        target_tags = {str(value) for value in config.get("targetTags", [])}
        blocking_layers = [
            str(value) for value in config.get("blockingLayers", ["objects"])
        ]
        blocking_tags = {
            str(value) for value in config.get("blockingTags", ["solid"])
        }
        multi_cell_objects_block = bool(config.get("multiCellObjectsBlock", True))
        max_matches = int(config.get("maxMatches", 1))

        events: list[dict] = []
        for target, entity in list(target_layer.entries()):
            if target_kinds and entity.kind not in target_kinds:
                continue
            if target_tags and not any(
                game.has_tag(entity.kind, tag) for tag in target_tags
            ):
                continue

            match: tuple[_SightSource, Pos] | None = None
            for source in sources:
                if multi_cell_objects_block and _covered_by_other_multi_cell_object(
                    target,
                    source.multi_cell_object_id,
                    state,
                ):
                    continue
                for source_position in source.positions:
                    if _has_clear_line(
                        source_position,
                        target,
                        source.multi_cell_object_id,
                        state,
                        game,
                        blocking_layers,
                        blocking_tags,
                        multi_cell_objects_block,
                    ):
                        match = (source, source_position)
                        break
                if match is not None:
                    break

            if match is None:
                continue
            source, source_position = match
            events.append(
                ev.line_of_sight_detected(
                    source_position,
                    target,
                    entity.kind,
                    source.id,
                    source.kind,
                )
            )
            if max_matches > 0 and len(events) >= max_matches:
                break
        return events


def _sources(state: GameState, game: GameDef, config: dict) -> list[_SightSource]:
    source_kinds = {str(value) for value in config.get("sourceKinds", [])}
    source_tags = {str(value) for value in config.get("sourceTags", [])}
    source_roles = {str(value) for value in config.get("sourceRoles", [])}
    source_layer_id = config.get("sourceLayer")

    if source_layer_id is not None:
        layer_id = str(source_layer_id)
        layer = state.board.layers.get(layer_id)
        if layer is None:
            return []
        return [
            _SightSource(
                f"{layer_id}:{position.x},{position.y}",
                entity.kind,
                (position,),
            )
            for position, entity in layer.entries()
            if _matches_kind_and_tags(
                entity.kind,
                source_kinds,
                source_tags,
                game,
            )
        ]

    return [
        _SightSource(
            item.id,
            item.kind,
            tuple(item.cells),
            multi_cell_object_id=item.id,
        )
        for item in state.board.multi_cell_objects
        if _matches_kind_and_tags(item.kind, source_kinds, source_tags, game)
        and (
            not source_roles
            or (
                item.params.get("role") is not None
                and str(item.params["role"]) in source_roles
            )
        )
    ]


def _matches_kind_and_tags(
    kind: str,
    kinds: set[str],
    tags: set[str],
    game: GameDef,
) -> bool:
    if kinds and kind not in kinds:
        return False
    return not tags or any(game.has_tag(kind, tag) for tag in tags)


def _covered_by_other_multi_cell_object(
    position: Pos,
    source_multi_cell_object_id: str | None,
    state: GameState,
) -> bool:
    return any(
        item.id != source_multi_cell_object_id and position in item.cells
        for item in state.board.multi_cell_objects
    )


def _has_clear_line(
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
        if multi_cell_objects_block and _covered_by_other_multi_cell_object(
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
