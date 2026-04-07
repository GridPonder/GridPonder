import '../models/board.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/goal.dart';
import '../models/position.dart';

class GoalStatus {
  final bool isWon;
  final Map<String, double> progress; // goalId → 0.0..1.0

  const GoalStatus({required this.isWon, required this.progress});
}

class GoalEvaluator {
  /// Evaluate all goals. Level is won when ALL goals are satisfied.
  /// Also processes sequence_match progress and emits goal_step_completed events.
  GoalStatus evaluate(
    List<GoalDef> goals,
    LevelState state,
    GameDefinition game,
    List<GameEvent> pendingEvents,
  ) {
    if (goals.isEmpty) return const GoalStatus(isWon: false, progress: {});

    final progress = <String, double>{};
    bool allDone = true;

    for (final goal in goals) {
      final (done, prog) =
          _evaluateGoal(goal, state, game, pendingEvents);
      progress[goal.id] = prog;
      if (!done) allDone = false;
    }

    return GoalStatus(isWon: allDone, progress: progress);
  }

  (bool done, double progress) _evaluateGoal(
    GoalDef goal,
    LevelState state,
    GameDefinition game,
    List<GameEvent> pendingEvents,
  ) {
    switch (goal.type) {
      case 'reach_target':
        return _reachTarget(goal, state, game);
      case 'sequence_match':
        return _sequenceMatch(goal, state, game, pendingEvents);
      case 'board_match':
        return _boardMatch(goal, state, game);
      case 'variable_threshold':
        return _variableThreshold(goal, state);
      case 'all_cleared':
        return _allCleared(goal, state, game);
      default:
        return (false, 0.0);
    }
  }

  (bool, double) _reachTarget(
      GoalDef goal, LevelState state, GameDefinition game) {
    if (!state.avatar.enabled || state.avatar.position == null) {
      return (false, 0.0);
    }
    final pos = state.avatar.position!;
    final targetKind = goal.config['targetKind'] as String?;
    final targetTag = goal.config['targetTag'] as String?;

    bool reached = false;
    for (final layerId in ['markers', 'objects', 'ground', 'actors']) {
      final entity = state.board.getEntity(layerId, pos);
      if (entity == null) continue;
      if (targetKind != null && entity.kind == targetKind) {
        reached = true;
        break;
      }
      if (targetTag != null && game.hasTag(entity.kind, targetTag)) {
        reached = true;
        break;
      }
    }
    return (reached, reached ? 1.0 : 0.0);
  }

  (bool, double) _sequenceMatch(
    GoalDef goal,
    LevelState state,
    GameDefinition game,
    List<GameEvent> pendingEvents,
  ) {
    final sequence = (goal.config['sequence'] as List?)
            ?.map((e) => e as int)
            .toList() ??
        [];
    if (sequence.isEmpty) return (true, 1.0);

    final currentIndex = state.sequenceIndices[goal.id] ?? 0;

    // Process on_merge trigger: scan for current target in tiles_merged events
    final trigger = (goal.config['scanTrigger'] as String?) ?? 'turn_end';
    int index = currentIndex;

    if (trigger == 'on_merge') {
      for (final event in pendingEvents) {
        if (event.type == 'tiles_merged' && index < sequence.length) {
          final resultValue = event.payload['resultValue'] as int?;
          if (resultValue == sequence[index]) {
            index++;
            // Emit goal step completed (we add to pending events externally)
          }
        }
      }
    } else {
      // turn_end: scan board for current target
      while (index < sequence.length) {
        final target = sequence[index];
        final found = _findNumberOnBoard(state.board, target, game);
        if (found == null) break;
        // consume (remove) if consumeOnMatch is true (default)
        final consume = (goal.config['consumeOnMatch'] as bool?) ?? true;
        if (consume) {
          state.board.setEntity(found.key, found.value, null);
        }
        index++;
      }
    }

    state.sequenceIndices[goal.id] = index;

    final prog = sequence.isEmpty ? 1.0 : index / sequence.length;
    return (index >= sequence.length, prog);
  }

  MapEntry<String, Position>? _findNumberOnBoard(
      Board board, int target, GameDefinition game) {
    for (final entry in (board.layers['objects']?.entries() ?? const <MapEntry<Position, EntityInstance>>[])) {
      if (entry.value.kind == 'number') {
        final v = entry.value.param('value');
        if (v == target || v?.toString() == target.toString()) {
          return MapEntry('objects', entry.key);
        }
      }
    }
    return null;
  }

  (bool, double) _boardMatch(
      GoalDef goal, LevelState state, GameDefinition game) {
    final targetLayers =
        goal.config['targetLayers'] as Map<String, dynamic>? ?? {};
    final matchMode =
        (goal.config['matchMode'] as String?) ?? 'exact_non_null';

    int totalCells = 0;
    int matchedCells = 0;

    for (final layerEntry in targetLayers.entries) {
      final layerId = layerEntry.key;
      final targetData = layerEntry.value as List;
      final boardLayer = state.board.layers[layerId];
      if (boardLayer == null) continue;

      for (int y = 0; y < targetData.length; y++) {
        final row = targetData[y] as List;
        for (int x = 0; x < row.length; x++) {
          final target = row[x];
          if (matchMode == 'exact_non_null' && target == null) continue;
          totalCells++;
          final actual = boardLayer.getAt(Position(x, y));
          if (matchMode == 'exact_non_null') {
            final targetEntity = EntityInstance.fromJson(target);
            if (actual != null && actual.kind == targetEntity.kind) {
              matchedCells++;
            }
          } else {
            // exact
            if (target == null && actual == null) {
              matchedCells++;
            } else if (target != null && actual != null) {
              final targetEntity = EntityInstance.fromJson(target);
              if (actual.kind == targetEntity.kind) matchedCells++;
            }
          }
        }
      }
    }

    if (totalCells == 0) return (true, 1.0);
    final prog = matchedCells / totalCells;
    return (matchedCells == totalCells, prog);
  }

  (bool, double) _variableThreshold(GoalDef goal, LevelState state) {
    final name = goal.config['variable'] as String;
    final target = goal.config['target'] as num;
    final comparison =
        (goal.config['comparison'] as String?) ?? 'gte';
    final current = state.variables[name];
    if (current == null) return (false, 0.0);
    final numCurrent = current as num;

    bool done;
    switch (comparison) {
      case 'eq':
        done = numCurrent == target;
      case 'gte':
        done = numCurrent >= target;
      case 'lte':
        done = numCurrent <= target;
      default:
        done = false;
    }

    final prog = (target == 0)
        ? 1.0
        : (numCurrent / target).clamp(0.0, 1.0).toDouble();
    return (done, prog);
  }

  (bool, double) _allCleared(
      GoalDef goal, LevelState state, GameDefinition game) {
    final kind = goal.config['kind'] as String?;
    final tag = goal.config['tag'] as String?;

    int remaining = 0;
    for (final layer in state.board.layers.values) {
      for (final entry in layer.entries()) {
        if (kind != null && entry.value.kind == kind) remaining++;
        if (tag != null && game.hasTag(entry.value.kind, tag)) remaining++;
      }
    }

    return (remaining == 0, remaining == 0 ? 1.0 : 0.0);
  }
}
