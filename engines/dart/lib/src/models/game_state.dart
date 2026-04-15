import 'avatar.dart';
import 'board.dart';
import 'position.dart';
import 'direction.dart';

/// Overlay cursor state.
class OverlayCursor {
  final int x;
  final int y;
  final int width;
  final int height;

  const OverlayCursor({
    required this.x,
    required this.y,
    required this.width,
    required this.height,
  });

  Position get position => Position(x, y);

  factory OverlayCursor.fromJson(Map<String, dynamic> j) {
    final pos = j['position'] as List?;
    final size = j['size'] as List?;
    return OverlayCursor(
      x: pos?[0] as int? ?? 0,
      y: pos?[1] as int? ?? 0,
      width: size?[0] as int? ?? 2,
      height: size?[1] as int? ?? 2,
    );
  }

  OverlayCursor copyWith({int? x, int? y, int? width, int? height}) =>
      OverlayCursor(
        x: x ?? this.x,
        y: y ?? this.y,
        width: width ?? this.width,
        height: height ?? this.height,
      );
}

/// A pending avatar move (set when solidHandling: "delegate" encounters a solid).
class PendingMove {
  final Position from;
  final Position to;
  final Direction direction;

  const PendingMove({
    required this.from,
    required this.to,
    required this.direction,
  });
}

/// The full mutable runtime state for a level.
class LevelState {
  Board board;
  AvatarState avatar;
  Map<String, dynamic> variables;
  OverlayCursor? overlay;
  int turnCount;
  int actionCount;
  PendingMove? pendingMove;

  /// Sequence goal progress: goalId → current index into the sequence.
  Map<String, int> sequenceIndices;

  /// Rules with `once: true` that have already fired this level attempt.
  Set<String> onceFiredRules;

  bool isWon;
  bool isLost;

  LevelState({
    required this.board,
    required this.avatar,
    required this.variables,
    this.overlay,
    this.turnCount = 0,
    this.actionCount = 0,
    this.pendingMove,
    Map<String, int>? sequenceIndices,
    Set<String>? onceFiredRules,
    this.isWon = false,
    this.isLost = false,
  })  : sequenceIndices = sequenceIndices ?? {},
        onceFiredRules = onceFiredRules ?? {};

  factory LevelState.fromJson(
    Map<String, dynamic> stateJson,
    Board board,
  ) {
    final avatarJson = stateJson['avatar'] as Map<String, dynamic>? ?? {};
    final vars = Map<String, dynamic>.from(
        stateJson['variables'] as Map? ?? {});
    final overlayJson = stateJson['overlay'] as Map<String, dynamic>?;

    return LevelState(
      board: board,
      avatar: AvatarState.fromJson(avatarJson),
      variables: vars,
      overlay: overlayJson != null ? OverlayCursor.fromJson(overlayJson) : null,
    );
  }

  /// Deep copy for undo snapshots.
  LevelState copy() => LevelState(
        board: board.copy(),
        avatar: avatar,
        variables: Map.from(variables),
        overlay: overlay,
        turnCount: turnCount,
        actionCount: actionCount,
        pendingMove: pendingMove,
        sequenceIndices: Map.from(sequenceIndices),
        onceFiredRules: Set.from(onceFiredRules),
        isWon: isWon,
        isLost: isLost,
      );
}
