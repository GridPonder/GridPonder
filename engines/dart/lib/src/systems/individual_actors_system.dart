import '../engine/game_system.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// Selects one actor with a tap action, then moves only that selected actor
/// with the configured move action. Optional claiming and per-actor successful
/// move budgets mirror the coupled actors territory flow.
class IndividualActorsSystem extends GameSystem {
  const IndividualActorsSystem({required super.id})
      : super(type: 'individual_actors');

  static const _defaultDirections = ['up', 'down', 'left', 'right'];

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, {});
    final selectAction = config['selectAction'] as String? ?? 'tap_cell';
    final moveAction = config['moveAction'] as String? ?? 'move';

    if (action.actionId == selectAction) {
      return _select(action, state, game, config);
    }
    if (action.actionId == moveAction) {
      return _move(action, state, game, config);
    }
    return const [];
  }

  List<GameEvent> _select(
    GameAction action,
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> config,
  ) {
    final rawPos = action.params['position'];
    if (rawPos == null) return [GameEvent.actionVetoed()];

    final pos = rawPos is Position ? rawPos : Position.fromJson(rawPos);
    final actorLayerId = config['actorLayer'] as String? ?? 'actors';
    final actorTag = config['actorTag'] as String? ?? 'actor';
    final entity = state.board.getEntity(actorLayerId, pos);
    if (entity == null || !game.hasTag(entity.kind, actorTag)) {
      return [GameEvent.actionVetoed()];
    }

    final selectedKey =
        config['selectedVariable'] as String? ?? 'selectedActorKind';
    state.variables[selectedKey] = entity.kind;
    _ensureBudgetState(state, config);
    return [GameEvent.actorSelected(entity.kind, pos)];
  }

  List<GameEvent> _move(
    GameAction action,
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> config,
  ) {
    final allowedRaw =
        config['directions'] as List<dynamic>? ?? _defaultDirections;
    final allowed = allowedRaw.map((d) => d.toString()).toList();
    final directionStr = action.directionStr;
    if (directionStr == null || !allowed.contains(directionStr)) {
      return const [];
    }

    final selectedKey =
        config['selectedVariable'] as String? ?? 'selectedActorKind';
    final selectedKind = state.variables[selectedKey] as String?;
    if (selectedKind == null) return [GameEvent.actionVetoed()];

    final remaining = _ensureBudgetState(state, config);
    if (remaining != null && (remaining[selectedKind] ?? 0) <= 0) {
      return [GameEvent.actionVetoed()];
    }

    final direction = action.direction;
    if (direction == null) return const [];
    final delta = direction.offset;
    if (delta.x == 0 && delta.y == 0) return const [];

    final actorLayerId = config['actorLayer'] as String? ?? 'actors';
    final groundLayerId = config['groundLayer'] as String? ?? 'ground';
    final wallTag = config['wallTag'] as String? ?? 'solid';
    final board = state.board;
    final actorLayer = board.layers[actorLayerId];
    if (actorLayer == null) return [GameEvent.actionVetoed()];

    Position? pos;
    EntityInstance? entity;
    final occupied = <Position>{};
    for (final entry in actorLayer.entries()) {
      occupied.add(entry.key);
      if (entry.value.kind == selectedKind) {
        pos = entry.key;
        entity = entry.value;
      }
    }

    if (pos == null || entity == null) return [GameEvent.actionVetoed()];

    final target = Position(pos.x + delta.x, pos.y + delta.y);
    final blocked = !board.isInBounds(target) ||
        board.hasTagAt(groundLayerId, target, wallTag, game.entityKinds) ||
        occupied.contains(target);

    if (blocked) {
      return [GameEvent.actorBlocked(entity.kind, pos)];
    }

    board.setEntity(actorLayerId, pos, null);
    board.setEntity(actorLayerId, target, entity);
    final events = <GameEvent>[
      GameEvent.actorMoved(entity.kind, pos, target, directionStr),
      GameEvent.actorEntered(entity.kind, target, pos, directionStr),
    ];

    final claim = config['claim'] as Map<String, dynamic>?;
    if (claim != null) {
      final claimLayerId = claim['layer'] as String;
      final claimMap = claim['map'] as Map<String, dynamic>? ?? const {};
      final claimKind = claimMap[entity.kind] as String?;
      if (claimKind != null && board.getEntity(claimLayerId, target) == null) {
        board.setEntity(claimLayerId, target, EntityInstance(claimKind));
        events.add(GameEvent.cellClaimed(
            target, claimLayerId, claimKind, entity.kind));
      }
    }

    if (remaining != null) {
      remaining[entity.kind] = (remaining[entity.kind] ?? 0) - 1;
    }

    return events;
  }

  Map<String, int>? _ensureBudgetState(
    LevelState state,
    Map<String, dynamic> config,
  ) {
    final budgets = config['budgets'] as Map<String, dynamic>?;
    if (budgets == null || budgets.isEmpty) return null;

    final key = config['budgetVariable'] as String? ?? 'actorMovesRemaining';
    final current = state.variables[key];
    if (current is Map) {
      final normalized =
          current.map((k, v) => MapEntry(k as String, (v as num).toInt()));
      state.variables[key] = normalized;
      return normalized;
    }

    final initialized = budgets.map((k, v) => MapEntry(k, (v as num).toInt()));
    state.variables[key] = initialized;
    return initialized;
  }
}
