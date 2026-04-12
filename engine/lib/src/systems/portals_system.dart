import '../engine/game_system.dart';
import '../models/board.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

class PortalsSystem extends GameSystem {
  const PortalsSystem({required super.id}) : super(type: 'portals');

  // ---------------------------------------------------------------------------
  // Phase 3 — normal movement (avatar walks into portal; push resolves a normal
  // push that lands an object on a portal).
  // ---------------------------------------------------------------------------

  @override
  List<GameEvent> executeMovementResolution(
    LevelState state,
    GameDefinition game,
  ) {
    final cfg = _config(game);
    final events = <GameEvent>[];

    final avatarPos = state.avatar.position;
    if (avatarPos != null) {
      events.addAll(_tryTeleportAvatar(
        state: state,
        game: game,
        avatarPos: avatarPos,
        teleportTags: cfg.tags,
        matchKey: cfg.matchKey,
        endMovement: cfg.endMovement,
      ));
    }

    // Object teleportation is handled in executeCascadeResolution, triggered
    // by object_placed events. Never scan all portals proactively here — that
    // would undo object placements made on previous turns.

    return events;
  }

  // ---------------------------------------------------------------------------
  // Phase 5 (cascade) — avatar or object arrives at a portal cell via ice slide.
  // ---------------------------------------------------------------------------

  @override
  List<GameEvent> executeCascadeResolution(
    List<GameEvent> triggerEvents,
    LevelState state,
    GameDefinition game,
  ) {
    final cfg = _config(game);
    final events = <GameEvent>[];

    final avatarPos = state.avatar.position;
    if (avatarPos != null) {
      for (final e in triggerEvents) {
        if (e.type != 'avatar_entered') continue;

        // Only act on the event that placed Pip at her current position.
        final enteredPos = e.position;
        if (enteredPos != avatarPos) continue;

        // Bounce guard: if Pip arrived here FROM the partner portal (i.e. this
        // avatar_entered was itself emitted by a prior teleport), do not
        // teleport again — that would send her straight back.
        final fromRaw = e.payload['fromPosition'];
        final fromPos = fromRaw == null
            ? null
            : (fromRaw is Position ? fromRaw : Position.fromJson(fromRaw));

        final portal = _portalAt(state.board, avatarPos, cfg.tags, game);
        if (portal != null) {
          final channelValue = portal.entity.param(cfg.matchKey);
          if (channelValue != null) {
            final exitPos = _findExitPortal(state.board, avatarPos,
                portal.entity.kind, channelValue, cfg.matchKey);
            if (exitPos != null && fromPos == exitPos) break; // came from partner → stop
          }
        }

        events.addAll(_tryTeleportAvatar(
          state: state,
          game: game,
          avatarPos: avatarPos,
          teleportTags: cfg.tags,
          matchKey: cfg.matchKey,
          endMovement: cfg.endMovement,
        ));
        break; // only process one avatar_entered per pass
      }
    }

    // Collect object_placed positions that arrived naturally (not via teleport).
    // Teleported placements carry wasTeleported:true to break the bounce loop.
    final arrivedAtPortal = triggerEvents
        .where((e) =>
            e.type == 'object_placed' &&
            e.payload['wasTeleported'] != true)
        .map((e) => e.position)
        .whereType<Position>()
        .toSet();
    if (arrivedAtPortal.isNotEmpty) {
      events.addAll(_tryTeleportObjects(state, game, cfg, arrivedAtPortal));
    }

    return events;
  }

  // ---------------------------------------------------------------------------
  // Core teleport helpers
  // ---------------------------------------------------------------------------

  /// Teleports the avatar if they are standing on a portal.
  /// Returns [] without teleporting when the exit portal is blocked by a solid
  /// object — the caller (navigation or ice_slide) then continues the move.
  List<GameEvent> _tryTeleportAvatar({
    required LevelState state,
    required GameDefinition game,
    required Position avatarPos,
    required List<String> teleportTags,
    required String matchKey,
    required bool endMovement,
  }) {
    final board = state.board;

    // Find a portal entity at the avatar's position across all layers.
    final portal = _portalAt(board, avatarPos, teleportTags, game);
    if (portal == null) return const [];

    final channelValue = portal.entity.param(matchKey);
    if (channelValue == null) return const [];

    // Find the matching exit portal (same kind + channel, different position).
    final exitPos = _findExitPortal(
        board, avatarPos, portal.entity.kind, channelValue, matchKey);
    if (exitPos == null) return const [];

    // Blocked exit: a solid object occupies the exit cell → pass through.
    final objAtExit = board.getEntity('objects', exitPos);
    if (objAtExit != null && game.hasTag(objAtExit.kind, 'solid')) {
      return const [];
    }

    final oldPos = avatarPos;
    state.avatar = state.avatar.copyWith(position: exitPos);

    if (endMovement) {
      final facingStr = state.avatar.facing.toJson();
      return [
        GameEvent.avatarExited(oldPos),
        GameEvent.avatarEntered(exitPos, oldPos, facingStr),
      ];
    }
    return const [];
  }

  /// Teleports any object in the objects layer that is sitting on a portal.
  /// [onlyAtPositions] — when non-null, only checks portals at those positions
  /// (used in cascade to avoid re-scanning unrelated portals).
  /// Skips if the exit cell is occupied (any object, not just solid).
  List<GameEvent> _tryTeleportObjects(
    LevelState state,
    GameDefinition game,
    _PortalConfig cfg,
    Set<Position>? onlyAtPositions,
  ) {
    final board = state.board;
    final objectsLayer = board.layers['objects'];
    if (objectsLayer == null) return const [];

    final events = <GameEvent>[];

    for (final layerEntry in board.layers.entries) {
      if (layerEntry.key == 'objects' || layerEntry.key == 'actors') continue;
      for (final cell in layerEntry.value.entries()) {
        final portalPos = cell.key;
        if (onlyAtPositions != null && !onlyAtPositions.contains(portalPos)) continue;

        final entity = cell.value;
        if (!cfg.tags.any((t) => game.hasTag(entity.kind, t))) continue;

        final channelValue = entity.param(cfg.matchKey);
        if (channelValue == null) continue;

        final objAtPortal = objectsLayer.getAt(portalPos);
        if (objAtPortal == null) continue;

        final exitPos = _findExitPortal(
            board, portalPos, entity.kind, channelValue, cfg.matchKey);
        if (exitPos == null) continue;

        // Exit must be clear for object teleportation.
        final objAtExit = objectsLayer.getAt(exitPos);
        if (objAtExit != null) continue;

        board.setEntity('objects', portalPos, null);
        board.setEntity('objects', exitPos, objAtPortal);

        events.add(GameEvent.objectRemoved(portalPos, objAtPortal.kind));
        // wasTeleported marks this placement so the next cascade pass does not
        // immediately teleport the object back.
        events.add(GameEvent('object_placed', {
          'position': exitPos,
          'kind': objAtPortal.kind,
          'params': objAtPortal.params,
          'wasTeleported': true,
        }));
      }
    }

    return events;
  }

  // ---------------------------------------------------------------------------
  // Utilities
  // ---------------------------------------------------------------------------

  /// Returns the first portal-tagged entity at [pos] across all board layers,
  /// or null if none exists.
  _PortalHit? _portalAt(Board board, Position pos,
      List<String> teleportTags, GameDefinition game) {
    for (final layerEntry in board.layers.entries) {
      final entity = layerEntry.value.getAt(pos);
      if (entity == null) continue;
      if (teleportTags.any((t) => game.hasTag(entity.kind, t))) {
        return _PortalHit(entity, layerEntry.key);
      }
    }
    return null;
  }

  /// Finds the exit portal: same kind and channel, any position ≠ [sourcePos].
  Position? _findExitPortal(Board board, Position sourcePos, String kind,
      dynamic channelValue, String matchKey) {
    for (final layerEntry in board.layers.entries) {
      for (final entry in layerEntry.value.entries()) {
        if (entry.key == sourcePos) continue;
        final candidate = entry.value;
        if (candidate.kind != kind) continue;
        final ch = candidate.param(matchKey);
        if (ch?.toString() == channelValue.toString()) {
          return entry.key;
        }
      }
    }
    return null;
  }

  _PortalConfig _config(GameDefinition game) {
    final config = game.systemConfig(id, {});
    final tagsRaw = config['teleportTags'] as List<dynamic>? ?? ['teleport'];
    return _PortalConfig(
      tags: tagsRaw.map((t) => t.toString()).toList(),
      matchKey: config['matchKey'] as String? ?? 'channel',
      endMovement: config['endMovement'] as bool? ?? true,
      teleportObjects: config['teleportObjects'] as bool? ?? true,
    );
  }
}

class _PortalConfig {
  final List<String> tags;
  final String matchKey;
  final bool endMovement;
  final bool teleportObjects;
  const _PortalConfig(
      {required this.tags,
      required this.matchKey,
      required this.endMovement,
      required this.teleportObjects});
}

class _PortalHit {
  final EntityInstance entity;
  final String layerId;
  const _PortalHit(this.entity, this.layerId);
}
