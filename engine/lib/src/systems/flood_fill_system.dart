import 'dart:collection';

import '../engine/game_system.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';
import '../models/direction.dart';
import '../models/entity.dart';

class FloodFillSystem extends GameSystem {
  const FloodFillSystem({required super.id}) : super(type: 'flood_fill');

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, {});

    final floodAction = config['floodAction'] as String? ?? 'flood';
    if (action.actionId != floodAction) return const [];

    final sourcePositionMode =
        config['sourcePosition'] as String? ?? 'avatar';
    final affectedLayer = config['affectedLayer'] as String? ?? 'objects';
    final matchBy = config['matchBy'] as String? ?? 'color';

    final colorCycleRaw = config['colorCycle'] as List<dynamic>? ??
        ['red', 'blue', 'green', 'yellow', 'purple', 'orange'];
    final colorCycle = colorCycleRaw.map((c) => c.toString()).toList();

    final kindTransformRaw =
        config['kindTransform'] as Map<String, dynamic>? ?? {};
    final kindTransform = kindTransformRaw
        .map((k, v) => MapEntry(k, v.toString()));

    final board = state.board;
    final layer = board.layers[affectedLayer];
    if (layer == null) return const [];

    // Determine source position.
    final Position sourcePos;
    if (sourcePositionMode == 'overlay_center') {
      final overlay = state.overlay;
      if (overlay == null) return const [];
      sourcePos = Position(
        overlay.x + overlay.width ~/ 2,
        overlay.y + overlay.height ~/ 2,
      );
    } else {
      // Default: "avatar"
      final avatarPos = state.avatar.position;
      if (avatarPos == null) return const [];
      sourcePos = avatarPos;
    }

    // Get source entity.
    final sourceEntity = layer.getAt(sourcePos);
    if (sourceEntity == null) return const [];

    // BFS to find all connected cells matching the fill criterion.
    final visited = <Position>{};
    final queue = Queue<Position>();
    queue.add(sourcePos);
    visited.add(sourcePos);

    final String matchValue;
    if (matchBy == 'color') {
      matchValue = sourceEntity.param('color') as String? ?? '';
    } else {
      // matchBy == 'kind'
      matchValue = sourceEntity.kind;
    }

    final cardinalDirections = [
      Direction.up,
      Direction.down,
      Direction.left,
      Direction.right,
    ];

    while (queue.isNotEmpty) {
      final current = queue.removeFirst();

      for (final dir in cardinalDirections) {
        final neighbor = current.moved(dir);
        if (visited.contains(neighbor)) continue;
        if (!board.isInBounds(neighbor)) continue;

        final entity = layer.getAt(neighbor);
        if (entity == null) continue;

        bool matches;
        if (matchBy == 'color') {
          matches = (entity.param('color') as String?) == matchValue;
        } else {
          matches = entity.kind == matchValue;
        }

        if (matches) {
          visited.add(neighbor);
          queue.add(neighbor);
        }
      }
    }

    // Apply transformation to all visited cells.
    final affectedPositions = <Position>[];

    for (final pos in visited) {
      final entity = layer.getAt(pos);
      if (entity == null) continue;

      EntityInstance? newEntity;

      if (matchBy == 'color') {
        final currentColor = entity.param('color') as String? ?? '';
        final colorIndex = colorCycle.indexOf(currentColor);
        final nextColor = colorIndex >= 0
            ? colorCycle[(colorIndex + 1) % colorCycle.length]
            : (colorCycle.isNotEmpty ? colorCycle[0] : currentColor);
        final newParams = Map<String, dynamic>.from(entity.params)
          ..['color'] = nextColor;
        newEntity = entity.copyWith(params: newParams);
      } else {
        // matchBy == 'kind'
        final nextKind = kindTransform[entity.kind];
        if (nextKind != null) {
          newEntity = entity.copyWith(kind: nextKind);
        }
      }

      if (newEntity != null) {
        layer.setAt(pos, newEntity);
        affectedPositions.add(pos);
      }
    }

    if (affectedPositions.isEmpty) return const [];

    return [GameEvent.cellsFlooded(affectedPositions)];
  }
}
