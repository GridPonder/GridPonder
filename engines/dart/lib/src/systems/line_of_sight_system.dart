import '../engine/game_system.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';
import 'sight.dart';

/// Detects unobstructed horizontal or vertical sightlines.
///
/// The system is intentionally read-only. It emits `line_of_sight_detected`;
/// rules decide what that relation means for a game.
class LineOfSightSystem extends GameSystem {
  final Map<String, dynamic>? config;

  const LineOfSightSystem({required super.id, this.config})
      : super(type: 'line_of_sight');

  @override
  List<GameEvent> executeCascadeResolution(
    List<GameEvent> triggerEvents,
    LevelState state,
    GameDefinition game,
  ) {
    final effectiveConfig = config ?? game.systemConfig(id, {});
    final configuredTriggers = (effectiveConfig['triggerEvents'] as List? ??
            const ['multi_cell_object_moved'])
        .map((value) => value.toString())
        .toSet();
    if (!triggerEvents.any(
      (event) => configuredTriggers.contains(event.type),
    )) {
      return const [];
    }

    final sources = _sources(state, game, effectiveConfig);
    if (sources.isEmpty) return const [];

    final targetLayerId =
        effectiveConfig['targetLayer'] as String? ?? 'objects';
    final targetLayer = state.board.layers[targetLayerId];
    if (targetLayer == null) return const [];

    final targetKinds = (effectiveConfig['targetKinds'] as List? ?? const [])
        .map((value) => value.toString())
        .toSet();
    final targetTags = (effectiveConfig['targetTags'] as List? ?? const [])
        .map((value) => value.toString())
        .toSet();
    final blockingLayers =
        (effectiveConfig['blockingLayers'] as List? ?? const ['objects'])
            .map((value) => value.toString())
            .toList();
    final blockingTags =
        (effectiveConfig['blockingTags'] as List? ?? const ['solid'])
            .map((value) => value.toString())
            .toList();
    final multiCellObjectsBlock =
        effectiveConfig['multiCellObjectsBlock'] as bool? ?? true;
    final maxMatches = effectiveConfig['maxMatches'] as int? ?? 1;

    final events = <GameEvent>[];
    for (final entry in targetLayer.entries().toList()) {
      final target = entry.key;
      final entity = entry.value;
      if (targetKinds.isNotEmpty && !targetKinds.contains(entity.kind)) {
        continue;
      }
      if (targetTags.isNotEmpty &&
          !targetTags.any((tag) => game.hasTag(entity.kind, tag))) {
        continue;
      }

      _SightSource? matchedSource;
      Position? matchedPosition;
      for (final source in sources) {
        if (multiCellObjectsBlock &&
            coveredByOtherMultiCellObject(
              target,
              source.multiCellObjectId,
              state,
            )) {
          continue;
        }
        for (final sourcePosition in source.positions) {
          if (hasClearLine(
            sourcePosition,
            target,
            source.multiCellObjectId,
            state,
            game,
            blockingLayers,
            blockingTags,
            multiCellObjectsBlock,
          )) {
            matchedSource = source;
            matchedPosition = sourcePosition;
            break;
          }
        }
        if (matchedSource != null) break;
      }

      if (matchedSource == null || matchedPosition == null) continue;
      events.add(
        GameEvent.lineOfSightDetected(
          matchedPosition,
          target,
          entity.kind,
          matchedSource.id,
          matchedSource.kind,
        ),
      );
      if (maxMatches > 0 && events.length >= maxMatches) break;
    }
    return events;
  }

  List<_SightSource> _sources(
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> config,
  ) {
    final sourceKinds = (config['sourceKinds'] as List? ?? const [])
        .map((value) => value.toString())
        .toSet();
    final sourceTags = (config['sourceTags'] as List? ?? const [])
        .map((value) => value.toString())
        .toSet();
    final sourceRoles = (config['sourceRoles'] as List? ?? const [])
        .map((value) => value.toString())
        .toSet();
    final sourceLayerId = config['sourceLayer'] as String?;

    if (sourceLayerId != null) {
      final layer = state.board.layers[sourceLayerId];
      if (layer == null) return const [];
      return [
        for (final entry in layer.entries())
          if (_matchesKindAndTags(
            entry.value.kind,
            sourceKinds,
            sourceTags,
            game,
          ))
            _SightSource(
              '$sourceLayerId:${entry.key.x},${entry.key.y}',
              entry.value.kind,
              [entry.key],
            ),
      ];
    }

    return [
      for (final object in state.board.multiCellObjects)
        if (_matchesKindAndTags(
              object.kind,
              sourceKinds,
              sourceTags,
              game,
            ) &&
            (sourceRoles.isEmpty ||
                sourceRoles.contains(object.params['role']?.toString())))
          _SightSource(
            object.id,
            object.kind,
            object.cells,
            multiCellObjectId: object.id,
          ),
    ];
  }

  bool _matchesKindAndTags(
    String kind,
    Set<String> kinds,
    Set<String> tags,
    GameDefinition game,
  ) {
    if (kinds.isNotEmpty && !kinds.contains(kind)) return false;
    return tags.isEmpty || tags.any((tag) => game.hasTag(kind, tag));
  }
}

class _SightSource {
  final String id;
  final String kind;
  final List<Position> positions;
  final String? multiCellObjectId;

  const _SightSource(
    this.id,
    this.kind,
    this.positions, {
    this.multiCellObjectId,
  });
}
