import '../engine/game_system.dart';
import '../models/board.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

class SlidingBlocksSystem extends GameSystem {
  final Map<String, dynamic>? config;

  const SlidingBlocksSystem({required super.id, this.config})
      : super(type: 'sliding_blocks');

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final effectiveConfig = config ?? game.systemConfig(id, {});
    final moveAction = effectiveConfig['moveAction'] as String? ?? 'move';
    if (action.actionId != moveAction) return const [];

    final direction = action.direction;
    final start = _parsePosition(action.params['position']);
    if (direction == null || start == null) {
      return [GameEvent.actionVetoed()];
    }

    final block = _blockAt(state, start);
    if (block == null) return [GameEvent.actionVetoed()];

    final axis = (block.params['axis'] as String?) ?? 'both';
    if (!_axisAllows(axis, direction.toJson())) {
      return [GameEvent.actionVetoed()];
    }

    final offset = direction.offset;
    final oldCells = block.cells.toList();
    final newCells = oldCells.map((p) => p + offset).toList();
    final oldSet = oldCells.toSet();
    final events = <GameEvent>[];

    final outOfBounds =
        newCells.where((p) => !state.board.isInBounds(p)).toList();
    if (outOfBounds.isNotEmpty) {
      if (!_canEscape(
        block,
        oldCells,
        direction.toJson(),
        state,
        game,
        effectiveConfig,
      )) {
        return [GameEvent.actionVetoed()];
      }
      state.board.multiCellObjects.removeWhere((m) => m.id == block.id);
      final variable =
          effectiveConfig['escapedVariable'] as String? ?? 'escapedCount';
      final oldValue = (state.variables[variable] as num?) ?? 0;
      final newValue = oldValue + 1;
      state.variables[variable] = newValue;
      events.addAll([
        GameEvent('multi_cell_object_exited', {
          'id': block.id,
          'kind': block.kind,
          'direction': direction.toJson(),
        }),
        GameEvent.variableChanged(variable, oldValue, newValue),
      ]);
      events.addAll(_revealUncovered(state, effectiveConfig));
      events.addAll(_lineOfSightCollect(state, game, effectiveConfig));
      events.addAll(
        _resolveObjectInteractions(newCells, state, game, effectiveConfig),
      );
      return events;
    }

    events.addAll(
      _resolveObjectInteractions(newCells, state, game, effectiveConfig),
    );

    for (final cell in newCells) {
      if (!_isValidDestination(
        cell,
        block,
        oldSet,
        state,
        game,
        effectiveConfig,
      )) {
        return [GameEvent.actionVetoed()];
      }
    }

    _moveBlockCells(block, oldCells, newCells);
    events.add(
      GameEvent('multi_cell_object_moved', {
        'id': block.id,
        'kind': block.kind,
        'fromCells': oldCells,
        'toCells': newCells,
        'direction': direction.toJson(),
      }),
    );
    events.addAll(
      _collectOnEnter(block, newCells, state, game, effectiveConfig),
    );
    events.addAll(_revealUncovered(state, effectiveConfig));
    events.addAll(_lineOfSightCollect(state, game, effectiveConfig));
    events.addAll(
      _resolveObjectInteractions(newCells, state, game, effectiveConfig),
    );
    return events;
  }

  MultiCellObjectInstance? _blockAt(LevelState state, Position pos) {
    for (final block in state.board.multiCellObjects) {
      if (block.cells.contains(pos)) return block;
    }
    return null;
  }

  Position? _parsePosition(dynamic raw) {
    if (raw is List && raw.length >= 2) {
      final x = raw[0];
      final y = raw[1];
      if (x is int && y is int) return Position(x, y);
    }
    return null;
  }

  bool _axisAllows(String axis, String direction) {
    return switch (axis) {
      'horizontal' => direction == 'left' || direction == 'right',
      'vertical' => direction == 'up' || direction == 'down',
      'both' => true,
      _ => false,
    };
  }

  bool _isValidDestination(
    Position pos,
    MultiCellObjectInstance movingBlock,
    Set<Position> movingBlockCells,
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> config,
  ) {
    if (!state.board.isInBounds(pos)) return false;
    if (state.board.isVoid(pos)) return false;

    final ground = state.board.getEntity('ground', pos);
    final validGroundTags = (config['validGroundTags'] as List? ?? ['walkable'])
        .map((v) => v.toString())
        .toList();
    if (ground == null ||
        !validGroundTags.any((tag) => game.hasTag(ground.kind, tag))) {
      return false;
    }

    for (final other in state.board.multiCellObjects) {
      for (final cell in other.cells) {
        if (cell == pos && !movingBlockCells.contains(cell)) return false;
      }
    }

    final blockingLayers = (config['blockingLayers'] as List? ?? ['objects'])
        .map((v) => v.toString());
    final blockingTags = (config['blockingTags'] as List? ?? ['solid'])
        .map((v) => v.toString())
        .toList();
    final coverableTags = (config['coverableTags'] as List? ?? const [])
        .map((v) => v.toString())
        .toList();
    final coverableBlockedRoles =
        (config['coverableBlockedRoles'] as List? ?? const ['escapee'])
            .map((v) => v.toString())
            .toSet();
    final movingRole = movingBlock.params['role']?.toString();
    for (final layerId in blockingLayers) {
      final entity = state.board.getEntity(layerId, pos);
      if (entity == null) continue;
      if (movingBlockCells.contains(pos)) continue;
      if (blockingTags.isEmpty ||
          blockingTags.any((tag) => game.hasTag(entity.kind, tag))) {
        final canCover = coverableTags
                .any((tag) => game.hasTag(entity.kind, tag)) &&
            (movingRole == null || !coverableBlockedRoles.contains(movingRole));
        if (canCover) continue;
        return false;
      }
    }

    return true;
  }

  bool _canEscape(
    MultiCellObjectInstance block,
    List<Position> oldCells,
    String direction,
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> config,
  ) {
    if (block.params['role'] != 'escapee') return false;

    final exitTags = (config['exitTags'] as List? ?? ['exit'])
        .map((v) => v.toString())
        .toList();
    if (exitTags.isEmpty) return true;

    final edgeCells = switch (direction) {
      'right' => _cellsAtX(oldCells, _maxX(oldCells)),
      'left' => _cellsAtX(oldCells, _minX(oldCells)),
      'down' => _cellsAtY(oldCells, _maxY(oldCells)),
      'up' => _cellsAtY(oldCells, _minY(oldCells)),
      _ => const <Position>[],
    };

    for (final cell in edgeCells) {
      final ground = state.board.getEntity('ground', cell);
      if (ground != null &&
          exitTags.any((tag) => game.hasTag(ground.kind, tag))) {
        return true;
      }
    }
    return false;
  }

  void _moveBlockCells(
    MultiCellObjectInstance block,
    List<Position> oldCells,
    List<Position> newCells,
  ) {
    block.cells
      ..clear()
      ..addAll(newCells);

    if (block.cellSprites.isEmpty) return;
    final oldSprites = Map<Position, String>.from(block.cellSprites);
    block.cellSprites.clear();
    for (var i = 0; i < oldCells.length; i++) {
      final sprite = oldSprites[oldCells[i]];
      if (sprite != null) block.cellSprites[newCells[i]] = sprite;
    }
  }

  int _minX(List<Position> cells) =>
      cells.map((p) => p.x).reduce((a, b) => a < b ? a : b);

  int _maxX(List<Position> cells) =>
      cells.map((p) => p.x).reduce((a, b) => a > b ? a : b);

  int _minY(List<Position> cells) =>
      cells.map((p) => p.y).reduce((a, b) => a < b ? a : b);

  int _maxY(List<Position> cells) =>
      cells.map((p) => p.y).reduce((a, b) => a > b ? a : b);

  List<Position> _cellsAtX(List<Position> cells, int x) =>
      cells.where((p) => p.x == x).toList();

  List<Position> _cellsAtY(List<Position> cells, int y) =>
      cells.where((p) => p.y == y).toList();

  List<GameEvent> _revealUncovered(
    LevelState state,
    Map<String, dynamic> config,
  ) {
    final events = <GameEvent>[];
    for (final raw in config['revealOnUncovered'] as List? ?? const []) {
      if (raw is! Map) continue;
      final item = raw.cast<String, dynamic>();
      final pos = _parsePosition(item['position']);
      final kind = item['kind'] as String?;
      if (pos == null || kind == null) continue;

      final variable = item['revealedVariable'] as String?;
      if (variable != null && state.variables[variable] == true) continue;
      if (_blockAt(state, pos) != null) continue;

      final layerId = item['layer'] as String? ?? 'objects';
      if (state.board.getEntity(layerId, pos) != null) continue;

      state.board.setEntity(layerId, pos, EntityInstance(kind));
      events.add(GameEvent.objectPlaced(pos, kind));
      if (variable != null) {
        final oldValue = state.variables[variable] ?? false;
        state.variables[variable] = true;
        events.add(GameEvent.variableChanged(variable, oldValue, true));
      }
    }
    return events;
  }

  List<GameEvent> _collectOnEnter(
    MultiCellObjectInstance block,
    List<Position> newCells,
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> config,
  ) {
    final events = <GameEvent>[];
    for (final raw in config['collectOnEnter'] as List? ?? const []) {
      if (raw is! Map) continue;
      final item = raw.cast<String, dynamic>();
      final roles =
          (item['roles'] as List? ?? const []).map((v) => v.toString()).toSet();
      final role = block.params['role']?.toString();
      if (roles.isNotEmpty && !roles.contains(role)) continue;

      final layerId = item['layer'] as String? ?? 'objects';
      final kinds =
          (item['kinds'] as List? ?? const []).map((v) => v.toString()).toSet();
      final tags =
          (item['tags'] as List? ?? const []).map((v) => v.toString()).toSet();
      final variable = item['variable'] as String?;
      final remove = item['remove'] as bool? ?? true;
      for (final pos in newCells) {
        final entity = state.board.getEntity(layerId, pos);
        if (entity == null) continue;
        if (kinds.isNotEmpty && !kinds.contains(entity.kind)) continue;
        if (tags.isNotEmpty &&
            !tags.any((tag) => game.hasTag(entity.kind, tag))) {
          continue;
        }
        if (remove) {
          state.board.setEntity(layerId, pos, null);
          events.add(GameEvent.objectRemoved(pos, entity.kind));
        }
        if (variable != null) {
          final oldValue = (state.variables[variable] as num?) ?? 0;
          final newValue = oldValue + 1;
          state.variables[variable] = newValue;
          events.add(GameEvent.variableChanged(variable, oldValue, newValue));
        }
      }
    }
    return events;
  }

  List<GameEvent> _resolveObjectInteractions(
    List<Position> newCells,
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> config,
  ) {
    final events = <GameEvent>[];
    for (final raw in config['objectInteractions'] as List? ?? const []) {
      if (raw is! Map) continue;
      final item = raw.cast<String, dynamic>();
      final layerId = item['layer'] as String? ?? 'objects';
      final layer = state.board.layers[layerId];
      if (layer == null) continue;
      final targetKinds = (item['targetKinds'] as List? ?? const [])
          .map((v) => v.toString())
          .toSet();
      final targetTags = (item['targetTags'] as List? ?? const [])
          .map((v) => v.toString())
          .toSet();
      final requiredVariable = item['requiredVariable'] as String?;
      if (requiredVariable != null) {
        final current = (state.variables[requiredVariable] as num?) ?? 0;
        final minValue = (item['minValue'] as num?) ?? 1;
        if (current < minValue) continue;
      }
      final toKind = item['toKind'] as String?;
      final remove = item['remove'] as bool? ?? false;
      final scope = item['scope'] as String? ?? 'destination';
      final positions = scope == 'board'
          ? layer.entries().map((entry) => entry.key).toList()
          : newCells;
      for (final pos in positions) {
        final entity = state.board.getEntity(layerId, pos);
        if (entity == null) continue;
        if (targetKinds.isNotEmpty && !targetKinds.contains(entity.kind)) {
          continue;
        }
        if (targetTags.isNotEmpty &&
            !targetTags.any((tag) => game.hasTag(entity.kind, tag))) {
          continue;
        }
        if (remove) {
          state.board.setEntity(layerId, pos, null);
          events.add(GameEvent.objectRemoved(pos, entity.kind));
        } else if (toKind != null) {
          if (entity.kind == toKind) continue;
          state.board.setEntity(layerId, pos, EntityInstance(toKind));
          events.add(
            GameEvent.cellTransformed(pos, entity.kind, toKind, layerId),
          );
        }
      }
    }
    return events;
  }

  List<GameEvent> _lineOfSightCollect(
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> config,
  ) {
    final events = <GameEvent>[];
    for (final raw in config['lineOfSightCollect'] as List? ?? const []) {
      if (raw is! Map) continue;
      final item = raw.cast<String, dynamic>();
      final roles =
          (item['roles'] as List? ?? const []).map((v) => v.toString()).toSet();
      final collectors = state.board.multiCellObjects.where((collector) {
        final role = collector.params['role']?.toString();
        return roles.isEmpty || roles.contains(role);
      }).toList();
      if (collectors.isEmpty) continue;

      final layerId = item['layer'] as String? ?? 'objects';
      final layer = state.board.layers[layerId];
      if (layer == null) continue;
      final kinds =
          (item['kinds'] as List? ?? const []).map((v) => v.toString()).toSet();
      final tags =
          (item['tags'] as List? ?? const []).map((v) => v.toString()).toSet();
      final variable = item['variable'] as String?;
      final remove = item['remove'] as bool? ?? true;
      final blockingLayers = (item['blockingLayers'] as List? ??
              config['blockingLayers'] as List? ??
              const ['objects'])
          .map((v) => v.toString())
          .toList();
      final blockingTags = (item['blockingTags'] as List? ??
              config['blockingTags'] as List? ??
              const ['solid'])
          .map((v) => v.toString())
          .toList();

      for (final entry in layer.entries().toList()) {
        final keyPos = entry.key;
        final entity = entry.value;
        if (kinds.isNotEmpty && !kinds.contains(entity.kind)) continue;
        if (tags.isNotEmpty &&
            !tags.any((tag) => game.hasTag(entity.kind, tag))) {
          continue;
        }
        final coveringBlock = _blockAt(state, keyPos);
        Position? source;
        String? collectorId;
        for (final collector in collectors) {
          if (coveringBlock != null && coveringBlock.id != collector.id) {
            continue;
          }
          for (final cell in collector.cells) {
            if (_hasClearLine(
              cell,
              keyPos,
              collector,
              state,
              game,
              blockingLayers,
              blockingTags,
            )) {
              source = cell;
              collectorId = collector.id;
              break;
            }
          }
          if (source != null) break;
        }
        if (source == null || collectorId == null) continue;

        if (remove) {
          state.board.setEntity(layerId, keyPos, null);
          events.add(GameEvent.objectRemoved(keyPos, entity.kind));
        }
        events.add(
          GameEvent.lineOfSightCollected(
            source,
            keyPos,
            entity.kind,
            collectorId,
          ),
        );
        if (variable != null) {
          final oldValue = (state.variables[variable] as num?) ?? 0;
          final newValue = oldValue + 1;
          state.variables[variable] = newValue;
          events.add(GameEvent.variableChanged(variable, oldValue, newValue));
        }
        break;
      }
    }
    return events;
  }

  bool _hasClearLine(
    Position source,
    Position target,
    MultiCellObjectInstance sourceBlock,
    LevelState state,
    GameDefinition game,
    List<String> blockingLayers,
    List<String> blockingTags,
  ) {
    if (source.x != target.x && source.y != target.y) return false;
    final dx = source.x == target.x ? 0 : (target.x > source.x ? 1 : -1);
    final dy = source.y == target.y ? 0 : (target.y > source.y ? 1 : -1);
    var pos = Position(source.x + dx, source.y + dy);
    while (pos != target) {
      if (state.board.isVoid(pos)) return false;
      final blocker = _blockAt(state, pos);
      if (blocker != null && blocker.id != sourceBlock.id) return false;
      for (final layerId in blockingLayers) {
        final entity = state.board.getEntity(layerId, pos);
        if (entity == null) continue;
        if (blockingTags.isEmpty ||
            blockingTags.any((tag) => game.hasTag(entity.kind, tag))) {
          return false;
        }
      }
      pos = Position(pos.x + dx, pos.y + dy);
    }
    return true;
  }
}
