import '../engine/game_system.dart';
import '../models/board.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

class ElasticBlockSystem extends GameSystem {
  static const _cardinalDirections = {'up', 'down', 'left', 'right'};

  final Map<String, dynamic>? config;

  const ElasticBlockSystem({required super.id, this.config})
      : super(type: 'elastic_block');

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final effectiveConfig = config ?? game.systemConfig(id, {});
    final moveAction = effectiveConfig['moveAction'] as String? ?? 'move';
    if (action.actionId != moveAction) return const [];

    final direction = action.params['direction'];
    final directions = (effectiveConfig['directions'] as List? ??
            const ['up', 'down', 'left', 'right'])
        .map((value) => value.toString())
        .toSet();
    if (direction is! String ||
        !_cardinalDirections.contains(direction) ||
        !directions.contains(direction)) {
      return [GameEvent.actionVetoed()];
    }

    final objectKind =
        effectiveConfig['objectKind'] as String? ?? 'elastic_block';
    final blocks = state.board.multiCellObjects
        .where((item) => item.kind == objectKind)
        .toList();
    if (blocks.length != 1 || !_isRectangle(blocks.single.cells)) {
      return [GameEvent.actionVetoed()];
    }

    final block = blocks.single;
    final oldCells = block.cells.toList();
    final pushOrigins = <Position, Position>{};
    var nextLine = _leadingLine(oldCells, direction, 1);
    var pushes = _linePushes(
      nextLine,
      direction,
      block,
      state,
      game,
      effectiveConfig,
    );
    final events = <GameEvent>[];

    if (pushes == null) {
      final collapseWhenBlocked =
          effectiveConfig['collapseWhenBlocked'] as bool? ?? true;
      if (!collapseWhenBlocked) return _noOp(effectiveConfig);
      final rawThickness =
          (effectiveConfig['collapseThickness'] as num?)?.toInt() ?? 1;
      final thickness = rawThickness < 1 ? 1 : rawThickness;
      final newCells = _collapsedCells(oldCells, direction, thickness);
      if (newCells.toSet().containsAll(oldCells) &&
          oldCells.toSet().containsAll(newCells)) {
        return _noOp(effectiveConfig);
      }
      block.cells
        ..clear()
        ..addAll(newCells);
      block.cellSprites
          .removeWhere((position, _) => !newCells.contains(position));
      events.add(GameEvent('elastic_block_collapsed', {
        'id': block.id,
        'kind': block.kind,
        'fromCells': oldCells,
        'toCells': newCells,
        'direction': direction,
      }));
    } else {
      final inflateMode =
          effectiveConfig['inflateMode'] as String? ?? 'to_obstacle';
      if (inflateMode != 'to_obstacle' && inflateMode != 'single_step') {
        return [GameEvent.actionVetoed()];
      }

      final addedCells = <Position>[];
      var distance = 0;
      while (pushes != null) {
        _applyPushes(pushes, state, direction, events, pushOrigins);
        addedCells.addAll(nextLine);
        block.cells.addAll(nextLine);
        distance += 1;
        if (inflateMode == 'single_step') break;
        nextLine = _leadingLine(block.cells, direction, 1);
        pushes = _linePushes(
          nextLine,
          direction,
          block,
          state,
          game,
          effectiveConfig,
        );
      }
      events.add(GameEvent('elastic_block_inflated', {
        'id': block.id,
        'kind': block.kind,
        'fromCells': oldCells,
        'toCells': block.cells.toList(),
        'addedCells': addedCells,
        'direction': direction,
        'distance': distance,
      }));
    }

    events.addAll(_updateTargets(block, state, effectiveConfig));
    return events;
  }

  List<GameEvent> _noOp(Map<String, dynamic> config) {
    final reject = config['rejectNoOpMoves'] as bool? ?? true;
    return reject ? [GameEvent.actionVetoed()] : const [];
  }

  bool _isRectangle(List<Position> cells) {
    if (cells.isEmpty || cells.toSet().length != cells.length) return false;
    final minX = _minX(cells);
    final maxX = _maxX(cells);
    final minY = _minY(cells);
    final maxY = _maxY(cells);
    if (cells.length != (maxX - minX + 1) * (maxY - minY + 1)) return false;
    final actual = cells.toSet();
    for (var y = minY; y <= maxY; y++) {
      for (var x = minX; x <= maxX; x++) {
        if (!actual.contains(Position(x, y))) return false;
      }
    }
    return true;
  }

  List<Position> _leadingLine(
      List<Position> cells, String direction, int offset) {
    final minX = _minX(cells);
    final maxX = _maxX(cells);
    final minY = _minY(cells);
    final maxY = _maxY(cells);
    return switch (direction) {
      'left' => [for (var y = minY; y <= maxY; y++) Position(minX - offset, y)],
      'right' => [
          for (var y = minY; y <= maxY; y++) Position(maxX + offset, y)
        ],
      'up' => [for (var x = minX; x <= maxX; x++) Position(x, minY - offset)],
      _ => [for (var x = minX; x <= maxX; x++) Position(x, maxY + offset)],
    };
  }

  List<Position> _collapsedCells(
      List<Position> cells, String direction, int thickness) {
    var minX = _minX(cells);
    var maxX = _maxX(cells);
    var minY = _minY(cells);
    var maxY = _maxY(cells);
    switch (direction) {
      case 'left':
        maxX = _min(maxX, minX + thickness - 1);
      case 'right':
        minX = _max(minX, maxX - thickness + 1);
      case 'up':
        maxY = _min(maxY, minY + thickness - 1);
      case 'down':
        minY = _max(minY, maxY - thickness + 1);
    }
    return [
      for (var y = minY; y <= maxY; y++)
        for (var x = minX; x <= maxX; x++) Position(x, y),
    ];
  }

  List<_Push>? _linePushes(
    List<Position> line,
    String direction,
    MultiCellObjectInstance block,
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> config,
  ) {
    final pushes = <_Push>[];
    for (final position in line) {
      if (!_validGround(position, state, game, config)) return null;
      if (state.board.multiCellObjects.any(
          (other) => other.id != block.id && other.cells.contains(position))) {
        return null;
      }
      final blockers = _blockingEntities(position, state, game, config);
      if (blockers.isEmpty) continue;
      if (blockers.length != 1) return null;
      final blocker = blockers.single;
      final pushableTags =
          (config['pushableTags'] as List? ?? const ['pushable'])
              .map((value) => value.toString());
      if (!pushableTags.any((tag) => game.hasTag(blocker.entity.kind, tag))) {
        return null;
      }
      final chain = _pushChain(
        blocker,
        position,
        direction,
        block,
        state,
        game,
        config,
      );
      if (chain == null) return null;
      pushes.addAll(chain);
    }
    final uniquePushes = <String, _Push>{
      for (final push in pushes)
        '${push.layer}:${push.source.x},${push.source.y}': push,
    }.values.toList();
    if (uniquePushes.map((push) => push.destination).toSet().length !=
        uniquePushes.length) {
      return null;
    }
    return uniquePushes;
  }

  List<_Push>? _pushChain(
    _BlockingEntity blocker,
    Position source,
    String direction,
    MultiCellObjectInstance block,
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> config,
  ) {
    final destination = source + actionOffset(direction);
    if (!_validGround(destination, state, game, config)) return null;
    if (state.board.multiCellObjects.any(
        (other) => other.id != block.id && other.cells.contains(destination))) {
      return null;
    }

    final destinationEntity = state.board.getEntity(blocker.layer, destination);
    final tail = <_Push>[];
    if (destinationEntity != null) {
      if (config['chainPush'] != true) return null;
      final pushableTags =
          (config['pushableTags'] as List? ?? const ['pushable'])
              .map((value) => value.toString());
      if (!pushableTags
          .any((tag) => game.hasTag(destinationEntity.kind, tag))) {
        return null;
      }
      final destinationBlockers =
          _blockingEntities(destination, state, game, config);
      if (destinationBlockers.length != 1 ||
          destinationBlockers.single.layer != blocker.layer) {
        return null;
      }
      final chained = _pushChain(
        destinationBlockers.single,
        destination,
        direction,
        block,
        state,
        game,
        config,
      );
      if (chained == null) return null;
      tail.addAll(chained);
    } else if (_blockingEntities(destination, state, game, config).isNotEmpty) {
      return null;
    }

    return [
      ...tail,
      _Push(blocker.layer, source, destination, blocker.entity),
    ];
  }

  bool _validGround(Position position, LevelState state, GameDefinition game,
      Map<String, dynamic> config) {
    if (!state.board.isInBounds(position) || state.board.isVoid(position)) {
      return false;
    }
    final groundLayer = config['groundLayer'] as String? ?? 'ground';
    final ground = state.board.getEntity(groundLayer, position);
    final validTags = (config['validGroundTags'] as List? ?? const ['walkable'])
        .map((value) => value.toString());
    return ground != null &&
        validTags.any((tag) => game.hasTag(ground.kind, tag));
  }

  List<_BlockingEntity> _blockingEntities(Position position, LevelState state,
      GameDefinition game, Map<String, dynamic> config) {
    final layers = (config['blockingLayers'] as List? ?? const ['objects'])
        .map((value) => value.toString());
    final tags = (config['blockingTags'] as List? ?? const ['solid'])
        .map((value) => value.toString());
    final found = <_BlockingEntity>[];
    for (final layer in layers) {
      final entity = state.board.getEntity(layer, position);
      if (entity != null &&
          (tags.isEmpty || tags.any((tag) => game.hasTag(entity.kind, tag)))) {
        found.add(_BlockingEntity(layer, entity));
      }
    }
    return found;
  }

  void _applyPushes(
    List<_Push> pushes,
    LevelState state,
    String direction,
    List<GameEvent> events,
    Map<Position, Position> pushOrigins,
  ) {
    for (final push in pushes) {
      state.board.setEntity(push.layer, push.source, null);
    }
    for (final push in pushes) {
      state.board.setEntity(push.layer, push.destination, push.entity);
      final origin = pushOrigins.remove(push.source) ?? push.source;
      pushOrigins[push.destination] = origin;
      events.add(GameEvent('object_pushed', {
        'kind': push.entity.kind,
        'fromPosition': push.source,
        'toPosition': push.destination,
        'originPosition': origin,
        'layer': push.layer,
        'direction': direction,
      }));
    }
  }

  List<GameEvent> _updateTargets(MultiCellObjectInstance block,
      LevelState state, Map<String, dynamic> config) {
    final targets = config['targets'] as List? ?? const [];
    if (targets.isEmpty) return const [];

    final completedKey =
        config['completedTargetIdsVariable'] as String? ?? 'completedTargetIds';
    final consumedKey =
        config['consumedTargetIdsVariable'] as String? ?? 'consumedTargetIds';
    final countKey =
        config['completedTargetsVariable'] as String? ?? 'completedTargetCount';
    final completed = _stringSet(state.variables[completedKey]);
    final consumed = _stringSet(state.variables[consumedKey]);
    final targetLayer = config['targetLayer'] as String? ?? 'markers';
    final blockCells = block.cells.toSet();
    final events = <GameEvent>[];

    for (final rawTarget in targets) {
      if (rawTarget is! Map) continue;
      final target = Map<String, dynamic>.from(rawTarget);
      final markerKind = target['markerKind']?.toString() ?? '';
      final targetId = target['id']?.toString() ?? markerKind;
      if (targetId.isEmpty || markerKind.isEmpty) continue;
      final markerLayer = target['markerLayer'] as String? ?? targetLayer;
      final cells = _targetCells(state, markerLayer, markerKind);
      if (cells.isEmpty) continue;

      if (completed.contains(targetId) &&
          !consumed.contains(targetId) &&
          blockCells.intersection(cells).isEmpty) {
        final mode = target['onLeave']?.toString() ?? 'none';
        _consumeTarget(
            cells, markerKind, markerLayer, mode, target, state, events);
        consumed.add(targetId);
        events.add(GameEvent('target_consumed', {
          'targetId': targetId,
          'mode': mode,
        }));
      }

      if (!completed.contains(targetId) && _setsEqual(blockCells, cells)) {
        completed.add(targetId);
        events.add(GameEvent('target_completed', {'targetId': targetId}));
      }
    }

    final oldCompleted = state.variables[completedKey] ?? const <dynamic>[];
    final oldConsumed = state.variables[consumedKey] ?? const <dynamic>[];
    final oldCount = state.variables[countKey] ?? 0;
    final newCompleted = completed.toList()..sort();
    final newConsumed = consumed.toList()..sort();
    if (!_listsEqual(oldCompleted, newCompleted)) {
      state.variables[completedKey] = newCompleted;
      events.add(
          GameEvent.variableChanged(completedKey, oldCompleted, newCompleted));
    }
    if (!_listsEqual(oldConsumed, newConsumed)) {
      state.variables[consumedKey] = newConsumed;
      events.add(
          GameEvent.variableChanged(consumedKey, oldConsumed, newConsumed));
    }
    if (oldCount != completed.length) {
      state.variables[countKey] = completed.length;
      events
          .add(GameEvent.variableChanged(countKey, oldCount, completed.length));
    }
    return events;
  }

  Set<Position> _targetCells(
      LevelState state, String layerId, String markerKind) {
    final layer = state.board.layers[layerId];
    if (layer == null) return {};
    return {
      for (final entry in layer.entries())
        if (entry.value.kind == markerKind) entry.key,
    };
  }

  void _consumeTarget(
    Set<Position> cells,
    String markerKind,
    String markerLayer,
    String mode,
    Map<String, dynamic> target,
    LevelState state,
    List<GameEvent> events,
  ) {
    late final String layer;
    late final String kind;
    if (mode == 'void') {
      layer = target['groundLayer'] as String? ?? 'ground';
      kind = target['voidKind'] as String? ?? 'void';
    } else if (mode == 'wall') {
      layer = target['wallLayer'] as String? ?? 'objects';
      kind = target['wallKind'] as String? ?? 'wall';
    } else {
      layer = '';
      kind = '';
    }

    final orderedCells = cells.toList()
      ..sort((left, right) {
        final byY = left.y.compareTo(right.y);
        return byY != 0 ? byY : left.x.compareTo(right.x);
      });
    for (final position in orderedCells) {
      state.board.setEntity(markerLayer, position, null);
      events
          .add(GameEvent.cellCleared(position, markerKind, layer: markerLayer));
      if (layer.isNotEmpty) {
        final previous = state.board.getEntity(layer, position);
        state.board.setEntity(layer, position, EntityInstance(kind));
        events.add(GameEvent.cellTransformed(
            position, previous?.kind ?? 'empty', kind, layer));
      }
    }
  }

  Set<String> _stringSet(dynamic value) {
    if (value is! List) return {};
    return value.map((item) => item.toString()).toSet();
  }

  bool _setsEqual(Set<Position> left, Set<Position> right) =>
      left.length == right.length && left.containsAll(right);

  bool _listsEqual(dynamic oldValue, List<String> newValue) {
    if (oldValue is! List || oldValue.length != newValue.length) return false;
    for (var index = 0; index < newValue.length; index++) {
      if (oldValue[index].toString() != newValue[index]) return false;
    }
    return true;
  }

  Position actionOffset(String direction) => switch (direction) {
        'left' => const Position(-1, 0),
        'right' => const Position(1, 0),
        'up' => const Position(0, -1),
        _ => const Position(0, 1),
      };

  int _minX(List<Position> cells) =>
      cells.map((p) => p.x).reduce((a, b) => a < b ? a : b);
  int _maxX(List<Position> cells) =>
      cells.map((p) => p.x).reduce((a, b) => a > b ? a : b);
  int _minY(List<Position> cells) =>
      cells.map((p) => p.y).reduce((a, b) => a < b ? a : b);
  int _maxY(List<Position> cells) =>
      cells.map((p) => p.y).reduce((a, b) => a > b ? a : b);
  int _min(int left, int right) => left < right ? left : right;
  int _max(int left, int right) => left > right ? left : right;
}

class _BlockingEntity {
  final String layer;
  final EntityInstance entity;

  const _BlockingEntity(this.layer, this.entity);
}

class _Push {
  final String layer;
  final Position source;
  final Position destination;
  final EntityInstance entity;

  const _Push(this.layer, this.source, this.destination, this.entity);
}
