import '../engine/game_system.dart';
import '../models/direction_transform.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';
import 'claim_policy.dart';

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
    final selectedPositionKey = config['selectedPositionVariable'] as String? ??
        'selectedActorPosition';
    state.variables[selectedKey] = entity.kind;
    state.variables[selectedPositionKey] = [pos.x, pos.y];
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
    final selectedPositionKey = config['selectedPositionVariable'] as String? ??
        'selectedActorPosition';
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

    final selectedPosition =
        _parsePosition(state.variables[selectedPositionKey]);
    Position? pos;
    EntityInstance? entity;
    final occupied = <Position>{};
    for (final entry in actorLayer.entries()) {
      occupied.add(entry.key);
      if (selectedPosition != null &&
          entry.key == selectedPosition &&
          entry.value.kind == selectedKind) {
        pos = entry.key;
        entity = entry.value;
      }
    }

    // Backward compatibility for states created before position-based
    // selection: a kind is sufficient only when it identifies one actor.
    if (selectedPosition == null) {
      final matches = actorLayer
          .entries()
          .where((entry) => entry.value.kind == selectedKind)
          .toList();
      if (matches.length == 1) {
        pos = matches.single.key;
        entity = matches.single.value;
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
    state.variables[selectedPositionKey] = [target.x, target.y];
    final events = <GameEvent>[
      GameEvent.actorMoved(entity.kind, pos, target, directionStr),
      GameEvent.actorEntered(entity.kind, target, pos, directionStr),
    ];

    final claimEvent = applyClaim(
      board,
      game,
      config['claim'] as Map<String, dynamic>?,
      groundLayerId,
      target,
      entity.kind,
    );
    if (claimEvent != null) events.add(claimEvent);

    if (remaining != null) {
      remaining[entity.kind] = (remaining[entity.kind] ?? 0) - 1;
    }

    events.addAll(_react(
        state, game, config, delta, actorLayerId, groundLayerId, wallTag));

    return events;
  }

  /// Moves every reactive-kind actor in response to a successful player move.
  ///
  /// Rivals answer the *player's* direction through their own transform, so the
  /// move the player makes is also the move the opposition makes. Runs only
  /// after a real step — a blocked attempt gives the rivals nothing. Resolution
  /// mirrors `coupled_actors`: bucket by effective direction in canonical
  /// order, front-first within a bucket, with a live `occupied` set, so the
  /// outcome is fully deterministic.
  ///
  /// Emits `actor_reacted` rather than `actor_moved` so move counters and
  /// budgets keyed on player movement stay honest; a level that wants rival
  /// landings to anchor captures names `actor_reacted` in the capture system's
  /// `triggerEvents`.
  List<GameEvent> _react(
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> config,
    Position delta,
    String actorLayerId,
    String groundLayerId,
    String wallTag,
  ) {
    final reactive = config['reactiveKinds'] as Map<String, dynamic>?;
    if (reactive == null || reactive.isEmpty) return const [];

    final board = state.board;
    final actorLayer = board.layers[actorLayerId];
    if (actorLayer == null) return const [];

    final occupied = <Position>{};
    final triples = <List<Object>>[];
    for (final entry in actorLayer.entries()) {
      occupied.add(entry.key);
      final transform = reactive[entry.value.kind];
      if (transform == null) continue;
      triples.add([
        entry.key,
        entry.value,
        transformDelta(delta, transform.toString()),
      ]);
    }
    if (triples.isEmpty) return const [];

    final ordered = <List<Object>>[];
    for (final bucket in _canonicalBuckets) {
      final members = triples.where((t) {
        final d = t[2] as Position;
        return d.x == bucket.x && d.y == bucket.y;
      }).toList()
        ..sort((a, b) {
          final pa = a[0] as Position;
          final pb = b[0] as Position;
          final projA = -(pa.x * bucket.x + pa.y * bucket.y);
          final projB = -(pb.x * bucket.x + pb.y * bucket.y);
          if (projA != projB) return projA.compareTo(projB);
          final sideA = pa.x * bucket.y.abs() + pa.y * bucket.x.abs();
          final sideB = pb.x * bucket.y.abs() + pb.y * bucket.x.abs();
          if (sideA != sideB) return sideA.compareTo(sideB);
          return (a[1] as EntityInstance).kind.compareTo(
                (b[1] as EntityInstance).kind,
              );
        });
      ordered.addAll(members);
    }

    final events = <GameEvent>[];
    for (final triple in ordered) {
      final pos = triple[0] as Position;
      final entity = triple[1] as EntityInstance;
      final rdelta = triple[2] as Position;
      if (rdelta.x == 0 && rdelta.y == 0) continue;
      final target = Position(pos.x + rdelta.x, pos.y + rdelta.y);
      final blocked = !board.isInBounds(target) ||
          board.hasTagAt(groundLayerId, target, wallTag, game.entityKinds) ||
          occupied.contains(target);
      if (blocked) continue;
      board.setEntity(actorLayerId, pos, null);
      board.setEntity(actorLayerId, target, entity);
      occupied.remove(pos);
      occupied.add(target);
      events.add(GameEvent.actorReacted(
          entity.kind, pos, target, _deltaDirection(rdelta)));
    }
    return events;
  }

  static const _canonicalBuckets = [
    Position(0, -1),
    Position(0, 1),
    Position(-1, 0),
    Position(1, 0),
  ];

  static String _deltaDirection(Position d) {
    if (d.x == 0 && d.y == -1) return 'up';
    if (d.x == 0 && d.y == 1) return 'down';
    if (d.x == -1 && d.y == 0) return 'left';
    if (d.x == 1 && d.y == 0) return 'right';
    return '';
  }

  Position? _parsePosition(dynamic raw) {
    if (raw is Position) return raw;
    if (raw is List && raw.length >= 2 && raw[0] is int && raw[1] is int) {
      return Position(raw[0] as int, raw[1] as int);
    }
    return null;
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
