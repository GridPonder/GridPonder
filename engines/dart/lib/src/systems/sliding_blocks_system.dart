import '../engine/game_system.dart';
import '../models/board.dart';
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
    final oldCellSet = oldCells.toSet();
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
      return events;
    }

    for (final cell in newCells) {
      if (!_isValidDestination(
        cell,
        block,
        oldCellSet,
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
    Set<Position> currentCells,
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
      if (other.id == movingBlock.id) continue;
      if (other.cells.contains(pos)) return false;
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
      if (currentCells.contains(pos)) continue;
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
    final escapeRoles = (config['escapeRoles'] as List? ?? const ['escapee'])
        .map((value) => value.toString())
        .toSet();
    if (!escapeRoles.contains(block.params['role']?.toString())) return false;

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
}
