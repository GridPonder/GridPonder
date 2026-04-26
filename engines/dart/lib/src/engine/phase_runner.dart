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

    // Stage allocator: each phase advances `baseStage` past whatever stages
    // its emitted animations used, so later phases never overlap earlier ones.
    int baseStage = 0;
    int advanceBase() {
      if (animations.isEmpty) return baseStage;
      final maxStage = animations
          .map((a) => a.stage)
          .fold<int>(baseStage, (m, s) => s > m ? s : m);
      return maxStage + 1;
    }

    // Phase 2: Action resolution
    for (final sys in systems) {
      final events = sys.executeActionResolution(action, state, _game);
      allEvents.addAll(events);
      _collectAnimations(events, state, animations, baseStage);
    }

    // If a system explicitly vetoed the action, reject without counting a move.
    if (allEvents.any((e) => e.type == 'action_vetoed')) {
      return TurnResult.rejected(state);
    }

    // Phase 3: Movement resolution
    baseStage = advanceBase();
    for (final sys in systems) {
      final events = sys.executeMovementResolution(state, _game);
      allEvents.addAll(events);
      _collectAnimations(events, state, animations, baseStage);
    }

    // Phase 4: Interaction resolution (no-op in v0)

    // Phase 5: Cascade resolution
    baseStage = advanceBase();
    final rulesEngine = RulesEngine(
      _game.rules,
      _level.rules,
    );
    final maxDepth = _game.defaults.maxCascadeDepth;
    final cascadeEvents = rulesEngine.evaluate(
        allEvents, state, _game, maxDepth, systems);
    allEvents.addAll(cascadeEvents);
    _collectAnimationsFromList(cascadeEvents, state, animations, baseStage);

    // Phase 6: NPC resolution
    baseStage = advanceBase();
    for (final sys in systems) {
      final events = sys.executeNpcResolution(state, _game);
      allEvents.addAll(events);
      _collectAnimations(events, state, animations, baseStage);
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

  void _collectAnimations(List<GameEvent> events, LevelState state,
          List<AnimationStep> out, int baseStage) =>
      _collectAnimationsFromList(events, state, out, baseStage);

  /// Translates [events] into [AnimationStep]s, appending to [out].
  ///
  /// Stage assignment within a phase:
  ///   • motion (avatar_move, tile_moved, item_released spawns) → baseStage+0
  ///   • merge   (tiles_merged with sources)                    → baseStage+1
  ///   • destroy (object_removed with animation)                → baseStage+2
  void _collectAnimationsFromList(List<GameEvent> events, LevelState state,
      List<AnimationStep> out, int baseStage) {
    final motionStage = baseStage;
    final mergeStage = baseStage + 1;
    final destroyStage = baseStage + 2;

    for (final event in events) {
      if (event.type == 'avatar_entered') {
        final pos = event.position;
        final from = event.payload['fromPosition'];
        if (pos != null && from != null) {
          final fromPos = from is Position ? from : Position.fromJson(from);
          out.add(AnimationStep.avatarMove(fromPos, pos, stage: motionStage));
        }
      } else if (event.type == 'tile_moved') {
        final pos = event.position;
        final from = event.payload['fromPosition'];
        final kind = event.payload['kind'] as String?;
        if (pos != null && from != null && kind != null) {
          final fromPos = from is Position ? from : Position.fromJson(from);
          final layer = event.payload['layer'] as String? ?? 'objects';
          final params = (event.payload['params'] as Map?)
                  ?.cast<String, dynamic>() ??
              const <String, dynamic>{};
          final dur = _motionDurationMs(kind, 'moveDurationMs', 130);
          out.add(AnimationStep.entityMove(
            fromPos, pos, kind, layer,
            durationMs: dur,
            stage: motionStage,
            params: params,
          ));
        }
      } else if (event.type == 'tiles_merged') {
        final pos = event.position;
        final sourcesRaw = event.payload['sources'];
        final kind = event.payload['kind'] as String?;
        if (pos != null && sourcesRaw is List && kind != null) {
          final sources = sourcesRaw
              .map((p) => p is Position ? p : Position.fromJson(p))
              .toList();
          final inputValues =
              (event.payload['inputValues'] as List?)?.cast<int>() ?? const [];
          final result = event.payload['resultValue'];
          // Build minimal source/result params; renderer can fall back to kind.
          final sourceParams = inputValues
              .map((v) => <String, dynamic>{'value': v})
              .toList();
          final sourceKinds = List<String>.filled(sources.length, kind);
          final resultParams = <String, dynamic>{
            if (result != null) 'value': result,
          };
          final dur = _motionDurationMs(kind, 'mergeDurationMs', 200);
          out.add(AnimationStep.entityMerge(
            pos, sources, sourceKinds, sourceParams, kind, resultParams,
            'objects',
            durationMs: dur,
            stage: mergeStage,
          ));
        }
      } else if (event.type == 'object_removed') {
        // Entity destroy animations: events carry an optional 'animation' key
        // naming the AnimationDef to play (e.g. 'burning' on wood).
        final animName = event.payload['animation'] as String?;
        final kind = event.payload['kind'] as String?;
        final pos = event.position;
        if (animName != null && kind != null && pos != null) {
          final animDef = _game.entityKinds[kind]?.animations[animName];
          if (animDef != null) {
            out.add(AnimationStep.entityAnim(
                pos, kind, animName, animDef.durationMs,
                stage: destroyStage));
          }
        }
      }
    }
  }

  int _motionDurationMs(String kind, String key, int fallback) {
    final motion = _game.entityKinds[kind]?.motion;
    if (motion == null) return fallback;
    final v = motion[key];
    if (v is int) return v;
    if (v is num) return v.toInt();
    return fallback;
  }
}
