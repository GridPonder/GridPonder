import 'dart:collection';

import '../engine/game_system.dart';
import '../models/direction.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// Cells that lose their connection to a support root fall as rigid bodies.
///
/// A structure is held up by cells tagged as roots. After any cell is removed,
/// every maximal group of member cells that can no longer reach a root is an
/// orphan, and each orphan translates in the configured direction — keeping its
/// exact shape — until one of its cells is blocked. Components fall
/// simultaneously, one step at a time, so stacked orphans resolve
/// deterministically without an ordering rule.
///
/// Generic: any game with a structure hanging from fixed roots names its own
/// root/member tags and fall direction. The player-facing sever verb is
/// optional — omit `severAction` and drive the collapse from `triggerEvents`
/// when cells are removed by rules or other systems instead.
class SupportCollapseSystem extends GameSystem {
  final Map<String, dynamic>? config;

  const SupportCollapseSystem({required super.id, this.config})
      : super(type: 'support_collapse');

  static const _cardinals = <Position>[
    Position(0, -1),
    Position(0, 1),
    Position(-1, 0),
    Position(1, 0),
  ];

  static const _diagonals = <Position>[
    ..._cardinals,
    Position(-1, -1),
    Position(1, -1),
    Position(-1, 1),
    Position(1, 1),
  ];

  Map<String, dynamic> _cfg(GameDefinition game) =>
      config ?? game.systemConfig(id, {});

  List<String> _stringList(dynamic raw, List<String> fallback) {
    if (raw is! List) return fallback;
    return raw.map((value) => value.toString()).toList();
  }

  /// The kind an emptied cell reverts to on an `exactly_one` layer.
  String? _defaultKind(GameDefinition game, String layerId) {
    for (final layer in game.layers) {
      if (layer.id != layerId) continue;
      if (layer.isExactlyOne) return layer.defaultKind ?? 'empty';
      return null;
    }
    return null;
  }

  EntityInstance? _empty(GameDefinition game, String layerId) {
    final kind = _defaultKind(game, layerId);
    return kind == null ? null : EntityInstance(kind);
  }

  bool _hasAnyTag(GameDefinition game, String kind, List<String> tags) {
    final def = game.entityKinds[kind];
    if (def == null) return false;
    for (final tag in tags) {
      if (def.hasTag(tag)) return true;
    }
    return false;
  }

  // ── phase 2: the sever verb ───────────────────────────────────────────────
  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final cfg = _cfg(game);
    final severAction = cfg['severAction'] as String?;
    if (severAction == null || action.actionId != severAction) return const [];

    final avatar = state.avatar;
    if (!avatar.enabled || avatar.position == null) {
      return [GameEvent.actionVetoed()];
    }

    final layerId = cfg['layer'] as String? ?? 'ground';
    final layer = state.board.layers[layerId];
    if (layer == null) return [GameEvent.actionVetoed()];

    // The target may be named either way, so a pack can bind the verb to a
    // directional swipe or to tapping the cell itself. Both resolve to a single
    // cell adjacent to the actor.
    final Position target;
    final rawPosition = action.params['position'];
    if (rawPosition != null) {
      target = Position.fromJson(rawPosition);
      final dx = (target.x - avatar.position!.x).abs();
      final dy = (target.y - avatar.position!.y).abs();
      if (dx + dy != 1) return [GameEvent.actionVetoed()]; // not adjacent
    } else {
      final dirStr = action.directionStr;
      if (dirStr == null) return [GameEvent.actionVetoed()];
      final Direction dir;
      try {
        dir = Direction.fromJson(dirStr);
      } on FormatException {
        return [GameEvent.actionVetoed()];
      }
      target = avatar.position! + dir.offset;
    }

    if (!state.board.isInBounds(target)) return [GameEvent.actionVetoed()];

    final entity = layer.getAt(target);
    final severable = _stringList(cfg['severableTags'], const ['severable']);
    if (entity == null || !_hasAnyTag(game, entity.kind, severable)) {
      return [GameEvent.actionVetoed()];
    }

    final previousKind = entity.kind;
    layer.setAt(target, _empty(game, layerId));
    return [
      GameEvent.cellCleared(target, previousKind, layer: layerId),
      ..._collapse(state, game, cfg),
    ];
  }

  // ── phase 5: event-driven collapse ────────────────────────────────────────
  @override
  List<GameEvent> executeCascadeResolution(
    List<GameEvent> triggerEvents,
    LevelState state,
    GameDefinition game,
  ) {
    final cfg = _cfg(game);
    final triggers = _stringList(cfg['triggerEvents'], const []).toSet();
    if (triggers.isEmpty) return const [];
    if (!triggerEvents.any((event) => triggers.contains(event.type))) {
      return const [];
    }
    return _collapse(state, game, cfg);
  }

  // ── the algorithm ─────────────────────────────────────────────────────────
  List<GameEvent> _collapse(
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> cfg,
  ) {
    final layerId = cfg['layer'] as String? ?? 'ground';
    final layer = state.board.layers[layerId];
    if (layer == null) return const [];
    final board = state.board;

    final rootTags = _stringList(cfg['rootTags'], const ['support_root']);
    final memberTags = _stringList(cfg['memberTags'], const ['supported']);
    final deltas = cfg['connectivity'] == 'diagonal' ? _diagonals : _cardinals;

    bool isRoot(Position pos) {
      final e = layer.getAt(pos);
      return e != null && _hasAnyTag(game, e.kind, rootTags);
    }

    bool isMember(Position pos) {
      final e = layer.getAt(pos);
      return e != null && _hasAnyTag(game, e.kind, memberTags);
    }

    // 1. BFS the supported set outward from every root.
    final supported = <Position>{};
    final queue = Queue<Position>();
    for (var y = 0; y < board.height; y++) {
      for (var x = 0; x < board.width; x++) {
        final p = Position(x, y);
        if (isRoot(p)) {
          supported.add(p);
          queue.add(p);
        }
      }
    }
    while (queue.isNotEmpty) {
      final cur = queue.removeFirst();
      for (final d in deltas) {
        final nb = cur + d;
        if (supported.contains(nb) || !board.isInBounds(nb)) continue;
        if (isMember(nb)) {
          supported.add(nb);
          queue.add(nb);
        }
      }
    }

    // 2. Group the unsupported members into maximal connected components.
    final remaining = <Position>{};
    for (var y = 0; y < board.height; y++) {
      for (var x = 0; x < board.width; x++) {
        final p = Position(x, y);
        if (isMember(p) && !supported.contains(p)) remaining.add(p);
      }
    }
    if (remaining.isEmpty) return const [];

    final components = <List<Position>>[];
    while (remaining.isNotEmpty) {
      final seed = remaining.first;
      remaining.remove(seed);
      final comp = <Position>[seed];
      final q = Queue<Position>()..add(seed);
      while (q.isNotEmpty) {
        final cur = q.removeFirst();
        for (final d in deltas) {
          final nb = cur + d;
          if (remaining.remove(nb)) {
            comp.add(nb);
            q.add(nb);
          }
        }
      }
      components.add(comp);
    }

    // 3. Lift every orphan cell off the board first, so a component is never
    //    blocked by the hole it is falling out of, nor by another orphan that
    //    is falling alongside it.
    final kinds = <Map<Position, EntityInstance>>[];
    for (final comp in components) {
      final snapshot = <Position, EntityInstance>{};
      for (final p in comp) {
        final e = layer.getAt(p);
        if (e != null) snapshot[p] = e;
      }
      kinds.add(snapshot);
      for (final p in comp) {
        layer.setAt(p, _empty(game, layerId));
      }
    }

    final fallDir = Direction.fromJson(cfg['direction'] as String? ?? 'down');
    final step = fallDir.offset;
    final restLayers = _stringList(cfg['restLayers'], [layerId]);
    final restTags = _stringList(cfg['restTags'], const ['solid']);
    final settleRaw = cfg['settleTransform'] as Map? ?? const {};
    final settle =
        settleRaw.map((k, v) => MapEntry(k.toString(), v.toString()));
    final deflectRaw = cfg['deflect'] as Map? ?? const {};
    final deflect =
        deflectRaw.map((k, v) => MapEntry(k.toString(), v.toString()));

    /// Kinds blocking a step by [d]. An empty list means the step is free.
    List<String> obstacles(List<Position> cells, Position d) {
      final out = <String>[];
      for (final c in cells) {
        final next = c + d;
        if (!board.isInBounds(next)) continue; // leaving the board never blocks
        for (final rl in restLayers) {
          final rlayer = board.layers[rl];
          if (rlayer == null) continue;
          final e = rlayer.getAt(next);
          if (e != null && _hasAnyTag(game, e.kind, restTags)) out.add(e.kind);
        }
      }
      return out;
    }

    /// The one agreed slide direction, or null if the component rests.
    ///
    /// A flat blocker holds the whole component, and ramps pulling opposite
    /// ways cancel — both fall back to resting, so the result never depends on
    /// which cell of the component is inspected first.
    Position? deflection(List<String> blocking) {
      if (deflect.isEmpty) return null;
      final directions = <String>{};
      for (final kind in blocking) {
        String? match;
        for (final entry in deflect.entries) {
          if (_hasAnyTag(game, kind, [entry.key])) {
            match = entry.value;
            break;
          }
        }
        if (match == null) return null;
        directions.add(match);
      }
      if (directions.length != 1) return null;
      return Direction.fromJson(directions.first).offset;
    }

    // 4. Resolve components one at a time, the one furthest along the fall
    //    direction first, writing each back to the board as it lands. Every
    //    component that could block another has therefore already come to rest
    //    by the time the other is resolved. Sorting is what makes this
    //    deterministic; stepping them in lockstep is not, because a lifted
    //    component is invisible to the others and they pass through it.
    int reachOf(List<Position> cells) => cells
        .map((c) => c.x * step.x + c.y * step.y)
        .reduce((a, b) => a > b ? a : b);
    int minXOf(List<Position> cells) =>
        cells.map((c) => c.x).reduce((a, b) => a < b ? a : b);
    int minYOf(List<Position> cells) =>
        cells.map((c) => c.y).reduce((a, b) => a < b ? a : b);

    final order = List<int>.generate(components.length, (i) => i)
      ..sort((a, b) {
        final byReach =
            reachOf(components[b]).compareTo(reachOf(components[a]));
        if (byReach != 0) return byReach;
        final byX = minXOf(components[a]).compareTo(minXOf(components[b]));
        if (byX != 0) return byX;
        return minYOf(components[a]).compareTo(minYOf(components[b]));
      });

    final events = <GameEvent>[];
    final avatarPos = state.avatar.enabled ? state.avatar.position : null;
    int? avatarComponent;
    Position? avatarDestination;
    final maxSteps = 2 * (board.width + board.height) + 1;

    for (final idx in order) {
      var cells = List<Position>.from(components[idx]);
      int? slidAt;
      for (var pass = 0; pass < maxSteps; pass++) {
        if (!cells.any(board.isInBounds)) break;
        final blocking = obstacles(cells, step);
        if (blocking.isEmpty) {
          cells = cells.map((c) => c + step).toList();
          continue;
        }
        final slide = deflection(blocking);
        if (slide == null) break;
        // A component may slide at most once per lane, or two facing ramps
        // would trade it back and forth forever. It must travel one cell along
        // the fall direction to earn another slide.
        final lane = step.y != 0 ? minYOf(cells) : minXOf(cells);
        if (slidAt == lane || obstacles(cells, slide).isNotEmpty) break;
        if (cells.any((c) => !board.isInBounds(c + slide))) {
          break; // sideways motion never leaves the board
        }
        cells = cells.map((c) => c + slide).toList();
        slidAt = lane;
      }

      final comp = components[idx];
      for (var i = 0; i < comp.length; i++) {
        final src = comp[i];
        final dst = cells[i];
        if (avatarPos != null && src == avatarPos) {
          avatarComponent = idx;
          avatarDestination = dst;
        }
        if (!board.isInBounds(dst)) continue; // this cell left the world
        final entity = kinds[idx][src];
        if (entity == null) continue;
        final newKind = settle[entity.kind] ?? entity.kind;
        layer.setAt(dst, entity.copyWith(kind: newKind));
        events.add(GameEvent.objectSettled(newKind, dst, src,
            layer: layerId, fromKind: entity.kind));
      }
    }

    // 6. The avatar rides its component down.
    final carryAvatar = cfg['carryAvatar'] as bool? ?? true;
    if (avatarComponent != null && carryAvatar) {
      if (avatarDestination != null && board.isInBounds(avatarDestination)) {
        state.avatar = state.avatar.copyWith(position: avatarDestination);
      }
      final variable = cfg['avatarFellVariable'] as String?;
      if (variable != null) {
        final old = state.variables[variable];
        final oldNum = old is num ? old.toInt() : 0;
        state.variables[variable] = oldNum + 1;
        events.add(GameEvent.variableChanged(variable, oldNum, oldNum + 1));
      }
    }

    return events;
  }
}
