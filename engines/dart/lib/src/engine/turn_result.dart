import '../models/event.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// A single animation the UI should play before showing the next state.
///
/// Steps with the same [stage] play in parallel; stage `N+1` starts after the
/// longest step in stage `N` has finished. The default stage is `0`, so legacy
/// animations (avatar_move, entity_animation) run concurrently as before.
///
/// Types:
///   - `entity_animation` — named in-place animation on an entityKind
///   - `avatar_move`      — avatar translates from `extra.from` → position
///   - `entity_move`      — entity translates from `extra.from` → position
///                          (extra: from:[x,y], layer:String)
///   - `entity_path`      — entity follows a multi-cell waypoint path
///                          (extra: path:[[x,y],…], layer:String)
///   - `entity_merge`     — two entities converge at position and combine
///                          (extra: sources:[[x,y],[x,y]], sourceKinds, sourceParams,
///                                  resultParams, layer)
///   - `entity_spawn`     — entity appears at position (pop / fade-in)
///                          (extra: layer:String, params:Map)
class AnimationStep {
  final String type;
  final Position position;
  final String? animationName; // entity kind's animation key
  final String? entityKind;
  final int durationMs;
  final int stage;
  final Map<String, dynamic> extra;

  const AnimationStep({
    required this.type,
    required this.position,
    this.animationName,
    this.entityKind,
    required this.durationMs,
    this.stage = 0,
    this.extra = const {},
  });

  static AnimationStep entityAnim(
          Position pos, String entityKind, String animName, int durationMs,
          {int stage = 0}) =>
      AnimationStep(
          type: 'entity_animation',
          position: pos,
          entityKind: entityKind,
          animationName: animName,
          durationMs: durationMs,
          stage: stage);

  static AnimationStep avatarMove(Position from, Position to,
          {int durationMs = 200, int stage = 0}) =>
      AnimationStep(
          type: 'avatar_move',
          position: to,
          durationMs: durationMs,
          stage: stage,
          extra: {'from': [from.x, from.y], 'to': [to.x, to.y]});

  static AnimationStep entityMove(
          Position from, Position to, String entityKind, String layer,
          {int durationMs = 150,
          int stage = 0,
          Map<String, dynamic> params = const {}}) =>
      AnimationStep(
          type: 'entity_move',
          position: to,
          entityKind: entityKind,
          durationMs: durationMs,
          stage: stage,
          extra: {
            'from': [from.x, from.y],
            'layer': layer,
            'params': params,
          });

  static AnimationStep entityPath(
          List<Position> path, String entityKind, String layer,
          {int durationMs = 80, // per step; total = durationMs * (path.length-1)
          int stage = 0,
          Map<String, dynamic> params = const {}}) =>
      AnimationStep(
          type: 'entity_path',
          position: path.last,
          entityKind: entityKind,
          durationMs: durationMs * (path.length - 1).clamp(1, 1 << 30),
          stage: stage,
          extra: {
            'path': path.map((p) => [p.x, p.y]).toList(),
            'layer': layer,
            'params': params,
            'stepDurationMs': durationMs,
          });

  static AnimationStep entityMerge(
          Position dest,
          List<Position> sources,
          List<String> sourceKinds,
          List<Map<String, dynamic>> sourceParams,
          String resultKind,
          Map<String, dynamic> resultParams,
          String layer,
          {int durationMs = 200, int stage = 0, String? animationName}) =>
      AnimationStep(
          type: 'entity_merge',
          position: dest,
          entityKind: resultKind,
          animationName: animationName,
          durationMs: durationMs,
          stage: stage,
          extra: {
            'sources': sources.map((p) => [p.x, p.y]).toList(),
            'sourceKinds': sourceKinds,
            'sourceParams': sourceParams,
            'resultParams': resultParams,
            'layer': layer,
          });

  static AnimationStep entitySpawn(
          Position pos, String entityKind, String layer,
          {int durationMs = 120,
          int stage = 0,
          Map<String, dynamic> params = const {}}) =>
      AnimationStep(
          type: 'entity_spawn',
          position: pos,
          entityKind: entityKind,
          durationMs: durationMs,
          stage: stage,
          extra: {'layer': layer, 'params': params});
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
