import '../models/game_state.dart';
import '../models/goal.dart';

class LoseStatus {
  final bool isLost;
  final String? reason;
  const LoseStatus({required this.isLost, this.reason});
}

class LoseEvaluator {
  LoseStatus evaluate(List<LoseConditionDef> conditions, LevelState state) {
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
              case 'eq': lost = numVal == target;
              case 'gte': lost = numVal >= target;
              case 'lte': lost = numVal <= target;
              default: lost = false;
            }
            if (lost) {
              return LoseStatus(isLost: true, reason: 'variable_threshold:$name');
            }
          }
      }
    }
    return const LoseStatus(isLost: false);
  }
}
