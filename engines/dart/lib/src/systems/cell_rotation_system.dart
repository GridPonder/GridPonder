import '../engine/game_system.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// Replaces one cell's entity kind with the next kind in a configured cycle.
///
/// Arrows, mirrors, road pieces, and valves can all opt in without
/// game-specific code.
class CellRotationSystem extends GameSystem {
  const CellRotationSystem({required super.id}) : super(type: 'cell_rotation');

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, {});
    final rotateAction = config['rotateAction'] as String? ?? 'rotate_cell';
    if (action.actionId != rotateAction) return const [];

    final position = _parsePosition(action.params['position']);
    if (position == null || !state.board.isInBounds(position)) {
      return [GameEvent.actionVetoed()];
    }

    final layerId = config['layer'] as String? ?? 'ground';
    final entity = state.board.getEntity(layerId, position);
    if (entity == null) return [GameEvent.actionVetoed()];

    final rawCycles =
        config['cycles'] as Map<String, dynamic>? ?? const <String, dynamic>{};
    final nextKind = rawCycles[entity.kind] as String?;
    if (nextKind == null || !game.entityKinds.containsKey(nextKind)) {
      return [GameEvent.actionVetoed()];
    }

    final blockingLayers = (config['blockingLayers'] as List<dynamic>? ??
            const <dynamic>['objects'])
        .map((value) => value.toString())
        .toList();
    final blockingTags =
        (config['blockingTags'] as List<dynamic>? ?? const <dynamic>[])
            .map((value) => value.toString())
            .toList();

    for (final blockingLayer in blockingLayers) {
      final blocker = state.board.getEntity(blockingLayer, position);
      if (blocker == null) continue;
      if (blockingTags.isEmpty ||
          blockingTags.any((tag) => game.hasTag(blocker.kind, tag))) {
        return [GameEvent.actionVetoed()];
      }
    }

    state.board.setEntity(
      layerId,
      position,
      EntityInstance(nextKind, Map<String, dynamic>.from(entity.params)),
    );
    return [
      GameEvent.cellTransformed(position, entity.kind, nextKind, layerId),
    ];
  }

  Position? _parsePosition(dynamic raw) {
    if (raw is List && raw.length >= 2 && raw[0] is num && raw[1] is num) {
      return Position((raw[0] as num).toInt(), (raw[1] as num).toInt());
    }
    if (raw is Map && raw['x'] is num && raw['y'] is num) {
      return Position((raw['x'] as num).toInt(), (raw['y'] as num).toInt());
    }
    return null;
  }
}
