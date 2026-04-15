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
      case 'sum_constraint':
        return _sumConstraint(goal, state);
      case 'count_constraint':
        return _countConstraint(goal, state);
      case 'param_match':
        return _paramMatch(goal, state);
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

  /// Evaluates row/column/board numeric sum constraints.
  ///
  /// Config fields:
  ///   layer      — layer id to scan (default "objects")
  ///   scope      — "row" | "col" | "all_rows" | "all_cols" | "board"
  ///   index      — row or col index (required for "row" / "col" scopes)
  ///   target     — expected sum (num)
  ///   comparison — "eq" (default) | "gte" | "lte"
  ///
  /// Numeric value is extracted from `num_<n>` kind or `number` kind with
  /// a `value` parameter. Non-numeric entities contribute 0.
  (bool, double) _sumConstraint(GoalDef goal, LevelState state) {
    final layerId = (goal.config['layer'] as String?) ?? 'objects';
    final scope = (goal.config['scope'] as String?) ?? 'board';
    final target = goal.config['target'] as num;
    final comparison = (goal.config['comparison'] as String?) ?? 'eq';
    final index = goal.config['index'] as int?;

    final layer = state.board.layers[layerId];
    if (layer == null) return (false, 0.0);

    final w = state.board.width;
    final h = state.board.height;

    int cellValue(Position pos) {
      final entity = layer.getAt(pos);
      if (entity == null) return 0;
      final kind = entity.kind;
      if (kind.startsWith('num_')) return int.tryParse(kind.substring(4)) ?? 0;
      if (kind == 'number') return (entity.param('value') as int?) ?? 0;
      return 0;
    }

    int rowSum(int y) =>
        List.generate(w, (x) => cellValue(Position(x, y))).fold(0, (a, b) => a + b);
    int colSum(int x) =>
        List.generate(h, (y) => cellValue(Position(x, y))).fold(0, (a, b) => a + b);

    bool satisfies(int sum) => switch (comparison) {
          'gte' => sum >= target,
          'lte' => sum <= target,
          _ => sum == target,
        };

    switch (scope) {
      case 'row':
        if (index == null) return (false, 0.0);
        final ok = satisfies(rowSum(index));
        return (ok, ok ? 1.0 : 0.0);
      case 'col':
        if (index == null) return (false, 0.0);
        final ok = satisfies(colSum(index));
        return (ok, ok ? 1.0 : 0.0);
      case 'all_rows':
        final satisfied = List.generate(h, rowSum).where(satisfies).length;
        return (satisfied == h, satisfied / h);
      case 'all_cols':
        final satisfied = List.generate(w, colSum).where(satisfies).length;
        return (satisfied == w, satisfied / w);
      case 'board':
        int total = 0;
        for (int y = 0; y < h; y++)
          for (int x = 0; x < w; x++) total += cellValue(Position(x, y));
        final ok = satisfies(total);
        return (ok, ok ? 1.0 : 0.0);
      default:
        return (false, 0.0);
    }
  }

  /// Evaluates row/column count constraints based on a cell predicate.
  ///
  /// Config fields:
  ///   layer      — layer id to scan (default "objects")
  ///   scope      — "all_rows" | "all_cols" | "row" | "col"
  ///   index      — row or col index (required for "row" / "col" scopes)
  ///   predicate  — "even" | "odd" | "gte_N" | "lte_N" | "eq_N"
  ///   target     — expected count (num)
  ///   comparison — "eq" (default) | "gte" | "lte"
  (bool, double) _countConstraint(GoalDef goal, LevelState state) {
    final layerId = (goal.config['layer'] as String?) ?? 'objects';
    final scope = (goal.config['scope'] as String?) ?? 'all_rows';
    final predicate = (goal.config['predicate'] as String?) ?? 'even';
    final target = goal.config['target'] as num;
    final comparison = (goal.config['comparison'] as String?) ?? 'eq';
    final index = goal.config['index'] as int?;

    final layer = state.board.layers[layerId];
    if (layer == null) return (false, 0.0);

    final w = state.board.width;
    final h = state.board.height;

    int cellValue(Position pos) {
      final entity = layer.getAt(pos);
      if (entity == null) return 0;
      final kind = entity.kind;
      if (kind.startsWith('num_')) return int.tryParse(kind.substring(4)) ?? 0;
      if (kind == 'number') return (entity.param('value') as int?) ?? 0;
      return 0;
    }

    bool matchesPredicate(int value) {
      if (predicate == 'even') return value % 2 == 0;
      if (predicate == 'odd') return value % 2 != 0;
      if (predicate.startsWith('gte_')) {
        return value >= int.parse(predicate.substring(4));
      }
      if (predicate.startsWith('lte_')) {
        return value <= int.parse(predicate.substring(4));
      }
      if (predicate.startsWith('eq_')) {
        return value == int.parse(predicate.substring(3));
      }
      return false;
    }

    bool hasEntity(Position pos) => layer.getAt(pos) != null;

    int rowCount(int y) {
      int count = 0;
      for (int x = 0; x < w; x++) {
        final pos = Position(x, y);
        if (hasEntity(pos) && matchesPredicate(cellValue(pos))) count++;
      }
      return count;
    }

    int colCount(int x) {
      int count = 0;
      for (int y = 0; y < h; y++) {
        final pos = Position(x, y);
        if (hasEntity(pos) && matchesPredicate(cellValue(pos))) count++;
      }
      return count;
    }

    bool satisfies(int count) => switch (comparison) {
          'gte' => count >= target,
          'lte' => count <= target,
          _ => count == target,
        };

    switch (scope) {
      case 'row':
        if (index == null) return (false, 0.0);
        final ok = satisfies(rowCount(index));
        return (ok, ok ? 1.0 : 0.0);
      case 'col':
        if (index == null) return (false, 0.0);
        final ok = satisfies(colCount(index));
        return (ok, ok ? 1.0 : 0.0);
      case 'all_rows':
        final satisfied = List.generate(h, rowCount).where(satisfies).length;
        return (satisfied == h, satisfied / h);
      case 'all_cols':
        final satisfied = List.generate(w, colCount).where(satisfies).length;
        return (satisfied == w, satisfied / w);
      default:
        return (false, 0.0);
    }
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

  /// Checks that every marker position has an entity with a specific param value.
  (bool, double) _paramMatch(GoalDef goal, LevelState state) {
    final markerLayerId = goal.config['markerLayer'] as String? ?? 'markers';
    final markerKind = goal.config['markerKind'] as String?;
    final checkLayerId = goal.config['checkLayer'] as String? ?? 'objects';
    final checkKind = goal.config['checkKind'] as String?;
    final checkParam = goal.config['checkParam'] as String?;
    final checkValue = goal.config['checkValue'];

    if (checkParam == null || checkValue == null) return (false, 0.0);

    final markerLayer = state.board.layers[markerLayerId];
    final checkLayer = state.board.layers[checkLayerId];
    if (markerLayer == null) return (false, 0.0);

    int total = 0;
    int matched = 0;
    for (final entry in markerLayer.entries()) {
      if (markerKind != null && entry.value.kind != markerKind) continue;
      total++;
      if (checkLayer == null) continue;
      final entity = checkLayer.getAt(entry.key);
      if (entity == null) continue;
      if (checkKind != null && entity.kind != checkKind) continue;
      if (entity.param(checkParam) == checkValue) matched++;
    }

    if (total == 0) return (false, 0.0);
    return (matched == total, matched / total);
  }
}
