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
/// A `splitters`-configured entity kind forks a single incoming beam into
/// several outgoing ones (entity kind -> incoming direction -> list of
/// outgoing directions), each continuing independently from that cell — so
/// one emitter can, via a single divider, ultimately reach more than one
/// target. Checked before `reflectors`, so a kind can't be both. Unlike a
/// reflector, a splitter kind occupies its whole cell physically: an
/// incoming direction absent from its map is not a pass-through, it's the
/// solid, unsplit side of the piece, so that approach is simply blocked.
/// `allTargetsHitVariable` is the splitter-era counterpart to
/// `allReflectorsUsedVariable`: 1 when every target-tagged entity on
/// `blockingLayers` was reached by some branch this turn (any source, any
/// branch), 0 if at least one wasn't — `hitVariable` alone only means
/// "something reached something," which stops distinguishing outcomes once
/// a level has more than one target.
///
/// `intersectionVariable` catches beam segments crossing each other: a cell
/// any branch (of any source) already stepped into this turn ends the next
/// branch that reaches it there, without a hit, the moment it happens —
/// takes priority over every other role at that cell, including a target.
/// Lets a level forbid overlapping beam paths the same way `hazardTags`
/// forbids touching a hazard: set the variable, pair it with a
/// `variable_threshold` `loseCondition`.
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
    // Re-validated, not just re-fetched: the entity the selection recorded
    // may have been removed or transformed into something else by another
    // system between the select and fire actions, and the cell could now
    // hold an unrelated entity that just happens to be non-null.
    final sourceTags = _stringList(cfg['sourceTags'], const ['beam_source']);
    if (entity == null || !sourceTags.any((t) => game.hasTag(entity.kind, t))) {
      return const [];
    }

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
    final intersectionVariable = cfg['intersectionVariable'] as String?;
    final pathLengthVariable = cfg['pathLengthVariable'] as String?;
    final allReflectorsUsedVariable =
        cfg['allReflectorsUsedVariable'] as String?;
    final allTargetsHitVariable = cfg['allTargetsHitVariable'] as String?;
    final pathLayer = cfg['pathLayer'] as String? ?? 'markers';
    final pathKind = cfg['pathKind'] as String?;
    final segmentKindHorizontal = cfg['segmentKindHorizontal'] as String?;
    final segmentKindVertical = cfg['segmentKindVertical'] as String?;
    final reflectorGlowKinds = _reflectorMap(cfg['reflectorGlowKinds']);
    final reflectorDualGlowKinds = _stringMap(cfg['reflectorDualGlowKinds']);
    final splitterGlowKinds = _reflectorMap(cfg['splitterGlowKinds']);
    final splitterBlockedKinds = _reflectorMap(cfg['splitterBlockedKinds']);
    final splitterIntersectionKinds =
        _stringMap(cfg['splitterIntersectionKinds']);
    final blockedKinds = _stringMap(cfg['blockedKinds']);
    final hitTargetKind = cfg['hitTargetKind'] as String?;
    final hazardKind = cfg['hazardKind'] as String?;
    final intersectionKind = cfg['intersectionKind'] as String?;
    final intersectionGlowKind = cfg['intersectionGlowKind'] as String?;
    final maxSteps = (cfg['maxSteps'] as num?)?.toInt() ?? 200;

    // Every kind any cell could be marked with this turn — a superset used to
    // clear last turn's trace regardless of which specific kind a cell had.
    final allMarkerKinds = <String>{
      if (pathKind != null) pathKind,
      if (segmentKindHorizontal != null) segmentKindHorizontal,
      if (segmentKindVertical != null) segmentKindVertical,
      if (hitTargetKind != null) hitTargetKind,
      if (hazardKind != null) hazardKind,
      if (intersectionKind != null) intersectionKind,
      if (intersectionGlowKind != null) intersectionGlowKind,
      ...reflectorGlowKinds.values.expand((m) => m.values),
      ...reflectorDualGlowKinds.values,
      ...splitterGlowKinds.values.expand((m) => m.values),
      ...splitterBlockedKinds.values.expand((m) => m.values),
      ...splitterIntersectionKinds.values,
      ...blockedKinds.values,
    };
    // Snapshotted before the clear below wipes it: painting compares each
    // cell's intended kind against what it showed *entering* this turn, not
    // the just-cleared board, so a cell repainted with the exact same kind
    // it already had is recognized as unchanged and — unlike the board
    // write itself, which always happens so the state stays correct even
    // when nothing observable follows from it — skips emitting
    // `beam_cell_revealed`/`beam_traced` for it. Without this, a source
    // whose retrace hasn't changed at all this turn (nothing moved, nothing
    // was placed on its path) would still report itself as if it had,
    // purely because the trace unconditionally reruns every turn — and a
    // turn whose only *other* event is `actor_selected` would then wrongly
    // read as a real move.
    final priorMarkerKindAt = <Position, String>{};
    if (allMarkerKinds.isNotEmpty) {
      final layer = state.board.layers[pathLayer];
      if (layer != null) {
        for (final entry in layer.entries().toList()) {
          if (allMarkerKinds.contains(entry.value.kind)) {
            priorMarkerKindAt[entry.key] = entry.value.kind;
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
    var anyIntersect = false;
    // Summed rather than "first hit's length" so a future multi-source game
    // reads naturally as "total beam material spent" — a per-source budget
    // reduces to plain path length when there is exactly one source.
    var totalHitLength = 0;
    final visitedCells = <Position>{};
    final hitTargetPositions = <Position>{};
    // Every cell any source's beam has stepped into so far this turn —
    // shared across sources and branches, so a later one crossing an
    // earlier one's path (or its own, after looping back) is detected
    // regardless of which source or branch got there first.
    final beamCellsThisTurn = <Position>{};
    // Which diagonal channel(s) of a reflector cell have already carried a
    // beam this turn — see `_reflectorChannelKey`. Shared the same way as
    // `beamCellsThisTurn`, keyed by position since a reflector only ever has
    // two possible channels regardless of which cell it sits on.
    final reflectorChannelsThisTurn = <Position, Set<String>>{};

    // Traced first, painted second: painting needs to know every position
    // that ends up hosting a collision *before* it decides how to mark the
    // plain segment cell that a later branch crashes into — see
    // `intersectionGlowKind` below. A single combined pass can't know that
    // in time, since the colliding branch is traced after the branch it
    // hits.
    final sourceBranches = <MapEntry<Position, List<_BeamTrace>>>[];
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
      // A source's facing is only ever fired cardinally (see _handleFire's
      // own isCardinal check), but a level can also author it directly in
      // the initial board state, bypassing that check entirely — so it
      // must be re-validated here too, matching Python's is_cardinal guard
      // in this same loop.
      if (!direction.isCardinal) continue;

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
        beamCellsThisTurn,
        reflectorChannelsThisTurn,
        maxSteps,
      );
      sourceBranches.add(MapEntry(entry.key, branches));
    }

    // Every position where some branch ended in an 'intersection' this turn
    // — i.e. a real collision, not just any revisited cell (a reflector's
    // legitimate second-channel visit never adds a role='intersection'
    // cell). Used below to retroactively mark the *original* segment a
    // later branch crashed into, so the plain path it once was reads as
    // "this got crossed" even at the cell before the crash.
    final intersectionPositions = <Position>{
      for (final entry in sourceBranches)
        for (final trace in entry.value)
          for (final cell in trace.cells)
            if (cell.role == 'intersection') cell.position,
    };

    for (final entry in sourceBranches) {
      for (final trace in entry.value) {
        // Whether any cell of this branch actually differs from how it
        // showed entering this turn — gates `beam_traced` below the same
        // way each cell's own diff gates its `beam_cell_revealed`.
        var branchChanged = false;
        for (final cell in trace.cells) {
          final kind = _markerKindFor(
            cell,
            pathKind,
            segmentKindHorizontal,
            segmentKindVertical,
            reflectorGlowKinds,
            reflectorDualGlowKinds,
            splitters,
            splitterGlowKinds,
            splitterBlockedKinds,
            splitterIntersectionKinds,
            blockedKinds,
            hitTargetKind,
            hazardKind,
            intersectionKind,
            intersectionGlowKind,
            intersectionPositions,
          );
          if (kind != null) {
            state.board
                .setEntity(pathLayer, cell.position, EntityInstance(kind));
            if (priorMarkerKindAt[cell.position] != kind) {
              branchChanged = true;
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
        if (trace.cells.any((c) => c.role == 'intersection')) {
          anyIntersect = true;
        }
        if (branchChanged) {
          events.add(GameEvent('beam_traced', {
            'position': entry.key,
            'path': trace.path.map((p) => p.toJson()).toList(),
            'hit': trace.hit,
          }));
        }
      }
    }

    if (hitVariable != null) {
      state.variables[hitVariable] = anyHit ? 1 : 0;
    }
    if (hazardVariable != null) {
      state.variables[hazardVariable] = anyHazard ? 1 : 0;
    }
    if (intersectionVariable != null) {
      state.variables[intersectionVariable] = anyIntersect ? 1 : 0;
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
    Set<Position> beamCellsThisTurn,
    Map<Position, Set<String>> reflectorChannelsThisTurn,
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
        beamCellsThisTurn,
        reflectorChannelsThisTurn,
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
    Set<Position> beamCellsThisTurn,
    Map<Position, Set<String>> reflectorChannelsThisTurn,
    int maxSteps,
  ) {
    var direction = initialDirection;
    var pos = source;
    final cells = List<_PathCell>.from(prefix);

    for (var step = 0; step < maxSteps; step++) {
      final incoming = direction;
      pos = pos.moved(direction);
      if (!state.board.isInBounds(pos)) break;

      // Peeked ahead of the full role lookup below because a reflector cell
      // needs to know this *before* deciding whether stepping here is a
      // self-intersection — see `_reflectorChannelKey`. The entity kind
      // itself is kept alongside it so an intersection landing here can be
      // painted with a piece-specific marker (see `splitterIntersectionKinds`)
      // instead of the generic one.
      Map<String, String>? reflectorMapHere;
      String? entityKindHere;
      for (final layerId in blockingLayers) {
        final e = state.board.getEntity(layerId, pos);
        if (e == null) continue;
        reflectorMapHere = reflectors[e.kind];
        entityKindHere = e.kind;
        break;
      }

      // `Set.add` both checks and records in one step: false means [pos] was
      // already part of some beam segment traced this turn — this source's
      // own path looping back, an earlier branch of the same split, or a
      // different source's beam entirely. Takes priority over every other
      // role: crossing an existing beam ends the branch regardless of what
      // else is at that cell. A reflector is the one exception: its two
      // diagonal channels occupy different, non-overlapping halves of the
      // cell, so a second pass through the *other* channel isn't a real
      // overlap — only a repeat of the same channel is.
      var dualChannelVisit = false;
      if (!beamCellsThisTurn.add(pos)) {
        final channelKey = reflectorMapHere == null
            ? null
            : _reflectorChannelKey(reflectorMapHere, direction);
        final usedChannels =
            reflectorChannelsThisTurn.putIfAbsent(pos, () => <String>{});
        if (channelKey != null && usedChannels.add(channelKey)) {
          dualChannelVisit = true;
        } else {
          cells.add(_PathCell(pos, incoming, 'intersection', entityKindHere));
          break;
        }
      } else if (reflectorMapHere != null) {
        final channelKey = _reflectorChannelKey(reflectorMapHere, direction);
        if (channelKey != null) {
          reflectorChannelsThisTurn
              .putIfAbsent(pos, () => <String>{})
              .add(channelKey);
        }
      }

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
          entityKind = cellEntity.kind;
          // A splitter kind occupies its whole cell physically — an
          // incoming direction with no mapped split isn't a pass-through,
          // it's the solid, unsplit side of the piece. Only a direction
          // explicitly mapped in `splitters` divides the beam; every other
          // approach is simply blocked, never reflected or continued.
          if (splitTo == null || splitTo.isEmpty) {
            blocked = true;
            role = 'blocked';
          } else {
            role = 'splitter';
          }
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

      cells.add(_PathCell(pos, incoming, role, entityKind,
          dualChannel: dualChannelVisit));
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
              beamCellsThisTurn,
              reflectorChannelsThisTurn,
              maxSteps,
            ),
        ];
      }
      if (reflectTo != null) {
        try {
          final next = Direction.fromJson(reflectTo);
          // A reflector map is only ever documented and traced in cardinal
          // directions; `Direction` itself is the shared 8-directional model
          // other systems use diagonally, so parsing alone would silently
          // accept a diagonal redirect here instead of rejecting it like the
          // Python engine does.
          if (!next.isCardinal) break;
          direction = next;
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
    Set<Position> beamCellsThisTurn,
    Map<Position, Set<String>> reflectorChannelsThisTurn,
    int maxSteps,
  ) {
    Direction direction;
    try {
      direction = Direction.fromJson(dirStr);
    } catch (_) {
      return [_BeamTrace(prefix, false)];
    }
    // A splitter map is only ever documented and traced in cardinal
    // directions, matching the Python engine's `is_cardinal` check — a
    // diagonal entry dead-ends that one branch right at the splitter cell
    // rather than silently sending it off at an angle.
    if (!direction.isCardinal) return [_BeamTrace(prefix, false)];
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
      beamCellsThisTurn,
      reflectorChannelsThisTurn,
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
  /// An intersection cell (the beam crossed an already-traced beam segment)
  /// behaves like the hazard exception too, for the same reason: the run
  /// ends there, so `intersectionKind` (usually unset) is all it ever shows.
  ///
  /// A plain segment cell is a special case when its position is in
  /// [intersectionPositions] — meaning *some* branch this turn ended in a
  /// collision there, even though this particular cell reached it first and
  /// safely, before the crash. `intersectionGlowKind` lets a game show that
  /// cell as a crossing point too (e.g. a plus-shaped glow) rather than a
  /// plain straight segment, so the collision reads as "these two paths
  /// crossed here" rather than one path just vanishing.
  ///
  /// A [cell] with [_PathCell.dualChannel] set prefers `reflectorDualGlowKinds`
  /// (entity kind -> marker kind, not direction-specific — both of a
  /// reflector's channels are lit, so there's no single "incoming direction"
  /// left to key by) over the ordinary per-direction glow.
  ///
  /// A splitter blocked on its unmapped side is a distinct visual case from
  /// a wall blocking the beam — it's the piece's own solid backing, not an
  /// obstacle the beam crashed into — so it prefers `splitterBlockedKinds`
  /// (entity kind -> incoming direction -> marker kind) and, unlike every
  /// other role, does *not* fall back to `blockedKinds` or `pathKind` when
  /// unset: no override configured means no marker at all. Identified via
  /// `splitters` itself (the piece's actual behavioral config), not the
  /// optional `splitterGlowKinds` visual map — a splitter kind with no glow
  /// overrides configured at all must still read as "no marker," not fall
  /// through to a generic wall-hit marker as if it weren't a splitter.
  ///
  /// An intersection cell prefers `splitterIntersectionKinds` (entity kind ->
  /// marker kind) when the collision landed on a splitter — a beam re-entering
  /// a divider it already used reads very differently from two plain segments
  /// crossing, so a game that wants that distinction can give the piece its
  /// own "this is where it went wrong" art instead of the generic
  /// `intersectionKind`. Unset falls back to `intersectionKind` like normal.
  String? _markerKindFor(
    _PathCell cell,
    String? pathKind,
    String? segmentKindHorizontal,
    String? segmentKindVertical,
    Map<String, Map<String, String>> reflectorGlowKinds,
    Map<String, String> reflectorDualGlowKinds,
    Map<String, Map<String, List<String>>> splitters,
    Map<String, Map<String, String>> splitterGlowKinds,
    Map<String, Map<String, String>> splitterBlockedKinds,
    Map<String, String> splitterIntersectionKinds,
    Map<String, String> blockedKinds,
    String? hitTargetKind,
    String? hazardKind,
    String? intersectionKind,
    String? intersectionGlowKind,
    Set<Position> intersectionPositions,
  ) {
    final dir = cell.incomingDirection.toJson();
    if (cell.role == 'reflector') {
      if (cell.dualChannel) {
        final k = reflectorDualGlowKinds[cell.entityKind];
        if (k != null) return k;
      }
      final byKind = reflectorGlowKinds[cell.entityKind];
      final k = byKind?[dir];
      if (k != null) return k;
    } else if (cell.role == 'splitter') {
      final byKind = splitterGlowKinds[cell.entityKind];
      final k = byKind?[dir];
      if (k != null) return k;
    } else if (cell.role == 'blocked') {
      if (splitters.containsKey(cell.entityKind)) {
        // This is a splitter's own solid, unmapped side, not a wall — no
        // configured marker means none at all (see doc comment above).
        return splitterBlockedKinds[cell.entityKind]?[dir];
      }
      final k = blockedKinds[dir];
      if (k != null) return k;
    } else if (cell.role == 'target') {
      if (hitTargetKind != null) return hitTargetKind;
    } else if (cell.role == 'hazard') {
      return hazardKind;
    } else if (cell.role == 'intersection') {
      final k = splitterIntersectionKinds[cell.entityKind];
      if (k != null) return k;
      return intersectionKind;
    } else if (cell.role == 'segment') {
      if (intersectionGlowKind != null &&
          intersectionPositions.contains(cell.position)) {
        return intersectionGlowKind;
      }
      final horizontal = cell.incomingDirection == Direction.left ||
          cell.incomingDirection == Direction.right;
      final k = horizontal ? segmentKindHorizontal : segmentKindVertical;
      if (k != null) return k;
    }
    return pathKind;
  }

  /// The directions a beam can enter a reflector from aren't all independent:
  /// [reflectMap] folds them into exactly two straight-line channels through
  /// the cell (e.g. a backslash's up<->right and down<->left), each running
  /// through a different, non-overlapping half of the cell. Returns a key
  /// that's identical for both directions of the same channel — [entryDir]
  /// and the opposite of `reflectMap[entryDir]` — so two visits with the same
  /// key are a genuine overlap (the same physical line), while two visits
  /// with different keys aren't. Returns null if [reflectMap] has no entry
  /// for [entryDir] (this reflector doesn't reflect that approach at all).
  String? _reflectorChannelKey(
      Map<String, String> reflectMap, Direction entryDir) {
    final exitStr = reflectMap[entryDir.toJson()];
    if (exitStr == null) return null;
    Direction exitDir;
    try {
      exitDir = Direction.fromJson(exitStr);
    } catch (_) {
      return null;
    }
    final parts = [entryDir.toJson(), exitDir.opposite.toJson()]..sort();
    return parts.join(',');
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
/// [entityKind] set for the latter three). [dualChannel] marks a reflector
/// cell reached a second time this turn through its *other* diagonal
/// channel — see the note above `_reflectorChannelKey`.
class _PathCell {
  final Position position;
  final Direction incomingDirection;
  final String role;
  final String? entityKind;
  final bool dualChannel;
  const _PathCell(
      this.position, this.incomingDirection, this.role, this.entityKind,
      {this.dualChannel = false});
}

class _BeamTrace {
  final List<_PathCell> cells;
  final bool hit;
  const _BeamTrace(this.cells, this.hit);
  List<Position> get path => cells.map((c) => c.position).toList();
}
