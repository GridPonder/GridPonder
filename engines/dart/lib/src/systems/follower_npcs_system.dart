import '../engine/game_system.dart';
import '../models/board.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';
import '../models/direction.dart';
import '../models/entity.dart';

class FollowerNpcsSystem extends GameSystem {
  const FollowerNpcsSystem({required super.id}) : super(type: 'follower_npcs');

  @override
  List<GameEvent> executeNpcResolution(
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, {});

    final npcTagsRaw = config['npcTags'] as List<dynamic>? ?? ['npc'];
    final npcTags = npcTagsRaw.map((t) => t.toString()).toList();

    final behaviorsConfig =
        config['behaviors'] as Map<String, dynamic>? ?? {};

    final board = state.board;
    final actorsLayer = board.layers['actors'];
    if (actorsLayer == null) return const [];

    final events = <GameEvent>[];

    // Collect all NPC positions first to avoid mutation during iteration
    final npcEntries = <MapEntry<Position, EntityInstance>>[];
    for (final entry in actorsLayer.entries()) {
      final entity = entry.value;
      final isNpc = npcTags.any((tag) => game.hasTag(entity.kind, tag));
      if (isNpc) {
        npcEntries.add(entry);
      }
    }

    // Track positions occupied by NPCs this turn (after moves) to avoid collisions
    final occupiedAfterMove = <Position>{};
    // Pre-populate with NPC positions that haven't moved yet
    for (final entry in npcEntries) {
      occupiedAfterMove.add(entry.key);
    }

    for (final entry in npcEntries) {
      final npcPos = entry.key;
      final npcEntity = entry.value;

      final behaviorName = npcEntity.param('behavior')?.toString();
      if (behaviorName == null) continue;

      final behaviorDef = behaviorsConfig[behaviorName] as Map<String, dynamic>?;
      if (behaviorDef == null) continue;

      final behaviorType = behaviorDef['type'] as String?;
      if (behaviorType == null) continue;

      // Frequency check
      final frequency = behaviorDef['frequency'] as int? ?? 1;
      final turnCount = state.variables['turnCount'] as int? ?? 0;
      if (frequency > 1 && turnCount % frequency != 0) continue;

      final solidBlocking = behaviorDef['solidBlocking'] as bool? ?? true;

      final nextPos = _computeNextPosition(
        npcPos: npcPos,
        npcEntity: npcEntity,
        behaviorType: behaviorType,
        behaviorDef: behaviorDef,
        state: state,
        game: game,
        solidBlocking: solidBlocking,
        occupiedAfterMove: occupiedAfterMove,
      );

      if (nextPos == null || nextPos == npcPos) continue;

      // Remove from occupied set (old position) and add new
      occupiedAfterMove.remove(npcPos);
      occupiedAfterMove.add(nextPos);

      // Move NPC on board
      board.setEntity('actors', npcPos, null);
      board.setEntity('actors', nextPos, npcEntity);

      final npcId = 'spirit_${npcPos.x}_${npcPos.y}';
      events.add(GameEvent.npcMoved(npcId, npcPos, nextPos));
    }

    return events;
  }

  Position? _computeNextPosition({
    required Position npcPos,
    required EntityInstance npcEntity,
    required String behaviorType,
    required Map<String, dynamic> behaviorDef,
    required LevelState state,
    required GameDefinition game,
    required bool solidBlocking,
    required Set<Position> occupiedAfterMove,
  }) {
    final board = state.board;

    switch (behaviorType) {
      case 'toward_avatar':
        return _behaviorTowardAvatar(
          npcPos: npcPos,
          state: state,
          board: board,
          game: game,
          solidBlocking: solidBlocking,
          occupiedAfterMove: occupiedAfterMove,
        );

      case 'toward_tag':
        final targetTag = behaviorDef['targetTag'] as String?;
        if (targetTag == null) return null;
        return _behaviorTowardTag(
          npcPos: npcPos,
          targetTag: targetTag,
          board: board,
          game: game,
          solidBlocking: solidBlocking,
          occupiedAfterMove: occupiedAfterMove,
        );

      case 'toward_color':
        final targetColor = behaviorDef['targetColor'] as String?;
        if (targetColor == null) return null;
        return _behaviorTowardColor(
          npcPos: npcPos,
          targetColor: targetColor,
          board: board,
          game: game,
          solidBlocking: solidBlocking,
          occupiedAfterMove: occupiedAfterMove,
        );

      case 'clockwise':
        return _behaviorClockwise(
          npcPos: npcPos,
          npcEntity: npcEntity,
          board: board,
          game: game,
          solidBlocking: solidBlocking,
          occupiedAfterMove: occupiedAfterMove,
        );

      case 'patrol':
        return _behaviorPatrol(
          npcPos: npcPos,
          npcEntity: npcEntity,
          board: board,
          game: game,
          solidBlocking: solidBlocking,
          occupiedAfterMove: occupiedAfterMove,
        );

      default:
        return null;
    }
  }

  bool _canMoveTo({
    required Position pos,
    required Board board,
    required GameDefinition game,
    required bool solidBlocking,
    required Set<Position> occupiedAfterMove,
    required LevelState state,
  }) {
    if (!board.isInBounds(pos)) return false;
    if (board.isVoid(pos)) return false;

    // Can't overlap with avatar
    if (state.avatar.position == pos) return false;

    // Can't overlap with other NPCs
    if (occupiedAfterMove.contains(pos)) return false;

    // Check solid blocking via objects layer
    if (solidBlocking) {
      final objectsLayer = board.layers['objects'];
      if (objectsLayer != null) {
        final entity = objectsLayer.getAt(pos);
        if (entity != null && game.hasTag(entity.kind, 'solid')) return false;
      }
    }

    return true;
  }

  Direction _cardinalTowardTarget(Position from, Position target) {
    final dx = target.x - from.x;
    final dy = target.y - from.y;

    // Prefer x-axis movement first
    if (dx.abs() >= dy.abs()) {
      return dx > 0 ? Direction.right : Direction.left;
    } else {
      return dy > 0 ? Direction.down : Direction.up;
    }
  }

  Position? _stepToward({
    required Position npcPos,
    required Position target,
    required Board board,
    required GameDefinition game,
    required bool solidBlocking,
    required Set<Position> occupiedAfterMove,
    required LevelState state,
  }) {
    final cardinalDirs = [
      Direction.up,
      Direction.down,
      Direction.left,
      Direction.right,
    ];

    // Try preferred direction first (reduces manhattan distance more on dominant axis)
    final preferred = _cardinalTowardTarget(npcPos, target);
    final ordered = [preferred, ...cardinalDirs.where((d) => d != preferred)];

    // Among directions that reduce distance, pick best
    Position? best;
    int bestDist = _manhattan(npcPos, target);

    for (final dir in ordered) {
      final candidate = npcPos.moved(dir);
      final dist = _manhattan(candidate, target);
      if (dist < bestDist) {
        if (_canMoveTo(
          pos: candidate,
          board: board,
          game: game,
          solidBlocking: solidBlocking,
          occupiedAfterMove: occupiedAfterMove,
          state: state,
        )) {
          bestDist = dist;
          best = candidate;
        }
      }
    }

    return best;
  }

  int _manhattan(Position a, Position b) {
    return (a.x - b.x).abs() + (a.y - b.y).abs();
  }

  Position? _behaviorTowardAvatar({
    required Position npcPos,
    required LevelState state,
    required Board board,
    required GameDefinition game,
    required bool solidBlocking,
    required Set<Position> occupiedAfterMove,
  }) {
    final avatarPos = state.avatar.position;
    if (avatarPos == null) return null;

    return _stepToward(
      npcPos: npcPos,
      target: avatarPos,
      board: board,
      game: game,
      solidBlocking: solidBlocking,
      occupiedAfterMove: occupiedAfterMove,
      state: state,
    );
  }

  Position? _behaviorTowardTag({
    required Position npcPos,
    required String targetTag,
    required Board board,
    required GameDefinition game,
    required bool solidBlocking,
    required Set<Position> occupiedAfterMove,
  }) {
    // Find nearest entity with targetTag in objects/markers layers
    Position? nearestTarget;
    int nearestDist = 999999;

    for (final layerName in ['objects', 'markers']) {
      final layer = board.layers[layerName];
      if (layer == null) continue;
      for (final entry in layer.entries()) {
        if (game.hasTag(entry.value.kind, targetTag)) {
          final dist = _manhattan(npcPos, entry.key);
          if (dist < nearestDist) {
            nearestDist = dist;
            nearestTarget = entry.key;
          }
        }
      }
    }

    if (nearestTarget == null) return null;

    // Create a dummy state-like object isn't possible, so we pass a minimal check
    // We need a LevelState to call _canMoveTo, but we only have board here.
    // Use a direct inline check instead.
    final cardinalDirs = [
      Direction.up,
      Direction.down,
      Direction.left,
      Direction.right,
    ];

    final preferred = _cardinalTowardTarget(npcPos, nearestTarget);
    final ordered = [
      preferred,
      ...cardinalDirs.where((d) => d != preferred),
    ];

    Position? best;
    int bestDist = _manhattan(npcPos, nearestTarget);

    for (final dir in ordered) {
      final candidate = npcPos.moved(dir);
      final dist = _manhattan(candidate, nearestTarget);
      if (dist < bestDist) {
        if (!board.isInBounds(candidate)) continue;
        if (board.isVoid(candidate)) continue;
        if (occupiedAfterMove.contains(candidate)) continue;
        if (solidBlocking) {
          final objectsLayer = board.layers['objects'];
          if (objectsLayer != null) {
            final entity = objectsLayer.getAt(candidate);
            if (entity != null && game.hasTag(entity.kind, 'solid')) continue;
          }
        }
        bestDist = dist;
        best = candidate;
      }
    }

    return best;
  }

  Position? _behaviorTowardColor({
    required Position npcPos,
    required String targetColor,
    required Board board,
    required GameDefinition game,
    required bool solidBlocking,
    required Set<Position> occupiedAfterMove,
  }) {
    // Find nearest entity in objects/actors layers where param("color") == targetColor
    Position? nearestTarget;
    int nearestDist = 999999;

    for (final layerName in ['objects', 'actors']) {
      final layer = board.layers[layerName];
      if (layer == null) continue;
      for (final entry in layer.entries()) {
        final colorParam = entry.value.param('color');
        if (colorParam?.toString() == targetColor) {
          final dist = _manhattan(npcPos, entry.key);
          if (dist < nearestDist) {
            nearestDist = dist;
            nearestTarget = entry.key;
          }
        }
      }
    }

    if (nearestTarget == null) return null;

    final cardinalDirs = [
      Direction.up,
      Direction.down,
      Direction.left,
      Direction.right,
    ];

    final preferred = _cardinalTowardTarget(npcPos, nearestTarget);
    final ordered = [
      preferred,
      ...cardinalDirs.where((d) => d != preferred),
    ];

    Position? best;
    int bestDist = _manhattan(npcPos, nearestTarget);

    for (final dir in ordered) {
      final candidate = npcPos.moved(dir);
      final dist = _manhattan(candidate, nearestTarget);
      if (dist < bestDist) {
        if (!board.isInBounds(candidate)) continue;
        if (board.isVoid(candidate)) continue;
        if (occupiedAfterMove.contains(candidate)) continue;
        if (solidBlocking) {
          final objectsLayer = board.layers['objects'];
          if (objectsLayer != null) {
            final entity = objectsLayer.getAt(candidate);
            if (entity != null && game.hasTag(entity.kind, 'solid')) continue;
          }
        }
        bestDist = dist;
        best = candidate;
      }
    }

    return best;
  }

  // Clockwise rotation order: right -> down -> left -> up -> right
  static const _clockwiseOrder = [
    Direction.right,
    Direction.down,
    Direction.left,
    Direction.up,
  ];

  Direction _rotateClockwise(Direction current) {
    final idx = _clockwiseOrder.indexOf(current);
    if (idx == -1) return Direction.right;
    return _clockwiseOrder[(idx + 1) % _clockwiseOrder.length];
  }

  Position? _behaviorClockwise({
    required Position npcPos,
    required EntityInstance npcEntity,
    required Board board,
    required GameDefinition game,
    required bool solidBlocking,
    required Set<Position> occupiedAfterMove,
  }) {
    final facingStr = npcEntity.param('facing')?.toString() ?? 'right';
    Direction facing;
    try {
      facing = Direction.fromJson(facingStr);
    } catch (_) {
      facing = Direction.right;
    }

    // Try current facing first, then rotate clockwise until a valid move is found
    for (var i = 0; i < _clockwiseOrder.length; i++) {
      final candidate = npcPos.moved(facing);
      final isValid = board.isInBounds(candidate) &&
          !board.isVoid(candidate) &&
          !occupiedAfterMove.contains(candidate) &&
          (!solidBlocking || _noSolidObject(board, game, candidate));
      if (isValid) {
        // Update NPC facing param (mutate params map directly)
        npcEntity.params['facing'] = facing.toJson();
        return candidate;
      }
      facing = _rotateClockwise(facing);
    }

    return null;
  }

  Position? _behaviorPatrol({
    required Position npcPos,
    required EntityInstance npcEntity,
    required Board board,
    required GameDefinition game,
    required bool solidBlocking,
    required Set<Position> occupiedAfterMove,
  }) {
    final facingStr = npcEntity.param('facing')?.toString() ?? 'right';
    Direction facing;
    try {
      facing = Direction.fromJson(facingStr);
    } catch (_) {
      facing = Direction.right;
    }

    final candidate = npcPos.moved(facing);
    final isValid = board.isInBounds(candidate) &&
        !board.isVoid(candidate) &&
        !occupiedAfterMove.contains(candidate) &&
        (!solidBlocking || _noSolidObject(board, game, candidate));

    if (isValid) {
      return candidate;
    }

    // Reverse direction on obstacle
    final reversed = _reverseDirection(facing);
    final reversedCandidate = npcPos.moved(reversed);
    final reversedValid = board.isInBounds(reversedCandidate) &&
        !board.isVoid(reversedCandidate) &&
        !occupiedAfterMove.contains(reversedCandidate) &&
        (!solidBlocking || _noSolidObject(board, game, reversedCandidate));

    if (reversedValid) {
      npcEntity.params['facing'] = reversed.toJson();
      return reversedCandidate;
    }

    return null;
  }

  bool _noSolidObject(Board board, GameDefinition game, Position pos) {
    final objectsLayer = board.layers['objects'];
    if (objectsLayer == null) return true;
    final entity = objectsLayer.getAt(pos);
    if (entity == null) return true;
    return !game.hasTag(entity.kind, 'solid');
  }

  Direction _reverseDirection(Direction dir) {
    switch (dir) {
      case Direction.up:
        return Direction.down;
      case Direction.down:
        return Direction.up;
      case Direction.left:
        return Direction.right;
      case Direction.right:
        return Direction.left;
      case Direction.upLeft:
        return Direction.downRight;
      case Direction.upRight:
        return Direction.downLeft;
      case Direction.downLeft:
        return Direction.upRight;
      case Direction.downRight:
        return Direction.upLeft;
    }
  }
}
