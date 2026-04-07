import '../engine/goal_evaluator.dart';
import '../engine/lose_evaluator.dart';
import '../engine/turn_result.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/level_definition.dart';
import '../models/position.dart';
import '../rules/rules_engine.dart';
import '../systems/system_registry.dart';

/// Executes all 7 phases of a single turn.
class PhaseRunner {
  final GameDefinition _game;
  final LevelDefinition _level;
  final GoalEvaluator _goalEval = GoalEvaluator();
  final LoseEvaluator _loseEval = LoseEvaluator();

  PhaseRunner(this._game, this._level);

  TurnResult run(GameAction action, LevelState state) {
    // Instantiate systems with any level-specific overrides
    final systems = SystemRegistry.instantiate(_game, _level.systemOverrides);

    // Phase 1: Input validation
    if (!_game.isValidAction(action)) {
      return TurnResult.rejected(state);
    }

    final allEvents = <GameEvent>[];
    final animations = <AnimationStep>[];

    // Phase 2: Action resolution
    for (final sys in systems) {
      final events = sys.executeActionResolution(action, state, _game);
      allEvents.addAll(events);
      _collectAnimations(events, state, animations);
    }

    // Phase 3: Movement resolution
    for (final sys in systems) {
      final events = sys.executeMovementResolution(state, _game);
      allEvents.addAll(events);
      _collectAnimations(events, state, animations);
    }

    // Phase 4: Interaction resolution (no-op in v0)

    // Phase 5: Cascade resolution
    final rulesEngine = RulesEngine(
      _game.rules,
      _level.rules,
    );
    final maxDepth = _game.defaults.maxCascadeDepth;
    final cascadeEvents = rulesEngine.evaluate(
        allEvents, state, _game, maxDepth, systems);
    allEvents.addAll(cascadeEvents);
    _collectAnimationsFromList(cascadeEvents, state, animations);

    // Phase 6: NPC resolution
    for (final sys in systems) {
      final events = sys.executeNpcResolution(state, _game);
      allEvents.addAll(events);
    }

    // Phase 7: Goal evaluation
    state.actionCount++;
    state.turnCount++;

    // Check goals before lose conditions: winning on the last allowed move counts as a win.
    final goalStatus = _goalEval.evaluate(
        _level.goals, state, _game, allEvents);
    if (goalStatus.isWon) {
      state.isWon = true;
    }

    if (!state.isWon) {
      final loseStatus = _loseEval.evaluate(_level.loseConditions, state);
      if (loseStatus.isLost) {
        state.isLost = true;
        return TurnResult(
          accepted: true,
          newState: state,
          events: allEvents,
          animations: animations,
          goalProgress: goalStatus.progress,
          isWon: false,
          isLost: true,
          loseReason: loseStatus.reason,
        );
      }
    }

    allEvents.add(GameEvent.turnEnded(state.turnCount));

    return TurnResult(
      accepted: true,
      newState: state,
      events: allEvents,
      animations: animations,
      goalProgress: goalStatus.progress,
      isWon: goalStatus.isWon,
      isLost: false,
    );
  }

  void _collectAnimations(
      List<GameEvent> events, LevelState state, List<AnimationStep> out) {
    _collectAnimationsFromList(events, state, out);
  }

  void _collectAnimationsFromList(
      List<GameEvent> events, LevelState state, List<AnimationStep> out) {
    for (final event in events) {
      if (event.type == 'avatar_entered') {
        final pos = event.position;
        final from = event.payload['fromPosition'];
        if (pos != null && from != null) {
          final fromPos = from is Position ? from : Position.fromJson(from);
          out.add(AnimationStep.avatarMove(fromPos, pos));
        }
      }
      // Entity destroy animations: events carry an optional 'animation' key
      // naming the AnimationDef to play (e.g. 'burning' on wood).
      if (event.type == 'object_removed') {
        final animName = event.payload['animation'] as String?;
        final kind = event.payload['kind'] as String?;
        final pos = event.position;
        if (animName != null && kind != null && pos != null) {
          final animDef = _game.entityKinds[kind]?.animations[animName];
          if (animDef != null) {
            out.add(AnimationStep.entityAnim(pos, kind, animName, animDef.durationMs));
          }
        }
      }
    }
  }
}
