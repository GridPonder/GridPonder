import '../models/event.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// A single animation the UI should play before showing the next state.
class AnimationStep {
  final String type; // "entity_animation", "avatar_move", "avatar_push", etc.
  final Position position;
  final String? animationName; // entity kind's animation key
  final String? entityKind;
  final int durationMs;
  final Map<String, dynamic> extra;

  const AnimationStep({
    required this.type,
    required this.position,
    this.animationName,
    this.entityKind,
    required this.durationMs,
    this.extra = const {},
  });

  static AnimationStep entityAnim(
          Position pos, String entityKind, String animName, int durationMs) =>
      AnimationStep(
          type: 'entity_animation',
          position: pos,
          entityKind: entityKind,
          animationName: animName,
          durationMs: durationMs);

  static AnimationStep avatarMove(Position from, Position to,
          {int durationMs = 200}) =>
      AnimationStep(
          type: 'avatar_move',
          position: to,
          durationMs: durationMs,
          extra: {'from': [from.x, from.y], 'to': [to.x, to.y]});
}

/// The result of executing a single turn.
class TurnResult {
  /// Whether the action was accepted (false = illegal action, state unchanged).
  final bool accepted;
  final LevelState newState;
  final List<GameEvent> events;
  final List<AnimationStep> animations;
  final Map<String, double> goalProgress; // goalId → 0.0..1.0
  final bool isWon;
  final bool isLost;
  final String? loseReason;

  const TurnResult({
    required this.accepted,
    required this.newState,
    required this.events,
    required this.animations,
    required this.goalProgress,
    required this.isWon,
    required this.isLost,
    this.loseReason,
  });

  static TurnResult rejected(LevelState state) => TurnResult(
        accepted: false,
        newState: state,
        events: const [],
        animations: const [],
        goalProgress: const {},
        isWon: false,
        isLost: false,
      );
}
