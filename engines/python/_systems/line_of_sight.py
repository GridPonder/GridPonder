"""Detect unobstructed orthogonal sightlines between board entities.

The system is read-only. It emits ``line_of_sight_detected`` and leaves the
meaning of that relation to declarative rules.
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import _events as ev
from .._game_def import GameDef
from .._models import GameState, Pos
from ._base import GameSystem, config_list
from ._sight import covered_by_other_multi_cell_object, has_clear_line


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

        target_kinds = {str(value) for value in config_list(config, "targetKinds", [])}
        target_tags = {str(value) for value in config_list(config, "targetTags", [])}
        blocking_layers = [
            str(value) for value in config_list(config, "blockingLayers", ["objects"])
        ]
        blocking_tags = {
            str(value) for value in config_list(config, "blockingTags", ["solid"])
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
                if multi_cell_objects_block and covered_by_other_multi_cell_object(
                    target,
                    source.multi_cell_object_id,
                    state,
                ):
                    continue
                for source_position in source.positions:
                    if has_clear_line(
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
    source_kinds = {str(value) for value in config_list(config, "sourceKinds", [])}
    source_tags = {str(value) for value in config_list(config, "sourceTags", [])}
    source_roles = {str(value) for value in config_list(config, "sourceRoles", [])}
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
