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

    final dirStr = action.directionStr;
    if (dirStr == null) return [GameEvent.actionVetoed()];
    final Direction dir;
    try {
      dir = Direction.fromJson(dirStr);
    } on FormatException {
      return [GameEvent.actionVetoed()];
    }

    final avatar = state.avatar;
    if (!avatar.enabled || avatar.position == null) {
      return [GameEvent.actionVetoed()];
    }

    final layerId = cfg['layer'] as String? ?? 'ground';
    final layer = state.board.layers[layerId];
    if (layer == null) return [GameEvent.actionVetoed()];

    final target = avatar.position! + dir.offset;
    if (!state.board.isInBounds(target)) return [GameEvent.actionVetoed()];

    final entity = layer.getAt(target);
    final severable = _stringList(cfg['severableTags'], const ['severable']);
    if (entity == null || !_hasAnyTag(game, entity.kind, severable)) {
      return [GameEvent.actionVetoed()];
    }

    final previousKind = entity.kind;
    layer.setAt(target, _empty(game, layerId));
    return [
      GameEvent.cellCleared(target, previousKind),
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

    bool blocked(List<Position> cells) {
      for (final c in cells) {
        final next = c + step;
        if (!board.isInBounds(next)) continue; // leaving the board never blocks
        for (final rl in restLayers) {
          final rlayer = board.layers[rl];
          if (rlayer == null) continue;
          final e = rlayer.getAt(next);
          if (e != null && _hasAnyTag(game, e.kind, restTags)) return true;
        }
      }
      return false;
    }

    // 4. Step every unfrozen component one cell at a time until none move.
    final positions =
        components.map((comp) => List<Position>.from(comp)).toList();
    final frozen = <int>{};
    final maxSteps = board.width + board.height + 1;
    for (var pass = 0; pass < maxSteps; pass++) {
      var movedAny = false;
      for (var idx = 0; idx < positions.length; idx++) {
        if (frozen.contains(idx)) continue;
        final cells = positions[idx];
        if (!cells.any(board.isInBounds)) {
          frozen.add(idx);
          continue;
        }
        if (blocked(cells)) {
          frozen.add(idx);
          continue;
        }
        positions[idx] = cells.map((c) => c + step).toList();
        movedAny = true;
      }
      if (!movedAny) break;
    }

    // 5. Write the landed cells back, applying settleTransform.
    final settleRaw = cfg['settleTransform'] as Map? ?? const {};
    final settle =
        settleRaw.map((k, v) => MapEntry(k.toString(), v.toString()));
    final events = <GameEvent>[];
    final avatarPos = state.avatar.enabled ? state.avatar.position : null;
    int? avatarComponent;
    Position? avatarDestination;

    for (var idx = 0; idx < components.length; idx++) {
      final comp = components[idx];
      final landed = positions[idx];
      for (var i = 0; i < comp.length; i++) {
        final src = comp[i];
        final dst = landed[i];
        if (avatarPos != null && src == avatarPos) {
          avatarComponent = idx;
          avatarDestination = dst;
        }
        if (!board.isInBounds(dst)) continue; // this cell left the world
        final entity = kinds[idx][src];
        if (entity == null) continue;
        final newKind = settle[entity.kind] ?? entity.kind;
        layer.setAt(dst, entity.copyWith(kind: newKind));
        events.add(GameEvent.objectSettled(newKind, dst, src));
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
