import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/goal.dart';

class LoseStatus {
  final bool isLost;
  final String? reason;
  const LoseStatus({required this.isLost, this.reason});
}

class LoseEvaluator {
  LoseStatus evaluate(
    List<LoseConditionDef> conditions,
    LevelState state, {
    List<GoalDef> goals = const [],
    GameDefinition? game,
  }) {
    for (final cond in conditions) {
      switch (cond.type) {
        case 'max_actions':
          final limit = cond.config['limit'] as int;
          if (state.actionCount >= limit) {
            return LoseStatus(isLost: true, reason: 'max_actions');
          }
        case 'variable_threshold':
          final name = cond.config['variable'] as String;
          final target = cond.config['target'] as num;
          final comparison = (cond.config['comparison'] as String?) ?? 'gte';
          final current = state.variables[name];
          if (current != null) {
            final numVal = current as num;
            bool lost;
            switch (comparison) {
              case 'eq':
                lost = numVal == target;
              case 'gte':
                lost = numVal >= target;
              case 'lte':
                lost = numVal <= target;
              default:
                lost = false;
            }
            if (lost) {
              return LoseStatus(
                  isLost: true, reason: 'variable_threshold:$name');
            }
          }
        case 'balance_budget_exhausted':
          if (_balanceBudgetExhausted(cond.config, state, goals, game)) {
            return const LoseStatus(
              isLost: true,
              reason: 'balance_budget_exhausted',
            );
          }
        case 'balance_unreachable':
          if (_balanceUnreachable(cond.config, state, goals, game)) {
            return const LoseStatus(
              isLost: true,
              reason: 'balance_unreachable',
            );
          }
      }
    }
    return const LoseStatus(isLost: false);
  }

  /// Fires when the `balance` goal's equal-share requirement has already become
  /// impossible: some owner has claimed strictly more than its equal share
  /// (`claimable / owners`). Because a claimed cell can never change owner, an
  /// over-target owner can never come back down, so the level is unwinnable and
  /// is lost immediately rather than only when the action cap is reached. Also
  /// fires if `claimable` is not divisible by the owner count (equal shares are
  /// arithmetically impossible). Generic across coupled and individual modes;
  /// unlike `balance_budget_exhausted` it needs no actor/budget wiring.
  bool _balanceUnreachable(
    Map<String, dynamic> config,
    LevelState state,
    List<GoalDef> goals,
    GameDefinition? game,
  ) {
    final goal = _balanceGoalForCondition(config, goals);
    if (goal == null) return false;

    final owners =
        (goal.config['owners'] as List<dynamic>? ?? const []).cast<String>();
    if (owners.isEmpty) return false;

    final claimable = _countClaimable(state, goal.config, game);
    if (claimable % owners.length != 0) return true;
    final target = claimable ~/ owners.length;

    final owned = {for (final owner in owners) owner: 0};
    final layerId = goal.config['layer'] as String? ?? 'territory';
    final layer = state.board.layers[layerId];
    if (layer != null) {
      for (final entry in layer.entries()) {
        final count = owned[entry.value.kind];
        if (count != null) {
          owned[entry.value.kind] = count + 1;
        }
      }
    }

    return owned.values.any((count) => count > target);
  }

  bool _balanceBudgetExhausted(
    Map<String, dynamic> config,
    LevelState state,
    List<GoalDef> goals,
    GameDefinition? game,
  ) {
    final goal = _balanceGoalForCondition(config, goals);
    if (goal == null) return false;

    final owners =
        (goal.config['owners'] as List<dynamic>? ?? const []).cast<String>();
    if (owners.isEmpty) return false;

    final claimable = _countClaimable(state, goal.config, game);
    if (claimable % owners.length != 0) return true;
    final target = claimable ~/ owners.length;

    final owned = {for (final owner in owners) owner: 0};
    final layerId = goal.config['layer'] as String? ?? 'territory';
    final layer = state.board.layers[layerId];
    if (layer != null) {
      for (final entry in layer.entries()) {
        final count = owned[entry.value.kind];
        if (count != null) {
          owned[entry.value.kind] = count + 1;
        }
      }
    }

    if (owned.values.any((count) => count > target)) return true;

    final actorToOwner = _actorToOwner(config, game);
    if (actorToOwner.isEmpty) return false;

    final budgetKey =
        config['budgetVariable'] as String? ?? 'actorMovesRemaining';
    final rawRemaining = state.variables[budgetKey];
    final remaining = rawRemaining is Map
        ? rawRemaining.map((k, v) => MapEntry(k.toString(), (v as num).toInt()))
        : _individualBudgets(game);
    if (remaining.isEmpty) return false;

    for (final entry in actorToOwner.entries) {
      final ownerKind = entry.value;
      final ownerCount = owned[ownerKind];
      if (ownerCount == null) continue;
      final deficit = target - ownerCount;
      if (deficit > (remaining[entry.key] ?? 0)) return true;
    }
    return false;
  }

  GoalDef? _balanceGoalForCondition(
    Map<String, dynamic> config,
    List<GoalDef> goals,
  ) {
    final goalId = config['goalId'] as String?;
    for (final goal in goals) {
      if (goal.type != 'balance') continue;
      if (goalId == null || goal.id == goalId) return goal;
    }
    return null;
  }

  int _countClaimable(
    LevelState state,
    Map<String, dynamic> goalConfig,
    GameDefinition? game,
  ) {
    final layerId = goalConfig['claimableLayer'] as String? ?? 'ground';
    final claimableKind = (goalConfig['claimableKind'] as String?) ??
        _layerDefaultKind(game, layerId) ??
        'empty';
    final layer = state.board.layers[layerId];
    if (layer == null) return 0;
    return layer
        .entries()
        .where((entry) => entry.value.kind == claimableKind)
        .length;
  }

  String? _layerDefaultKind(GameDefinition? game, String layerId) {
    if (game == null) return null;
    for (final layer in game.layers) {
      if (layer.id == layerId) return layer.defaultKind;
    }
    return null;
  }

  Map<String, String> _actorToOwner(
    Map<String, dynamic> config,
    GameDefinition? game,
  ) {
    final explicit = config['actorToOwner'];
    if (explicit is Map) {
      return explicit.map((k, v) => MapEntry(k.toString(), v.toString()));
    }
    if (game == null) return const {};
    for (final system in game.systems) {
      if (system.type == 'individual_actors' && system.enabled) {
        final claim = system.config['claim'];
        if (claim is Map) {
          final map = claim['map'];
          if (map is Map) {
            return map.map((k, v) => MapEntry(k.toString(), v.toString()));
          }
        }
      }
    }
    return const {};
  }

  Map<String, int> _individualBudgets(GameDefinition? game) {
    if (game == null) return const {};
    for (final system in game.systems) {
      if (system.type == 'individual_actors' && system.enabled) {
        final budgets = system.config['budgets'];
        if (budgets is Map) {
          return budgets
              .map((k, v) => MapEntry(k.toString(), (v as num).toInt()));
        }
      }
    }
    return const {};
  }
}
