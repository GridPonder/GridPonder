import '../engine/game_system.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/rule.dart';
import 'condition_evaluator.dart';
import 'effect_executor.dart';

/// Runs the cascade resolution loop (phase 5).
class RulesEngine {
  final List<RuleDef> _gameRules;
  final List<RuleDef> _levelRules;
  final ConditionEvaluator _condEval = ConditionEvaluator();

  RulesEngine(this._gameRules, this._levelRules);

  /// Evaluate all rules against the given events, cascading up to maxDepth.
  /// Also runs cascade-phase systems after each pass.
  List<GameEvent> evaluate(
    List<GameEvent> initialEvents,
    LevelState state,
    GameDefinition game,
    int maxDepth,
    List<GameSystem> cascadeSystems,
  ) {
    final allNewEvents = <GameEvent>[];
    var pendingEvents = List<GameEvent>.from(initialEvents);
    final effectExec = EffectExecutor(game);

    // All rules in priority order (game-level first, then level-local)
    final allRules = [..._gameRules, ..._levelRules];
    allRules.sort((a, b) => b.priority.compareTo(a.priority));

    for (int pass = 0; pass < maxDepth; pass++) {
      if (pendingEvents.isEmpty) break;

      final newEvents = <GameEvent>[];

      for (final event in pendingEvents) {
        for (final rule in allRules) {
          if (rule.on != event.type) continue;

          // Check once-fired
          if (rule.once && state.onceFiredRules.contains(rule.id)) continue;

          // Evaluate where condition
          if (!_condEval.evaluate(rule.where, event, state, game)) continue;

          // Evaluate if condition
          if (!_condEval.evaluate(rule.ifCond, event, state, game)) continue;

          // Fire rule
          if (rule.once) state.onceFiredRules.add(rule.id);

          for (final effect in rule.then) {
            final effectEvents = effectExec.execute(effect, event, state);
            newEvents.addAll(effectEvents);
          }
        }
      }

      // Run cascade-phase systems
      for (final sys in cascadeSystems) {
        final sysEvents =
            sys.executeCascadeResolution(pendingEvents, state, game);
        newEvents.addAll(sysEvents);
      }

      allNewEvents.addAll(newEvents);
      pendingEvents = newEvents;
    }

    return allNewEvents;
  }
}
