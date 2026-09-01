import '../engine/game_system.dart';
import '../models/board.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';
import '../models/direction.dart';
import '../models/entity.dart';
import 'sight.dart';

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

    final contactVariable =
        config['contactVariable'] as String? ?? 'caught';

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

      // Gaze is about seeing, not moving, so it is refreshed before the
      // frequency gate and regardless of whether a step happens.
      bool? sight;
      if (behaviorType == 'toward_avatar') {
        sight = _avatarInSight(
          npcPos: npcPos,
          behaviorDef: behaviorDef,
          state: state,
          board: board,
          game: game,
        );
        final gazeParam = behaviorDef['gazeParam'] as String?;
        if (gazeParam != null) {
          final avatarPos = state.avatar.position;
          npcEntity.params[gazeParam] = (sight && avatarPos != null)
              ? _cardinalTowardTarget(npcPos, avatarPos).toJson()
              : 'rest';
        }
      }

      // Reported from wherever the NPC ends the turn, not from where it
      // looked: a chaser steps along the line it just traced.
      final npcId = 'spirit_${npcPos.x}_${npcPos.y}';
      final sightTarget = state.avatar.position;
      final reportSight = behaviorType == 'toward_avatar' &&
          sight == true &&
          (behaviorDef['requiresLineOfSight'] as bool? ?? false) &&
          sightTarget != null;
      void reportSightFrom(Position pos) {
        if (reportSight) {
          events.add(GameEvent.lineOfSightDetected(
            pos,
            sightTarget,
            'avatar',
            npcId,
            npcEntity.kind,
          ));
        }
      }

      // Frequency check. The turn counter lives on the state, not in the
      // variables map, and is incremented in the goal-evaluation phase after
      // this one — so the first turn sees 0 and a frequency of N acts on turn 1,
      // then every Nth turn after it.
      final frequency = behaviorDef['frequency'] as int? ?? 1;
      if (frequency > 1 && state.turnCount % frequency != 0) {
        reportSightFrom(npcPos);
        continue;
      }

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
        sight: sight,
      );

      if (nextPos == null || nextPos == npcPos) {
        reportSightFrom(npcPos);
        continue;
      }

      reportSightFrom(nextPos);
      final caught = state.avatar.position == nextPos;

      // Remove from occupied set (old position) and add new
      occupiedAfterMove.remove(npcPos);
      occupiedAfterMove.add(nextPos);

      // Move NPC on board
      board.setEntity('actors', npcPos, null);
      board.setEntity('actors', nextPos, npcEntity);

      events.add(GameEvent.npcMoved(npcId, npcPos, nextPos));

      if (caught) {
        // Goal and lose evaluation both run in the phase after this one, so
        // bumping the counter here is enough for a variable_threshold lose
        // condition to fire on the same turn.
        final current = (state.variables[contactVariable] as num?) ?? 0;
        state.variables[contactVariable] = current.toInt() + 1;
        events.add(GameEvent.avatarCaught(nextPos, npcEntity.kind, npcId));
      }
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
    bool? sight,
  }) {
    final board = state.board;

    // One flag governs every behavior: without it the avatar's cell is
    // impassable, so an NPC with no other option stands still or, for the
    // circuit behaviors, turns around.
    final lethalContact = behaviorDef['lethalContact'] as bool? ?? false;
    final blockAvatar = !lethalContact;

    switch (behaviorType) {
      case 'toward_avatar':
        return _behaviorTowardAvatar(
          npcPos: npcPos,
          behaviorDef: behaviorDef,
          state: state,
          board: board,
          game: game,
          solidBlocking: solidBlocking,
          occupiedAfterMove: occupiedAfterMove,
          sight: sight,
        );

      case 'toward_tag':
        final targetTag = behaviorDef['targetTag'] as String?;
        if (targetTag == null) return null;
        return _behaviorTowardTag(
          npcPos: npcPos,
          targetTag: targetTag,
          state: state,
          board: board,
          game: game,
          solidBlocking: solidBlocking,
          occupiedAfterMove: occupiedAfterMove,
          blockAvatar: blockAvatar,
        );

      case 'toward_color':
        final targetColor = behaviorDef['targetColor'] as String?;
        if (targetColor == null) return null;
        return _behaviorTowardColor(
          npcPos: npcPos,
          targetColor: targetColor,
          state: state,
          board: board,
          game: game,
          solidBlocking: solidBlocking,
          occupiedAfterMove: occupiedAfterMove,
          blockAvatar: blockAvatar,
        );

      case 'clockwise':
        return _behaviorClockwise(
          npcPos: npcPos,
          npcEntity: npcEntity,
          state: state,
          board: board,
          game: game,
          solidBlocking: solidBlocking,
          occupiedAfterMove: occupiedAfterMove,
          blockAvatar: blockAvatar,
        );

      case 'patrol':
        return _behaviorPatrol(
          npcPos: npcPos,
          npcEntity: npcEntity,
          state: state,
          board: board,
          game: game,
          solidBlocking: solidBlocking,
          occupiedAfterMove: occupiedAfterMove,
          blockAvatar: blockAvatar,
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
    bool blockAvatar = true,
  }) {
    if (!board.isInBounds(pos)) return false;
    if (board.isVoid(pos)) return false;

    // Can't overlap with the avatar unless the behavior treats contact as
    // lethal, in which case stepping onto the avatar is the point.
    if (blockAvatar && state.avatar.position == pos) return false;

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
    bool blockAvatar = true,
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
          blockAvatar: blockAvatar,
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


  /// Whether this behavior currently considers the avatar visible. A behavior
  /// without `requiresLineOfSight` chases unconditionally, so it always counts
  /// as seeing the avatar.
  bool _avatarInSight({
    required Position npcPos,
    required Map<String, dynamic> behaviorDef,
    required LevelState state,
    required Board board,
    required GameDefinition game,
  }) {
    final avatarPos = state.avatar.position;
    if (avatarPos == null) return false;
    if (!(behaviorDef['requiresLineOfSight'] as bool? ?? false)) return true;

    final blockingLayers =
        (behaviorDef['blockingLayers'] as List<dynamic>? ?? ['objects'])
            .map((l) => l.toString())
            .toList();
    final blockingTags =
        (behaviorDef['blockingTags'] as List<dynamic>? ?? ['solid'])
            .map((t) => t.toString())
            .toList();
    return hasClearLine(
      npcPos,
      avatarPos,
      null,
      state,
      game,
      blockingLayers,
      blockingTags,
      behaviorDef['multiCellObjectsBlock'] as bool? ?? true,
    );
  }

  Position? _behaviorTowardAvatar({
    required Position npcPos,
    required Map<String, dynamic> behaviorDef,
    required LevelState state,
    required Board board,
    required GameDefinition game,
    required bool solidBlocking,
    required Set<Position> occupiedAfterMove,
    bool? sight,
  }) {
    final avatarPos = state.avatar.position;
    if (avatarPos == null) return null;

    final lethalContact = behaviorDef['lethalContact'] as bool? ?? false;

    final visible = sight ??
        _avatarInSight(
          npcPos: npcPos,
          behaviorDef: behaviorDef,
          state: state,
          board: board,
          game: game,
        );
    if (!visible) return null;

    return _stepToward(
      npcPos: npcPos,
      target: avatarPos,
      board: board,
      game: game,
      solidBlocking: solidBlocking,
      occupiedAfterMove: occupiedAfterMove,
      state: state,
      blockAvatar: !lethalContact,
    );
  }

  Position? _behaviorTowardTag({
    required Position npcPos,
    required String targetTag,
    required LevelState state,
    required Board board,
    required GameDefinition game,
    required bool solidBlocking,
    required Set<Position> occupiedAfterMove,
    required bool blockAvatar,
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
      if (dist < bestDist &&
          _canMoveTo(
            pos: candidate,
            board: board,
            game: game,
            solidBlocking: solidBlocking,
            occupiedAfterMove: occupiedAfterMove,
            state: state,
            blockAvatar: blockAvatar,
          )) {
        bestDist = dist;
        best = candidate;
      }
    }

    return best;
  }

  Position? _behaviorTowardColor({
    required Position npcPos,
    required String targetColor,
    required LevelState state,
    required Board board,
    required GameDefinition game,
    required bool solidBlocking,
    required Set<Position> occupiedAfterMove,
    required bool blockAvatar,
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
      if (dist < bestDist &&
          _canMoveTo(
            pos: candidate,
            board: board,
            game: game,
            solidBlocking: solidBlocking,
            occupiedAfterMove: occupiedAfterMove,
            state: state,
            blockAvatar: blockAvatar,
          )) {
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
    required LevelState state,
    required Board board,
    required GameDefinition game,
    required bool solidBlocking,
    required Set<Position> occupiedAfterMove,
    required bool blockAvatar,
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
      final isValid = _canMoveTo(
        pos: candidate,
        board: board,
        game: game,
        solidBlocking: solidBlocking,
        occupiedAfterMove: occupiedAfterMove,
        state: state,
        blockAvatar: blockAvatar,
      );
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
    required LevelState state,
    required Board board,
    required GameDefinition game,
    required bool solidBlocking,
    required Set<Position> occupiedAfterMove,
    required bool blockAvatar,
  }) {
    final facingStr = npcEntity.param('facing')?.toString() ?? 'right';
    Direction facing;
    try {
      facing = Direction.fromJson(facingStr);
    } catch (_) {
      facing = Direction.right;
    }

    final candidate = npcPos.moved(facing);
    if (_canMoveTo(
      pos: candidate,
      board: board,
      game: game,
      solidBlocking: solidBlocking,
      occupiedAfterMove: occupiedAfterMove,
      state: state,
      blockAvatar: blockAvatar,
    )) {
      return candidate;
    }

    // Reverse direction on obstacle
    final reversed = _reverseDirection(facing);
    final reversedCandidate = npcPos.moved(reversed);
    final reversedValid = _canMoveTo(
      pos: reversedCandidate,
      board: board,
      game: game,
      solidBlocking: solidBlocking,
      occupiedAfterMove: occupiedAfterMove,
      state: state,
      blockAvatar: blockAvatar,
    );

    if (reversedValid) {
      npcEntity.params['facing'] = reversed.toJson();
      return reversedCandidate;
    }

    return null;
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
