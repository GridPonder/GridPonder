import '../engine/game_system.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// One body segment: a fixed appearance (assigned once, at creation) plus a
/// position that is rewritten every turn. `color` drives the templated kind
/// (`segmentKindTemplate`); `literalKind`, when set, bypasses the template
/// entirely — used only for the best-effort load-time backfill described in
/// [TrailingBodySystem]'s doc comment.
class _Segment {
  final Position position;
  final String? color;
  final String? literalKind;

  const _Segment(this.position, this.color, {this.literalKind});

  factory _Segment.fromJson(Map<String, dynamic> j) => _Segment(
        Position.fromJson(j['position']),
        j['color'] as String?,
        literalKind: j['literalKind'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'position': position.toJson(),
        if (color != null) 'color': color,
        if (literalKind != null) 'literalKind': literalKind,
      };
}

/// Makes a mover drag a body of variable length behind it, Snake-style, with
/// cells behind the tail freed as the mover advances (unlike Snake Tunnel's
/// permanent trail). See `docs/dsl/04_systems.md` §2.26 for the full spec.
///
/// Systems are re-instantiated every turn (see `SystemRegistry.instantiate`),
/// so this class holds no mutable fields of its own. Everything it needs to
/// remember between turns — the mover's position before its most recent move,
/// and the ordered list of segment (position, color) pairs — is persisted in
/// `state.variables` under keys namespaced by this system's `id`. That is the
/// "internal ordered list" the DSL doc describes; it just has to live in
/// state rather than instance memory.
///
/// Growth is detected *structurally*, not by comparing `lengthVariable`
/// across turns. This system runs in `movement_resolution` (phase 3), one
/// phase before rules run in `cascade_resolution` (phase 5) — the phase
/// where a pickup rule (Recipe A, `docs/dsl/05_rules.md`) would destroy the
/// consumed entity and increment the length variable. Reading
/// `lengthVariable` here would therefore always be one phase stale within
/// the pickup's own turn. Instead, this system checks the board directly, at
/// the mover's *new* cell, for an entity tagged `growthTriggerTag` on
/// `growthKindSource` — which is still there, since the rule that will
/// destroy it hasn't run yet. `lengthVariable` is read fresh each turn only
/// to reconcile the incidental drift case (padding/shrinking when the
/// variable and the structural trail disagree, e.g. a level that starts the
/// mover already carrying cargo) — never to detect this turn's own growth.
class TrailingBodySystem extends GameSystem {
  final Map<String, dynamic>? config;

  const TrailingBodySystem({required super.id, this.config})
      : super(type: 'trailing_body');

  Map<String, dynamic> _cfg(GameDefinition game) =>
      config ?? game.systemConfig(id, {});

  String get _prevPosKey => '_trailingBody_${id}_prevPos';
  String get _segmentsKey => '_trailingBody_${id}_segments';

  @override
  List<GameEvent> executeLoadSettle(LevelState state, GameDefinition game) {
    final cfg = _cfg(game);
    final moverPos = _resolveMoverPosition(state, game, cfg);
    if (moverPos == null) return const [];
    state.variables[_prevPosKey] = moverPos.toJson();

    final lengthVar = cfg['lengthVariable'] as String?;
    final freshL = lengthVar != null ? _readInt(state.variables[lengthVar]) : 0;
    if (freshL <= 0) {
      state.variables[_segmentsKey] = <dynamic>[];
      return const [];
    }

    // Best-effort backfill: a level that starts the mover already carrying
    // cargo has no real trail to source positions from, so every backfilled
    // segment is stacked on the mover's own starting cell using a fixed
    // `defaultSegmentKind` (not the color+shape template, since there is no
    // growth event to source a color from). Documented limitation — Hitch
    // never uses this path, since the truck always starts empty.
    final defaultKind = cfg['defaultSegmentKind'] as String?;
    final segments = <_Segment>[];
    if (defaultKind != null) {
      for (var i = 0; i < freshL; i++) {
        segments.add(_Segment(moverPos, null, literalKind: defaultKind));
      }
      final bodyLayer = cfg['bodyLayer'] as String? ?? 'tail';
      for (final seg in segments) {
        state.board.setEntity(
            bodyLayer, seg.position, EntityInstance(seg.literalKind!));
      }
    }
    state.variables[_segmentsKey] = segments.map((s) => s.toJson()).toList();
    return const [];
  }

  @override
  List<GameEvent> executeMovementResolution(
    LevelState state,
    GameDefinition game,
  ) {
    final cfg = _cfg(game);
    final moverPos = _resolveMoverPosition(state, game, cfg);
    if (moverPos == null) return const [];

    final prevPosRaw = state.variables[_prevPosKey];
    final prevPos =
        prevPosRaw != null ? Position.fromJson(prevPosRaw) : moverPos;

    if (moverPos == prevPos) {
      // Mover didn't move this turn (e.g. a non-movement action, or a
      // blocked move) — the body doesn't move either.
      state.variables[_prevPosKey] = moverPos.toJson();
      return const [];
    }

    final bodyLayer = cfg['bodyLayer'] as String? ?? 'tail';
    final segmentsRaw = (state.variables[_segmentsKey] as List?) ?? const [];
    final oldSegments = segmentsRaw
        .map((e) => _Segment.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();

    // Structural growth detection — see class doc comment for why this
    // can't be "did lengthVariable increase since last turn".
    final growthLayer = cfg['growthKindSource'] as String?;
    final growthTag = cfg['growthTriggerTag'] as String? ?? 'pickup';
    final colorParam = cfg['growthColorParam'] as String? ?? 'color';
    EntityInstance? growthEntity;
    if (growthLayer != null) {
      final candidate = state.board.getEntity(growthLayer, moverPos);
      if (candidate != null && game.hasTag(candidate.kind, growthTag)) {
        growthEntity = candidate;
      }
    }
    final isGrowth = growthEntity != null;

    // Positions always shift: prepend the cell the mover just left, and keep
    // every old position at its own index — the body doesn't slide on a
    // growth turn, so nothing is dropped; on an ordinary turn, the last
    // (farthest) position falls off the end.
    final oldPositions = oldSegments.map((s) => s.position).toList();
    final targetLen = isGrowth ? oldSegments.length + 1 : oldSegments.length;
    var newPositions = <Position>[prevPos, ...oldPositions];
    if (newPositions.length > targetLen) {
      newPositions = newPositions.sublist(0, targetLen);
    }

    // Appearances (color/literalKind) shift independently of position: on an
    // ordinary turn each existing segment's fixed appearance moves forward
    // into the cell the segment ahead of it just vacated (a real train's
    // cars each pull into the spot the car ahead just left) — so the
    // appearance list itself is untouched, just re-paired with the new,
    // shifted position list. On a growth turn a brand new appearance is
    // appended after every existing one, the way a new car couples onto
    // the back of a train: the earliest-picked-up cargo stays closest to
    // the mover, and each later pickup joins further back.
    final appearanceSource = isGrowth
        ? <_Segment>[
            ...oldSegments,
            _Segment(
              moverPos,
              (growthEntity.param(colorParam) as String?) ?? growthEntity.kind,
            ),
          ]
        : oldSegments;
    var appearances = appearanceSource;
    if (appearances.length > targetLen) {
      appearances = appearances.sublist(0, targetLen);
    }

    final length = newPositions.length < appearances.length
        ? newPositions.length
        : appearances.length;
    final rawSegments = <_Segment>[
      for (var i = 0; i < length; i++)
        _Segment(
          newPositions[i],
          appearances[i].color,
          literalKind: appearances[i].literalKind,
        ),
    ];

    // Unloading: a segment that lands exactly on a matching-color unloader
    // tile this turn is spliced out of the chain — not freed off the tail
    // end the way the farthest segment naturally is, but removed from
    // wherever it sits, with every segment behind it pulled forward into
    // the gap so the chain stays contiguous ("Red and Blue become connected
    // directly" — see docs/dsl/04_systems.md §2.26). Opt-in via
    // `unloadLayer`; a pack that never sets it pays nothing here and
    // `rawSegments` passes through unchanged.
    //
    // `originalIndexOf[i]` tracks, for each surviving segment, its index in
    // `oldSegments` — the tile_moved loop below needs this to find each
    // segment's *own* old position, since a pulled-forward segment's slot
    // in `rawSegments` no longer matches its slot in `oldSegments` once
    // something ahead of it has been spliced out.
    final unloadLayer = cfg['unloadLayer'] as String?;
    var newSegments = rawSegments;
    var originalIndexOf = List<int>.generate(rawSegments.length, (i) => i);
    final unloadEvents = <GameEvent>[];
    if (unloadLayer != null) {
      final unloadTag = cfg['unloadTag'] as String? ?? 'unloader';
      final unloadColorParam = cfg['unloadColorParam'] as String? ?? 'color';
      final layer = state.board.layers[unloadLayer];
      final kept = <_Segment>[];
      final keptOriginalIndex = <int>[];
      for (var i = 0; i < rawSegments.length; i++) {
        final seg = rawSegments[i];
        final unloader = layer?.getAt(seg.position);
        final matches = unloader != null &&
            game.hasTag(unloader.kind, unloadTag) &&
            (unloader.param(unloadColorParam) as String?) == seg.color;
        if (matches) {
          unloadEvents.add(GameEvent('body_segment_unloaded', {
            'position': seg.position,
            'color': seg.color,
          }));
        } else {
          kept.add(seg);
          keptOriginalIndex.add(i);
        }
      }
      if (kept.length != rawSegments.length) {
        newSegments = [
          for (var k = 0; k < kept.length; k++)
            _Segment(newPositions[k], kept[k].color,
                literalKind: kept[k].literalKind),
        ];
        originalIndexOf = keptOriginalIndex;
      }
    }

    // Reconcile against lengthVariable — only when this wasn't a structural
    // growth turn. On the growth turn itself, `lengthVariable` is still the
    // pre-increment value (rules haven't run yet this turn), so comparing
    // against it here would immediately undo the growth just computed above.
    // By next turn lengthVariable has caught up and this is a no-op.
    if (!isGrowth) {
      final lengthVar = cfg['lengthVariable'] as String?;
      if (lengthVar != null) {
        final freshL = _readInt(state.variables[lengthVar]);
        if (freshL > newSegments.length) {
          final defaultKind = cfg['defaultSegmentKind'] as String?;
          if (defaultKind != null) {
            final anchor =
                newSegments.isNotEmpty ? newSegments.last.position : prevPos;
            while (newSegments.length < freshL) {
              newSegments.add(_Segment(anchor, null, literalKind: defaultKind));
              originalIndexOf.add(-1); // no history to animate from
            }
          }
        } else if (freshL < newSegments.length) {
          while (newSegments.length > freshL) {
            newSegments.removeLast();
            if (originalIndexOf.length > freshL) originalIndexOf.removeLast();
          }
        }
      }
    }

    final events = <GameEvent>[...unloadEvents];
    final oldPosSet = oldPositions.toSet();
    final newPosSet = newSegments.map((s) => s.position).toSet();
    // Walk the ordered lists (not a raw set difference) so event order is
    // deterministic and matches the Python engine's list-derived order.
    final addedSeen = <Position>{};
    final addedPositions = <Position>[];
    for (final seg in newSegments) {
      if (!oldPosSet.contains(seg.position) && addedSeen.add(seg.position)) {
        addedPositions.add(seg.position);
      }
    }
    final freedSeen = <Position>{};
    final freedPositions = <Position>[];
    for (final pos in oldPositions) {
      if (!newPosSet.contains(pos) && freedSeen.add(pos)) {
        freedPositions.add(pos);
      }
    }

    if (isGrowth) {
      events.add(GameEvent('body_grown', {
        'position': prevPos,
        'color': newSegments.isNotEmpty ? newSegments.first.color : null,
        'length': newSegments.length,
      }));
    }
    for (final pos in addedPositions) {
      final seg = newSegments.firstWhere((s) => s.position == pos);
      events.add(GameEvent('body_segment_added', {
        'position': pos,
        'color': seg.color,
      }));
    }
    for (final pos in freedPositions) {
      state.board.setEntity(bodyLayer, pos, null);
      events.add(GameEvent('body_segment_freed', {'position': pos}));
    }

    // Rewrite every current segment's entity — even one whose position
    // didn't change may need a new shape, since its neighbors moved.
    //
    // A *persisting* appearance (originalIndexOf[i] < oldSegments.length,
    // i.e. not a brand-new segment coupling on this turn, and not a
    // lengthVariable-padded placeholder) moved exactly one cell this turn —
    // from its own old position to its new one — by construction (see the
    // class doc comment), UNLESS something ahead of it in the chain was
    // spliced out by an unloader this same turn, in which case it was
    // pulled forward more than one cell to close the gap — a hop this
    // system doesn't try to animate as a slide (there is no single legal
    // one-cell path for the renderer to walk), so it is left to appear at
    // rest, same as a brand-new segment already does. Emitting `tile_moved`
    // for the ordinary case lets the renderer's generic entity-glide
    // pipeline carry these segments in lockstep with the avatar's own step
    // animation instead of snapping — the presentation layer is what
    // decides to actually play them concurrently (see play_screen.dart's
    // trailing-body handling), this system only has to describe the motion.
    final template = cfg['segmentKindTemplate'] as String? ?? 'segment';
    for (var i = 0; i < newSegments.length; i++) {
      final seg = newSegments[i];
      final inward = i == 0 ? moverPos : newSegments[i - 1].position;
      final outward =
          i == newSegments.length - 1 ? null : newSegments[i + 1].position;
      final shape = _computeShape(seg.position, inward, outward);
      final kind =
          seg.literalKind ?? _renderKind(template, seg.color ?? '', shape);
      final originalIndex = i < originalIndexOf.length ? originalIndexOf[i] : -1;
      if (originalIndex >= 0 && originalIndex < oldSegments.length) {
        final fromPos = oldSegments[originalIndex].position;
        if (fromPos != seg.position && _isAdjacent(fromPos, seg.position)) {
          events.add(GameEvent('tile_moved', {
            'position': seg.position,
            'fromPosition': fromPos,
            'kind': kind,
            'layer': bodyLayer,
          }));
        }
      }
      state.board.setEntity(bodyLayer, seg.position, EntityInstance(kind));
    }

    state.variables[_segmentsKey] = newSegments.map((s) => s.toJson()).toList();
    state.variables[_prevPosKey] = moverPos.toJson();

    return events;
  }

  bool _isAdjacent(Position a, Position b) =>
      (a.x - b.x).abs() + (a.y - b.y).abs() == 1;

  Position? _resolveMoverPosition(
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> cfg,
  ) {
    final moverTag = cfg['moverTag'] as String? ?? 'avatar';
    if (moverTag == 'avatar') {
      return state.avatar.enabled ? state.avatar.position : null;
    }
    final moverLayer = cfg['moverLayer'] as String? ?? 'objects';
    final layer = state.board.layers[moverLayer];
    if (layer == null) return null;
    for (final entry in layer.entries()) {
      if (game.hasTag(entry.value.kind, moverTag)) return entry.key;
    }
    return null;
  }

  String? _directionBetween(Position from, Position to) {
    final dx = to.x - from.x;
    final dy = to.y - from.y;
    if (dx == 0 && dy == -1) return 'up';
    if (dx == 0 && dy == 1) return 'down';
    if (dx == -1 && dy == 0) return 'left';
    if (dx == 1 && dy == 0) return 'right';
    return null;
  }

  /// Straight/corner shape token from a segment's up-to-two neighbors. Names
  /// match the six-sprite convention this system was designed against
  /// (`horizontal`/`vertical` plus the four `corner_<a>_<b>` combinations),
  /// but nothing here is game-specific — any pack can reuse these tokens or
  /// point `segmentKindTemplate` at kinds using its own names.
  String _computeShape(Position pos, Position inward, Position? outward) {
    final dirIn = _directionBetween(pos, inward);
    if (outward == null) {
      return (dirIn == 'left' || dirIn == 'right') ? 'horizontal' : 'vertical';
    }
    final dirOut = _directionBetween(pos, outward);
    if (dirIn == null || dirOut == null) return 'horizontal';
    final pair = {dirIn, dirOut};
    if (pair.containsAll(['up', 'down'])) return 'vertical';
    if (pair.containsAll(['left', 'right'])) return 'horizontal';
    if (pair.containsAll(['up', 'right'])) return 'corner_up_right';
    if (pair.containsAll(['right', 'down'])) return 'corner_right_down';
    if (pair.containsAll(['down', 'left'])) return 'corner_down_left';
    if (pair.containsAll(['left', 'up'])) return 'corner_left_up';
    return 'horizontal';
  }

  String _renderKind(String template, String color, String shape) =>
      template.replaceAll('{color}', color).replaceAll('{shape}', shape);

  int _readInt(dynamic value) {
    if (value is int) return value;
    if (value is num) return value.toInt();
    return 0;
  }
}
