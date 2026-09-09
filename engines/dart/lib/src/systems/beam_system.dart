import '../engine/game_system.dart';
import '../models/direction.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// BeamSystem — see docs/dsl/04_systems.md.
///
/// Lets the player tap-select a source entity, aim it with a directional
/// action, and — every turn, unconditionally, like `sonar` — traces a ray
/// from each aimed source across the board: straight through empty cells,
/// bent at cells whose kind is a key in `reflectors` (via a plain
/// incoming-direction -> outgoing-direction map, so any reflector shape a
/// game defines needs only its own map entry), stopped by a blocking-tagged
/// cell or the board edge, and stopped — with the configured hit variable
/// set — at a target-tagged cell. A `hazardTags`-tagged cell also stops the
/// trace, setting `hazardVariable` instead of `hitVariable`; pairing that
/// variable with a `variable_threshold` `loseCondition` is what turns
/// touching it into an immediate loss, so the hazard itself is just another
/// stop condition here, not a lose-condition concept of its own. The summed
/// length of every hitting
/// source's path (in cells, each source's own cell excluded) is optionally
/// published too, so a level can cap it with an `lte` `variable_threshold`
/// goal — a maximum-path-length budget that forces the shorter of several
/// otherwise-valid routes. Summing (rather than reporting only one source's
/// length) is what keeps this meaningful once a level has more than one
/// source: the budget reads as "total beam material spent," which reduces
/// to plain path length for today's single-source levels.
///
/// Whether every reflector currently on the board actually lies on a traced
/// path is optionally published as well, via `allReflectorsUsedVariable` —
/// `1` when no placed reflector sits unvisited, `0` if at least one does.
/// This is deliberately about *placement*, not budget: a `budgetVariable`
/// reaching zero only proves every reflector was placed *somewhere*, which a
/// player can satisfy by dropping the leftovers on cells the beam never
/// reaches. Checking placement against the traced path is what actually
/// forces a route that uses all of them — pair with a `gte 1`
/// `variable_threshold` goal (and, separately, budget-exhaustion goals if a
/// level also requires every reflector to have been placed at all).
///
/// The path painted on `pathLayer` can be more than a uniform `pathKind`:
/// `segmentKindHorizontal`/`segmentKindVertical` pick a marker by axis for
/// plain traversed cells, `reflectorGlowKinds` (entity kind -> incoming
/// direction -> marker kind) for cells that bent the beam, `blockedKinds`
/// (incoming direction -> marker kind) for the cell that stopped it — each
/// keyed by the direction the beam was moving when it *entered* that cell,
/// so a mirror or wall can show which side the beam is hitting it from —
/// and `hitTargetKind` for the cell that completed a hit. Any cell without a
/// matching override falls back to `pathKind`, so a game that doesn't need
/// directional art keeps working unchanged.
///
/// Selection and firing are two different actions on purpose: selection also
/// records the tapped cell as a generic "last selected position" (independent
/// of whether it held a source), so another system — e.g. `terrain_edit`'s
/// `positionVariable` — can use the same tap to target a placement.
///
/// Firing accepts either a single parameterized `fireAction` (direction
/// carried in the action's own params — e.g. a keyboard/gamepad binding) or a
/// set of fixed-direction `fireActions` (one zero-param action id per
/// direction, defaulting to `fire_up`/`fire_down`/`fire_left`/`fire_right`) —
/// the latter is what the reference app's control buttons need, since they
/// only render zero-param actions.
class BeamSystem extends GameSystem {
  final Map<String, dynamic>? config;

  const BeamSystem({required super.id, this.config}) : super(type: 'beam');

  Map<String, dynamic> _cfg(GameDefinition game) =>
      config ?? game.systemConfig(id, {});

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final cfg = _cfg(game);
    final selectAction = cfg['selectAction'] as String? ?? 'tap_cell';
    if (action.actionId == selectAction) {
      return _handleSelect(action, state, game, cfg);
    }

    // A parameterized `fireAction` (direction carried in the action's own
    // params) and a set of fixed-direction `fireActions` (one zero-param
    // action id per direction — needed because the app's control buttons
    // only render zero-param actions) are both accepted, so a game can pick
    // whichever its input platform supports.
    final fireAction = cfg['fireAction'] as String?;
    if (fireAction != null && action.actionId == fireAction) {
      final direction = action.direction?.toJson();
      if (direction != null) return _handleFire(direction, state, game, cfg);
      return const [];
    }
    final fireActions = _fireActionsMap(cfg['fireActions']);
    final mappedDirection = fireActions[action.actionId];
    if (mappedDirection != null) {
      return _handleFire(mappedDirection, state, game, cfg);
    }
    return const [];
  }

  static const Map<String, String> _defaultFireActions = {
    'fire_up': 'up',
    'fire_down': 'down',
    'fire_left': 'left',
    'fire_right': 'right',
  };

  Map<String, String> _fireActionsMap(dynamic raw) {
    if (raw is Map) {
      return raw.map((k, v) => MapEntry(k.toString(), v.toString()));
    }
    return _defaultFireActions;
  }

  List<GameEvent> _handleSelect(
    GameAction action,
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> cfg,
  ) {
    final pos = _parsePosition(action.params['position']);
    if (pos == null || !state.board.isInBounds(pos)) return const [];

    final selectedCellVar =
        cfg['selectedCellVariable'] as String? ?? 'selectedCell';
    state.variables[selectedCellVar] = pos.toJson();

    final sourceLayer = cfg['sourceLayer'] as String? ?? 'objects';
    final sourceTags = _stringList(cfg['sourceTags'], const ['beam_source']);
    final entity = state.board.getEntity(sourceLayer, pos);
    if (entity == null ||
        !sourceTags.any((t) => game.hasTag(entity.kind, t))) {
      return const [];
    }

    final selectedSourceVar =
        cfg['selectedSourceVariable'] as String? ?? 'selectedSource';
    state.variables[selectedSourceVar] = pos.toJson();
    return [
      GameEvent('actor_selected', {'position': pos, 'kind': entity.kind}),
    ];
  }

  List<GameEvent> _handleFire(
    String directionStr,
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> cfg,
  ) {
    Direction direction;
    try {
      direction = Direction.fromJson(directionStr);
    } catch (_) {
      return const [];
    }
    if (!direction.isCardinal) return const [];

    final selectedSourceVar =
        cfg['selectedSourceVariable'] as String? ?? 'selectedSource';
    final srcPos = _parsePosition(state.variables[selectedSourceVar]);
    if (srcPos == null) return const [];

    final sourceLayer = cfg['sourceLayer'] as String? ?? 'objects';
    final entity = state.board.getEntity(sourceLayer, srcPos);
    if (entity == null) return const [];

    final facingParam = cfg['facingParam'] as String? ?? 'facing';
    final newParams = Map<String, dynamic>.from(entity.params)
      ..[facingParam] = direction.toJson();
    state.board.setEntity(
        sourceLayer, srcPos, entity.copyWith(params: newParams));
    return [
      GameEvent(
          'beam_aimed', {'position': srcPos, 'direction': direction.toJson()})
    ];
  }

  @override
  List<GameEvent> executeNpcResolution(
    LevelState state,
    GameDefinition game,
  ) {
    final cfg = _cfg(game);
    final sourceLayer = cfg['sourceLayer'] as String? ?? 'objects';
    final sourceTags = _stringList(cfg['sourceTags'], const ['beam_source']);
    final facingParam = cfg['facingParam'] as String? ?? 'facing';
    final blockingLayers =
        _stringList(cfg['blockingLayers'], const ['ground']);
    final blockingTags = _stringList(cfg['blockingTags'], const ['solid']);
    final targetTags = _stringList(cfg['targetTags'], const ['goal_target']);
    final hazardTags = _stringList(cfg['hazardTags'], const []);
    final reflectors = _reflectorMap(cfg['reflectors']);
    final splitters = _splitterMap(cfg['splitters']);
    final hitVariable = cfg['hitVariable'] as String?;
    final hazardVariable = cfg['hazardVariable'] as String?;
    final pathLengthVariable = cfg['pathLengthVariable'] as String?;
    final allReflectorsUsedVariable =
        cfg['allReflectorsUsedVariable'] as String?;
    final allTargetsHitVariable = cfg['allTargetsHitVariable'] as String?;
    final pathLayer = cfg['pathLayer'] as String? ?? 'markers';
    final pathKind = cfg['pathKind'] as String?;
    final segmentKindHorizontal = cfg['segmentKindHorizontal'] as String?;
    final segmentKindVertical = cfg['segmentKindVertical'] as String?;
    final reflectorGlowKinds = _reflectorMap(cfg['reflectorGlowKinds']);
    final splitterGlowKinds = _reflectorMap(cfg['splitterGlowKinds']);
    final blockedKinds = _stringMap(cfg['blockedKinds']);
    final hitTargetKind = cfg['hitTargetKind'] as String?;
    final hazardKind = cfg['hazardKind'] as String?;
    final maxSteps = (cfg['maxSteps'] as num?)?.toInt() ?? 200;

    // Every kind any cell could be marked with this turn — a superset used to
    // clear last turn's trace regardless of which specific kind a cell had.
    final allMarkerKinds = <String>{
      if (pathKind != null) pathKind,
      if (segmentKindHorizontal != null) segmentKindHorizontal,
      if (segmentKindVertical != null) segmentKindVertical,
      if (hitTargetKind != null) hitTargetKind,
      if (hazardKind != null) hazardKind,
      ...reflectorGlowKinds.values.expand((m) => m.values),
      ...splitterGlowKinds.values.expand((m) => m.values),
      ...blockedKinds.values,
    };
    if (allMarkerKinds.isNotEmpty) {
      final layer = state.board.layers[pathLayer];
      if (layer != null) {
        for (final entry in layer.entries().toList()) {
          if (allMarkerKinds.contains(entry.value.kind)) {
            state.board.setEntity(pathLayer, entry.key, null);
          }
        }
      }
    }

    final sourceLayerObj = state.board.layers[sourceLayer];
    if (sourceLayerObj == null) return const [];

    final events = <GameEvent>[];
    var anyHit = false;
    var anyHazard = false;
    // Summed rather than "first hit's length" so a future multi-source game
    // reads naturally as "total beam material spent" — a per-source budget
    // reduces to plain path length when there is exactly one source.
    var totalHitLength = 0;
    final visitedCells = <Position>{};
    final hitTargetPositions = <Position>{};

    for (final entry in sourceLayerObj.entries().toList()) {
      if (!sourceTags.any((t) => game.hasTag(entry.value.kind, t))) continue;
      final facingStr = entry.value.param(facingParam);
      if (facingStr is! String) continue;

      Direction direction;
      try {
        direction = Direction.fromJson(facingStr);
      } catch (_) {
        continue;
      }

      // Almost always one branch; more than one only when the ray passed
      // through a `splitters` cell and forked.
      final branches = _trace(
        entry.key,
        direction,
        state,
        game,
        blockingLayers,
        blockingTags,
        targetTags,
        hazardTags,
        reflectors,
        splitters,
        maxSteps,
      );

      for (final trace in branches) {
        for (final cell in trace.cells) {
          final kind = _markerKindFor(
            cell,
            pathKind,
            segmentKindHorizontal,
            segmentKindVertical,
            reflectorGlowKinds,
            splitterGlowKinds,
            blockedKinds,
            hitTargetKind,
            hazardKind,
          );
          if (kind != null) {
            state.board
                .setEntity(pathLayer, cell.position, EntityInstance(kind));
            // Emitted in trace order (source to endpoint) purely so a
            // renderer can play the path back cell-by-cell instead of the
            // board simply appearing fully painted — the state above is
            // already final.
            events.add(GameEvent('beam_cell_revealed', {
              'position': cell.position,
              'layer': pathLayer,
              'kind': kind,
            }));
          }
        }
        visitedCells.addAll(trace.path);
        if (trace.hit) {
          anyHit = true;
          totalHitLength += trace.path.length;
          hitTargetPositions.add(trace.cells.last.position);
        }
        if (trace.cells.any((c) => c.role == 'hazard')) {
          anyHazard = true;
        }
        events.add(GameEvent('beam_traced', {
          'position': entry.key,
          'path': trace.path.map((p) => p.toJson()).toList(),
          'hit': trace.hit,
        }));
      }
    }

    if (hitVariable != null) {
      state.variables[hitVariable] = anyHit ? 1 : 0;
    }
    if (hazardVariable != null) {
      state.variables[hazardVariable] = anyHazard ? 1 : 0;
    }
    if (pathLengthVariable != null) {
      state.variables[pathLengthVariable] = totalHitLength;
    }
    if (allReflectorsUsedVariable != null) {
      var allUsed = true;
      for (final layerId in blockingLayers) {
        final layer = state.board.layers[layerId];
        if (layer == null) continue;
        for (final entry in layer.entries()) {
          if (!reflectors.containsKey(entry.value.kind) &&
              !splitters.containsKey(entry.value.kind)) {
            continue;
          }
          if (!visitedCells.contains(entry.key)) {
            allUsed = false;
            break;
          }
        }
        if (!allUsed) break;
      }
      state.variables[allReflectorsUsedVariable] = allUsed ? 1 : 0;
    }
    if (allTargetsHitVariable != null) {
      var allTargetsHit = true;
      for (final layerId in blockingLayers) {
        final layer = state.board.layers[layerId];
        if (layer == null) continue;
        for (final entry in layer.entries()) {
          if (!targetTags.any((t) => game.hasTag(entry.value.kind, t))) {
            continue;
          }
          if (!hitTargetPositions.contains(entry.key)) {
            allTargetsHit = false;
            break;
          }
        }
        if (!allTargetsHit) break;
      }
      state.variables[allTargetsHitVariable] = allTargetsHit ? 1 : 0;
    }

    return events;
  }

  /// Traces from [source] in [initialDirection], returning one [_BeamTrace]
  /// per terminal branch. Almost always a single-element list — it only grows
  /// past one when the ray passes through a `splitters`-configured cell,
  /// which forks the single incoming beam into several outgoing ones. Each
  /// returned trace carries the full path from the source, prefix included,
  /// so branches replay independently rather than sharing a partial list.
  List<_BeamTrace> _trace(
    Position source,
    Direction initialDirection,
    LevelState state,
    GameDefinition game,
    List<String> blockingLayers,
    List<String> blockingTags,
    List<String> targetTags,
    List<String> hazardTags,
    Map<String, Map<String, String>> reflectors,
    Map<String, Map<String, List<String>>> splitters,
    int maxSteps,
  ) =>
      _traceSegment(
        source,
        initialDirection,
        const [],
        state,
        game,
        blockingLayers,
        blockingTags,
        targetTags,
        hazardTags,
        reflectors,
        splitters,
        maxSteps,
      );

  List<_BeamTrace> _traceSegment(
    Position source,
    Direction initialDirection,
    List<_PathCell> prefix,
    LevelState state,
    GameDefinition game,
    List<String> blockingLayers,
    List<String> blockingTags,
    List<String> targetTags,
    List<String> hazardTags,
    Map<String, Map<String, String>> reflectors,
    Map<String, Map<String, List<String>>> splitters,
    int maxSteps,
  ) {
    var direction = initialDirection;
    var pos = source;
    final cells = List<_PathCell>.from(prefix);

    for (var step = 0; step < maxSteps; step++) {
      final incoming = direction;
      pos = pos.moved(direction);
      if (!state.board.isInBounds(pos)) break;

      String? reflectTo;
      List<String>? splitTo;
      var blocked = false;
      var hitTarget = false;
      var hitHazard = false;
      var role = 'segment';
      String? entityKind;
      for (final layerId in blockingLayers) {
        final cellEntity = state.board.getEntity(layerId, pos);
        if (cellEntity == null) continue;
        if (targetTags.any((t) => game.hasTag(cellEntity.kind, t))) {
          hitTarget = true;
          role = 'target';
          entityKind = cellEntity.kind;
          break;
        }
        if (hazardTags.any((t) => game.hasTag(cellEntity.kind, t))) {
          hitHazard = true;
          role = 'hazard';
          entityKind = cellEntity.kind;
          break;
        }
        final splitMap = splitters[cellEntity.kind];
        if (splitMap != null) {
          splitTo = splitMap[direction.toJson()];
          role = 'splitter';
          entityKind = cellEntity.kind;
          break;
        }
        final reflectMap = reflectors[cellEntity.kind];
        if (reflectMap != null) {
          reflectTo = reflectMap[direction.toJson()];
          role = 'reflector';
          entityKind = cellEntity.kind;
          break;
        }
        if (blockingTags.any((t) => game.hasTag(cellEntity.kind, t))) {
          blocked = true;
          role = 'blocked';
          entityKind = cellEntity.kind;
          break;
        }
      }

      cells.add(_PathCell(pos, incoming, role, entityKind));
      if (hitTarget) return [_BeamTrace(cells, true)];
      if (hitHazard) break;
      if (blocked) break;
      if (splitTo != null && splitTo.isNotEmpty) {
        return [
          for (final dirStr in splitTo)
            ..._traceOrDeadEnd(
              pos,
              dirStr,
              cells,
              state,
              game,
              blockingLayers,
              blockingTags,
              targetTags,
              hazardTags,
              reflectors,
              splitters,
              maxSteps,
            ),
        ];
      }
      if (reflectTo != null) {
        try {
          direction = Direction.fromJson(reflectTo);
          continue;
        } catch (_) {
          break;
        }
      }
    }

    return [_BeamTrace(cells, false)];
  }

  /// Continues one branch of a split from [pos] in [dirStr]. An unparseable
  /// direction (bad config) ends just that branch rather than the whole
  /// trace, so one malformed entry in `splitters` can't take other branches
  /// down with it.
  List<_BeamTrace> _traceOrDeadEnd(
    Position pos,
    String dirStr,
    List<_PathCell> prefix,
    LevelState state,
    GameDefinition game,
    List<String> blockingLayers,
    List<String> blockingTags,
    List<String> targetTags,
    List<String> hazardTags,
    Map<String, Map<String, String>> reflectors,
    Map<String, Map<String, List<String>>> splitters,
    int maxSteps,
  ) {
    Direction direction;
    try {
      direction = Direction.fromJson(dirStr);
    } catch (_) {
      return [_BeamTrace(prefix, false)];
    }
    return _traceSegment(
      pos,
      direction,
      prefix,
      state,
      game,
      blockingLayers,
      blockingTags,
      targetTags,
      hazardTags,
      reflectors,
      splitters,
      maxSteps,
    );
  }

  /// Resolves which marker kind (if any) to paint at [cell]. Reflector and
  /// blocked cells prefer a kind keyed by the direction the beam was moving
  /// when it entered them (`reflectorGlowKinds`/`blockedKinds`); a plain
  /// traversed cell prefers `segmentKindHorizontal`/`segmentKindVertical`
  /// based on that same direction's axis; the target-hit cell prefers
  /// `hitTargetKind`. Anything not matched falls back to the uniform
  /// `pathKind`, and finally to no marker at all. A hazard cell is the one
  /// exception: it does *not* fall back to `pathKind`, since the run ends the
  /// instant the beam reaches it — the hazard entity's own sprite should
  /// stay exactly as it looks the rest of the time, not get redecorated with
  /// a beam-path marker a player has no time to appreciate before losing.
  /// `hazardKind` lets a game opt into one anyway (e.g. an explosion sprite).
  String? _markerKindFor(
    _PathCell cell,
    String? pathKind,
    String? segmentKindHorizontal,
    String? segmentKindVertical,
    Map<String, Map<String, String>> reflectorGlowKinds,
    Map<String, Map<String, String>> splitterGlowKinds,
    Map<String, String> blockedKinds,
    String? hitTargetKind,
    String? hazardKind,
  ) {
    final dir = cell.incomingDirection.toJson();
    if (cell.role == 'reflector') {
      final byKind = reflectorGlowKinds[cell.entityKind];
      final k = byKind?[dir];
      if (k != null) return k;
    } else if (cell.role == 'splitter') {
      final byKind = splitterGlowKinds[cell.entityKind];
      final k = byKind?[dir];
      if (k != null) return k;
    } else if (cell.role == 'blocked') {
      final k = blockedKinds[dir];
      if (k != null) return k;
    } else if (cell.role == 'target') {
      if (hitTargetKind != null) return hitTargetKind;
    } else if (cell.role == 'hazard') {
      return hazardKind;
    } else if (cell.role == 'segment') {
      final horizontal = cell.incomingDirection == Direction.left ||
          cell.incomingDirection == Direction.right;
      final k = horizontal ? segmentKindHorizontal : segmentKindVertical;
      if (k != null) return k;
    }
    return pathKind;
  }

  Map<String, String> _stringMap(dynamic raw) {
    if (raw is Map) {
      return raw.map((k, v) => MapEntry(k.toString(), v.toString()));
    }
    return const {};
  }

  Map<String, Map<String, String>> _reflectorMap(dynamic raw) {
    final result = <String, Map<String, String>>{};
    if (raw is Map) {
      raw.forEach((kind, dirMap) {
        if (dirMap is Map) {
          result[kind.toString()] = dirMap.map(
              (from, to) => MapEntry(from.toString(), to.toString()));
        }
      });
    }
    return result;
  }

  /// Same shape as `reflectors` but each incoming direction maps to a *list*
  /// of outgoing directions — a splitter kind absent from the map, or with no
  /// entry for the incoming direction, is not a splitter for that approach.
  Map<String, Map<String, List<String>>> _splitterMap(dynamic raw) {
    final result = <String, Map<String, List<String>>>{};
    if (raw is Map) {
      raw.forEach((kind, dirMap) {
        if (dirMap is Map) {
          result[kind.toString()] = dirMap.map((from, dirs) => MapEntry(
              from.toString(),
              dirs is List
                  ? dirs.map((d) => d.toString()).toList()
                  : const <String>[]));
        }
      });
    }
    return result;
  }

  List<String> _stringList(dynamic raw, List<String> fallback) {
    if (raw is List) return raw.map((e) => e.toString()).toList();
    return fallback;
  }

  Position? _parsePosition(dynamic raw) {
    if (raw is List && raw.length >= 2) {
      final x = raw[0];
      final y = raw[1];
      if (x is num && y is num && x.isFinite && y.isFinite) {
        return Position(x.toInt(), y.toInt());
      }
    }
    return null;
  }
}

/// One traced cell: where it is, the direction the beam was moving when it
/// entered ([incomingDirection]), and what it is ([role]: `'segment'` for a
/// plain floor cell, `'reflector'`, `'blocked'`, or `'target'`, with
/// [entityKind] set for the latter three).
class _PathCell {
  final Position position;
  final Direction incomingDirection;
  final String role;
  final String? entityKind;
  const _PathCell(
      this.position, this.incomingDirection, this.role, this.entityKind);
}

class _BeamTrace {
  final List<_PathCell> cells;
  final bool hit;
  const _BeamTrace(this.cells, this.hit);
  List<Position> get path => cells.map((c) => c.position).toList();
}
