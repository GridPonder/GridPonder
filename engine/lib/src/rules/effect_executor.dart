import '../models/avatar.dart';
import '../models/effect.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';
import '../models/value_ref.dart';

/// Context implementing PositionResolver and AvatarResolver for value_ref.
class _RefContext implements PositionResolver, AvatarResolver {
  final LevelState state;
  final GameDefinition game;

  _RefContext(this.state, this.game);

  @override
  String? entityKindAt(String layerId, Position pos) =>
      state.board.getEntity(layerId, pos)?.kind;

  @override
  dynamic entityParamAt(String layerId, Position pos, String key) =>
      state.board.getEntity(layerId, pos)?.param(key);

  @override
  Position? get position => state.avatar.position;

  @override
  String? get item => state.avatar.inventory.slot;
}

/// Executes effects and returns newly emitted events.
class EffectExecutor {
  final GameDefinition game;

  EffectExecutor(this.game);

  List<GameEvent> execute(
    Effect effect,
    GameEvent triggerEvent,
    LevelState state,
  ) {
    final refCtx = _RefContext(state, game);

    dynamic resolve(dynamic v) => resolveRef(v,
        eventPayload: triggerEvent.payload,
        board: refCtx,
        avatar: refCtx);

    switch (effect.type) {
      case 'spawn':
        return _spawn(effect.data, resolve, state);
      case 'destroy':
        return _destroy(effect.data, resolve, state);
      case 'transform':
        return _transform(effect.data, resolve, state);
      case 'move_entity':
        return _moveEntity(effect.data, resolve, state);
      case 'set_cell':
        return _setCell(effect.data, resolve, state);
      case 'release_from_emitter':
        return _releaseFromEmitter(effect.data, state);
      case 'apply_gravity':
        return _applyGravity(effect.data, state);
      case 'set_variable':
        return _setVariable(effect.data, resolve, state);
      case 'increment_variable':
        return _incrementVariable(effect.data, state);
      case 'set_inventory':
        return _setInventory(effect.data, resolve, state);
      case 'clear_inventory':
        return _clearInventory(state);
      case 'resolve_move':
        return _resolveMove(state);
      default:
        return const [];
    }
  }

  List<GameEvent> _spawn(
      Map<String, dynamic> data, dynamic Function(dynamic) r, LevelState state) {
    final posRaw = r(data['position']);
    if (posRaw == null) return const [];
    final pos = posRaw is Position ? posRaw : Position.fromJson(posRaw);
    final layerId = data['layer'] as String;
    final kind = r(data['kind']) as String?;
    if (kind == null) return const [];
    final params = <String, dynamic>{};
    for (final k in data.keys) {
      if (k != 'position' && k != 'layer' && k != 'kind') {
        params[k] = r(data[k]);
      }
    }
    final entity = EntityInstance(kind, params);
    state.board.setEntity(layerId, pos, entity);
    return [GameEvent.objectPlaced(pos, kind, params)];
  }

  List<GameEvent> _destroy(
      Map<String, dynamic> data, dynamic Function(dynamic) r, LevelState state) {
    final posRaw = r(data['position']);
    if (posRaw == null) return const [];
    final pos = posRaw is Position ? posRaw : Position.fromJson(posRaw);
    final layerId = data['layer'] as String;
    final existing = state.board.getEntity(layerId, pos);
    if (existing == null) return const [];
    final kind = existing.kind;
    state.board.setEntity(layerId, pos, null);
    final animName = data['animation'] as String?;
    return [
      animName != null
          ? GameEvent.objectRemovedAnimated(pos, kind, animName)
          : GameEvent.objectRemoved(pos, kind),
      GameEvent.cellCleared(pos, kind),
    ];
  }

  List<GameEvent> _transform(
      Map<String, dynamic> data, dynamic Function(dynamic) r, LevelState state) {
    final posRaw = r(data['position']);
    if (posRaw == null) return const [];
    final pos = posRaw is Position ? posRaw : Position.fromJson(posRaw);
    final layerId = data['layer'] as String;
    final toKind = r(data['toKind']) as String?;
    if (toKind == null) return const [];
    final existing = state.board.getEntity(layerId, pos);
    final fromKind = existing?.kind ?? '';
    final animName = data['animation'] as String?;
    state.board.setEntity(layerId, pos, EntityInstance(toKind));
    return [
      GameEvent.cellTransformed(pos, fromKind, toKind, layerId),
      if (animName != null)
        GameEvent.objectRemovedAnimated(pos, fromKind, animName),
    ];
  }

  List<GameEvent> _moveEntity(
      Map<String, dynamic> data, dynamic Function(dynamic) r, LevelState state) {
    final fromRaw = r(data['from']);
    final toRaw = r(data['to']);
    if (fromRaw == null || toRaw == null) return const [];
    final from = fromRaw is Position ? fromRaw : Position.fromJson(fromRaw);
    final to = toRaw is Position ? toRaw : Position.fromJson(toRaw);
    final layerId = data['layer'] as String;
    final entity = state.board.getEntity(layerId, from);
    if (entity == null) return const [];
    state.board.setEntity(layerId, from, null);
    state.board.setEntity(layerId, to, entity);
    return [
      GameEvent.objectRemoved(from, entity.kind),
      GameEvent.objectPlaced(to, entity.kind, entity.params),
    ];
  }

  List<GameEvent> _setCell(
      Map<String, dynamic> data, dynamic Function(dynamic) r, LevelState state) {
    final posRaw = r(data['position']);
    if (posRaw == null) return const [];
    final pos = posRaw is Position ? posRaw : Position.fromJson(posRaw);
    final layerId = data['layer'] as String;
    final kind = r(data['kind']) as String?;
    if (kind == null) return const [];
    final params = <String, dynamic>{};
    for (final k in data.keys) {
      if (k != 'position' && k != 'layer' && k != 'kind') {
        params[k] = r(data[k]);
      }
    }
    state.board.setEntity(layerId, pos, EntityInstance(kind, params));
    return [GameEvent.objectPlaced(pos, kind, params)];
  }

  List<GameEvent> _releaseFromEmitter(
      Map<String, dynamic> data, LevelState state) {
    final emitterId = data['emitterId'] as String;
    final mco = state.board.getMultiCellObject(emitterId);
    if (mco == null) return const [];
    final queue = mco.params['queue'] as List?;
    if (queue == null || queue.isEmpty) return const [];
    final idx = (mco.params['currentIndex'] as int?) ?? 0;
    if (idx >= queue.length) return const [];

    final value = queue[idx];
    mco.params['currentIndex'] = idx + 1;

    final exitRaw = mco.params['exitPosition'];
    if (exitRaw == null) return const [];
    final exitPos = exitRaw is Position ? exitRaw : Position.fromJson(exitRaw);
    state.board.setEntity('objects', exitPos, EntityInstance('number', {'value': value}));

    return [GameEvent.itemReleased(emitterId, 'number', exitPos, {'value': value})];
  }

  List<GameEvent> _applyGravity(
      Map<String, dynamic> data, LevelState state) {
    final selectorMap = data['selector'] as Map<String, dynamic>? ?? {};
    final tag = selectorMap['tag'] as String?;
    final direction = (data['direction'] as String?) ?? 'down';

    final dx = direction == 'left' ? -1 : direction == 'right' ? 1 : 0;
    final dy = direction == 'up' ? -1 : direction == 'down' ? 1 : 0;

    final events = <GameEvent>[];
    final board = state.board;

    // Process multiple passes until nothing moves
    bool moved = true;
    while (moved) {
      moved = false;
      final objectsLayer = board.layers['objects'];
      if (objectsLayer == null) break;

      // Collect entities to move (iterate in gravity direction order)
      final toMove = <MapEntry<Position, EntityInstance>>[];
      for (final entry in objectsLayer.entries()) {
        final entity = entry.value;
        if (tag != null && !game.hasTag(entity.kind, tag)) continue;
        toMove.add(entry);
      }

      // Sort so we process bottom-up for downward gravity
      if (direction == 'down') toMove.sort((a, b) => b.key.y.compareTo(a.key.y));
      if (direction == 'up') toMove.sort((a, b) => a.key.y.compareTo(b.key.y));
      if (direction == 'right') toMove.sort((a, b) => b.key.x.compareTo(a.key.x));
      if (direction == 'left') toMove.sort((a, b) => a.key.x.compareTo(b.key.x));

      for (final entry in toMove) {
        final pos = entry.key;
        final entity = entry.value;
        final nextPos = Position(pos.x + dx, pos.y + dy);
        if (!board.isInBounds(nextPos)) continue;
        if (board.isVoid(nextPos)) continue;
        if (board.getEntity('objects', nextPos) != null) continue;

        board.setEntity('objects', pos, null);
        board.setEntity('objects', nextPos, entity);
        events.add(GameEvent.objectSettled(entity.kind, nextPos, pos));
        moved = true;
      }
    }

    return events;
  }

  List<GameEvent> _setVariable(
      Map<String, dynamic> data, dynamic Function(dynamic) r, LevelState state) {
    final name = data['name'] as String;
    final value = r(data['value']);
    final old = state.variables[name];
    state.variables[name] = value;
    return [GameEvent.variableChanged(name, old, value)];
  }

  List<GameEvent> _incrementVariable(
      Map<String, dynamic> data, LevelState state) {
    final name = data['name'] as String;
    final amount = (data['amount'] as num?) ?? 1;
    final old = state.variables[name] as num? ?? 0;
    final newVal = old + amount;
    state.variables[name] = newVal;
    return [GameEvent.variableChanged(name, old, newVal)];
  }

  List<GameEvent> _setInventory(
      Map<String, dynamic> data, dynamic Function(dynamic) r, LevelState state) {
    final item = r(data['item']) as String?;
    final old = state.avatar.inventory.slot;
    state.avatar = state.avatar.copyWith(
        inventory: state.avatar.inventory.copyWith(slot: item));
    return [GameEvent.inventoryChanged(old, item)];
  }

  List<GameEvent> _clearInventory(LevelState state) {
    final old = state.avatar.inventory.slot;
    if (old == null) return const [];
    state.avatar = state.avatar.copyWith(
        inventory: const InventoryState());
    return [GameEvent.inventoryChanged(old, null)];
  }

  List<GameEvent> _resolveMove(LevelState state) {
    final pending = state.pendingMove;
    if (pending == null) return const [];
    state.pendingMove = null;
    final from = pending.from;
    final to = pending.to;
    state.avatar = state.avatar.copyWith(position: to, facing: pending.direction);
    return [
      GameEvent.avatarExited(from),
      GameEvent.avatarEntered(to, from, pending.direction.toJson()),
    ];
  }
}
