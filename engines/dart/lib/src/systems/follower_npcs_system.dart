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

    final behaviorsConfig = config['behaviors'] as Map<String, dynamic>? ?? {};

    final contactVariable = config['contactVariable'] as String? ?? 'caught';

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

    // Trains resolve as units, before the singletons, so a train's members can
    // never be interleaved with another machine's claim on a cell.
    for (final train in _partitionTrains(npcEntries)) {
      if (_trainSeized(train.key, train.value, state, config)) continue;
      // Per-member frequency: a geared train's members run at their own rates.
      // The active set is those whose gate opens this beat; the rest are not
      // probed and do not step — but they still turn, in _resolveTrain,
      // because facing is train-level state.
      final active = [
        for (final m in train.value)
          if (_memberIsActive(m.value, behaviorsConfig, state)) m,
      ];
      // Every wheel off-beat: a no-op, NOT a freeze.
      if (active.isEmpty) continue;
      for (final move in _resolveTrain(
        members: train.value,
        active: active,
        behaviorsConfig: behaviorsConfig,
        state: state,
        board: board,
        game: game,
        occupiedAfterMove: occupiedAfterMove,
      )) {
        _applyNpcMove(
          npcPos: move.$1,
          nextPos: move.$3,
          npcEntity: move.$2,
          state: state,
          board: board,
          contactVariable: contactVariable,
          occupiedAfterMove: occupiedAfterMove,
          events: events,
        );
      }
    }

    for (final entry in npcEntries) {
      final npcPos = entry.key;
      final npcEntity = entry.value;

      if (_shaftOf(npcEntity) != null) continue; // resolved in the train pass

      final behaviorName = npcEntity.param('behavior')?.toString();
      if (behaviorName == null) continue;

      final behaviorDef =
          behaviorsConfig[behaviorName] as Map<String, dynamic>?;
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
      _applyNpcMove(
        npcPos: npcPos,
        nextPos: nextPos,
        npcEntity: npcEntity,
        state: state,
        board: board,
        contactVariable: contactVariable,
        occupiedAfterMove: occupiedAfterMove,
        events: events,
      );
    }

    return events;
  }

  /// Commit one NPC step: board, occupancy, npcMoved, and contact.
  ///
  /// Shared by the train pass and the per-NPC loop so both emit identical
  /// events for identical motion.
  void _applyNpcMove({
    required Position npcPos,
    required Position nextPos,
    required EntityInstance npcEntity,
    required LevelState state,
    required Board board,
    required String contactVariable,
    required Set<Position> occupiedAfterMove,
    required List<GameEvent> events,
  }) {
    final npcId = 'spirit_${npcPos.x}_${npcPos.y}';
    final caught = state.avatar.position == nextPos;

    occupiedAfterMove.remove(npcPos);
    occupiedAfterMove.add(nextPos);

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

  // -- shafts (linked machines) ---------------------------------------------

  String? _shaftOf(EntityInstance npcEntity) =>
      npcEntity.param('shaft')?.toString();

  /// True when this member's own frequency gate opens on this turn.
  ///
  /// A train may be geared, so the gate is per member rather than per train. A
  /// member whose behavior is unknown is inactive rather than fatal: load
  /// settle has already rejected that board.
  bool _memberIsActive(
    EntityInstance npcEntity,
    Map<String, dynamic> behaviorsConfig,
    LevelState state,
  ) {
    final behaviorDef = behaviorsConfig[npcEntity.param('behavior')?.toString()]
        as Map<String, dynamic>?;
    if (behaviorDef == null) return false;
    final frequency = behaviorDef['frequency'] as int? ?? 1;
    return frequency <= 1 || state.turnCount % frequency == 0;
  }

  /// Shafted NPCs grouped by shaft id, ordered by each train's first member.
  ///
  /// Board order is the order `actorsLayer.entries()` yields, which is what the
  /// per-NPC loop already uses — so a board of singletons is unaffected, and a
  /// board with trains resolves them in the order their first members appear.
  List<MapEntry<String, List<MapEntry<Position, EntityInstance>>>>
      _partitionTrains(List<MapEntry<Position, EntityInstance>> npcEntries) {
    final trains = <String, List<MapEntry<Position, EntityInstance>>>{};
    for (final entry in npcEntries) {
      final shaft = _shaftOf(entry.value);
      if (shaft == null) continue;
      trains.putIfAbsent(shaft, () => []).add(entry);
    }
    return trains.entries.toList();
  }

  /// The active members all step forward, else all reverse, else the train
  /// freezes with facings intact.
  ///
  /// Only [active] — the members whose own frequency gate opened this beat — is
  /// probed and moved. [members] is the whole train and matters for exactly one
  /// thing: a reversal flips EVERY member's facing, on-beat or not, because the
  /// shaft is rigid in direction.
  ///
  /// Probes without mutating: `facing` is written only once the all-reverse
  /// branch is known to be legal for every active member, so a train that
  /// freezes resumes its original direction the beat the obstruction leaves.
  List<(Position, EntityInstance, Position)> _resolveTrain({
    required List<MapEntry<Position, EntityInstance>> members,
    required List<MapEntry<Position, EntityInstance>> active,
    required Map<String, dynamic> behaviorsConfig,
    required LevelState state,
    required Board board,
    required GameDefinition game,
    required Set<Position> occupiedAfterMove,
  }) {
    Position? legal(
      Position pos,
      EntityInstance entity,
      Direction facing,
      Set<Position> claimed,
    ) {
      final behaviorDef = behaviorsConfig[entity.param('behavior')?.toString()]
          as Map<String, dynamic>?;
      if (behaviorDef == null) return null;
      final candidate = pos.moved(facing);
      // Two members whose tracks cross can both reach the crossing on the same
      // beat. Without `claimed` they would both be handed the cell, the second
      // write would overwrite the first, and the train would lose a member with
      // no event to say so — which then reads as a seizure, because the size
      // recorded at load no longer matches.
      if (claimed.contains(candidate)) return null;
      final ok = _canMoveTo(
        pos: candidate,
        board: board,
        game: game,
        solidBlocking: behaviorDef['solidBlocking'] as bool? ?? true,
        occupiedAfterMove: occupiedAfterMove,
        state: state,
        blockAvatar: !(behaviorDef['lethalContact'] as bool? ?? false),
      );
      return ok ? candidate : null;
    }

    /// Candidate cells for the whole active set, or null if any is stuck.
    ///
    /// Sequential, so each member's claim blocks the next. The train is
    /// all-or-nothing, so a collision between two members is simply a failed
    /// direction: it falls through to the reverse, then to a freeze.
    List<Position>? probe({required bool reversed}) {
      final claimed = <Position>{};
      final out = <Position>[];
      for (final m in active) {
        final own = _facingOf(m.value);
        final facing = reversed ? _reverseDirection(own) : own;
        final candidate = legal(m.key, m.value, facing, claimed);
        if (candidate == null) return null;
        claimed.add(candidate);
        out.add(candidate);
      }
      return out;
    }

    final forward = probe(reversed: false);
    if (forward != null) {
      return [
        for (var i = 0; i < active.length; i++)
          (active[i].key, active[i].value, forward[i]),
      ];
    }

    final reverse = probe(reversed: true);
    if (reverse != null) {
      for (final m in members) {
        // The WHOLE train turns, not just the active members.
        m.value.params['facing'] =
            _reverseDirection(_facingOf(m.value)).toJson();
      }
      return [
        for (var i = 0; i < active.length; i++)
          (active[i].key, active[i].value, reverse[i]),
      ];
    }

    return const [];
  }

  /// Every NPC on the actors layer, in board order.
  ///
  /// Shared by the turn pass and load settle so both agree on what an NPC is.
  List<MapEntry<Position, EntityInstance>> _npcEntries(
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> config,
  ) {
    final actorsLayer = state.board.layers['actors'];
    if (actorsLayer == null) return const [];
    final npcTagsRaw = config['npcTags'] as List<dynamic>? ?? ['npc'];
    final npcTags = npcTagsRaw.map((t) => t.toString()).toList();
    return [
      for (final entry in actorsLayer.entries())
        if (npcTags.any((tag) => game.hasTag(entry.value.kind, tag))) entry,
    ];
  }

  /// Record each train's size once, and reject a train that cannot work.
  ///
  /// Sizing at load is what lets seizure be a pure function of the board: the
  /// system compares live membership against a constant, so no new mutable
  /// state enters the state key and solver dedup, undo and preview are all
  /// unaffected.
  @override
  List<GameEvent> executeLoadSettle(LevelState state, GameDefinition game) {
    final config = game.systemConfig(id, {});
    final behaviorsConfig = config['behaviors'] as Map<String, dynamic>? ?? {};
    for (final train in _partitionTrains(_npcEntries(state, game, config))) {
      _validateTrain(train.key, train.value, behaviorsConfig);
      state.variables['shaft_${train.key}_size'] = train.value.length;
    }
    return const [];
  }

  void _validateTrain(
    String shaftId,
    List<MapEntry<Position, EntityInstance>> members,
    Map<String, dynamic> behaviorsConfig,
  ) {
    for (final m in members) {
      final behaviorDef = behaviorsConfig[m.value.param('behavior')?.toString()]
          as Map<String, dynamic>?;
      if (behaviorDef == null) {
        throw ArgumentError(
          "shaft '$shaftId': member at ${m.key} has no known behavior",
        );
      }
      if (behaviorDef['type'] != 'patrol') {
        throw ArgumentError(
          "shaft '$shaftId': every member must be a patrol behavior; "
          "member at ${m.key} is '${behaviorDef['type']}'",
        );
      }
      // Members MAY differ in frequency — that is the ratio shaft, and a
      // geared train is the point. What they may not do is carry a frequency
      // the modulo gate cannot read.
      final frequency = behaviorDef['frequency'] ?? 1;
      if (frequency is! int || frequency < 1) {
        throw ArgumentError(
          "shaft '$shaftId': member at ${m.key} has frequency $frequency; "
          "every member's frequency must be a positive integer",
        );
      }
    }
    // A patrol never leaves its facing axis, so its traversal line is its own
    // row or column. Two members sharing one would block each other and the
    // train would jam at t=0 with no way for the player to see why. The test
    // runs against BOTH members' axes: a horizontal member standing on a
    // vertical member's column is on that member's line even though the
    // vertical one is not on the horizontal one's row, and board order must
    // not decide which of the two gets checked.
    bool onLineOf(MapEntry<Position, EntityInstance> m, Position other) {
      final facing = _facingOf(m.value);
      final horizontal = facing == Direction.left || facing == Direction.right;
      return horizontal ? m.key.y == other.y : m.key.x == other.x;
    }

    for (var i = 0; i < members.length; i++) {
      for (var j = i + 1; j < members.length; j++) {
        final a = members[i].key;
        final b = members[j].key;
        if (onLineOf(members[i], b) || onLineOf(members[j], a)) {
          throw ArgumentError(
            "shaft '$shaftId': members at $a and $b share a traversal line",
          );
        }
      }
    }
  }

  /// A member's facing param, falling back to right when missing or unknown.
  Direction _facingOf(EntityInstance entity) {
    try {
      return Direction.fromJson(entity.param('facing')?.toString() ?? 'right');
    } catch (_) {
      return Direction.right;
    }
  }

  /// A train that has lost a member never moves again.
  ///
  /// Read strictly: only the boolean true enables seizure, matching the
  /// `cycle` precedent in coupled_actors.
  bool _trainSeized(
    String shaftId,
    List<MapEntry<Position, EntityInstance>> members,
    LevelState state,
    Map<String, dynamic> config,
  ) {
    if (config['shaftSeizeOnLoss'] != true) return false;
    final size = state.variables['shaft_${shaftId}_size'] as num?;
    return size != null && members.length < size.toInt();
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
