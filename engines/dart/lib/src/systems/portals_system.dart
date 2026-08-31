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

    // Actor portal check (supports individual_actors system)
    final actorLayerId = cfg.actorLayer;
    if (actorLayerId != null) {
      final actorLayer = state.board.layers[actorLayerId];
      if (actorLayer != null) {
        for (final e in triggerEvents) {
          if (e.type != 'actor_entered') continue;
          final enteredPos = e.position;
          if (enteredPos == null) continue;
          final fromRaw = e.payload['fromPosition'];
          final fromPos = fromRaw == null
              ? null
              : (fromRaw is Position ? fromRaw : Position.fromJson(fromRaw));
          final portal = _portalAt(state.board, enteredPos, cfg.tags, game);
          if (portal == null) continue;
          final channelValue = portal.entity.param(cfg.matchKey);
          if (channelValue == null) continue;
          final exitPos = _findExitPortal(
              state.board, enteredPos, portal.entity.kind, channelValue, cfg.matchKey);
          if (exitPos == null) continue;
          if (fromPos == exitPos) continue; // bounce guard
          final actor = state.board.getEntity(actorLayerId, enteredPos);
          if (actor == null) continue;
          state.board.setEntity(actorLayerId, enteredPos, null);
          state.board.setEntity(actorLayerId, exitPos, actor);
          final actorPosVar = cfg.actorPositionVariable;
          if (actorPosVar != null) {
            state.variables[actorPosVar] = [exitPos.x, exitPos.y];
          }
          _clearActorTrail(state, cfg, actor.kind);
          _collectExitFood(state, game, cfg, exitPos, actor.kind);
        }
      }
    }

    // Keep portal cells free of trail tiles so they remain permanently usable.
    if (cfg.clearTrailAtPortalCells) {
      _clearTrailsAtPortalPositions(state, cfg, game);
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

  /// When an actor teleports, clear all trail tiles for that actor kind and
  /// restore the budget variable by the number of tiles cleared.
  /// After each cascade pass, erase any trail tiles that accumulated on portal
  /// cells.  This keeps portals permanently traversable even after an actor
  /// steps off an exit portal.  Budget is not restored — the move that caused
  /// the trail is already paid for.
  void _clearTrailsAtPortalPositions(
      LevelState state, _PortalConfig cfg, GameDefinition game) {
    if (cfg.trailClearing.isEmpty) return;
    for (final layerEntry in state.board.layers.entries) {
      for (final cell in layerEntry.value.entries()) {
        final entity = cell.value;
        if (!cfg.tags.any((t) => game.hasTag(entity.kind, t))) continue;
        final portalPos = cell.key;
        for (final tc in cfg.trailClearing) {
          final trailLayer = state.board.layers[tc.trailLayer];
          if (trailLayer == null) continue;
          final trailCell = trailLayer.getAt(portalPos);
          if (trailCell != null && trailCell.kind == tc.trailKind) {
            trailLayer.setAt(
                portalPos,
                tc.restoreKind != null
                    ? EntityInstance(tc.restoreKind!)
                    : null);
          }
        }
      }
    }
  }

  void _clearActorTrail(LevelState state, _PortalConfig cfg, String actorKind) {
    for (final tc in cfg.trailClearing) {
      if (tc.actorKind != actorKind) continue;
      final layer = state.board.layers[tc.trailLayer];
      if (layer == null) break;
      final toRestore = <Position>[];
      for (final entry in layer.entries()) {
        if (entry.value.kind == tc.trailKind) toRestore.add(entry.key);
      }
      for (final pos in toRestore) {
        layer.setAt(pos, tc.restoreKind != null ? EntityInstance(tc.restoreKind!) : null);
      }
      if (toRestore.isNotEmpty && tc.budgetVariable != null) {
        final current = state.variables[tc.budgetVariable!];
        state.variables[tc.budgetVariable!] =
            (current is int ? current : 0) + toRestore.length;
      }
      break;
    }
  }

  /// Awards food sitting on the portal's exit cell. Teleporting relocates the
  /// actor without emitting a fresh actor_entered event for the exit cell, so
  /// eat_food_* rules never see the landing and the actor silently overlaps
  /// the food without collecting it — same class of bug as the water
  /// terrain_skip system, fixed the same way here.
  void _collectExitFood(LevelState state, GameDefinition game, _PortalConfig cfg,
      Position exitPos, String actorKind) {
    for (final foodCheck in cfg.exitFoodLayers) {
      final layerId = foodCheck['layer'] as String?;
      final foodTag = foodCheck['foodTag'] as String? ?? 'food';
      final amountPrefix = foodCheck['amountTagPrefix'] as String? ?? 'food_v';
      final budgetPrefix = foodCheck['budgetVariablePrefix'] as String? ?? 'moveBudget_';
      if (layerId == null) continue;
      final exitEntity = state.board.getEntity(layerId, exitPos);
      if (exitEntity == null) continue;
      final kindDef = game.getKind(exitEntity.kind);
      final entityTags = kindDef?.tags ?? <String>[];
      if (!entityTags.contains(foodTag)) continue;
      int? amount;
      for (final t in entityTags) {
        if (t.startsWith(amountPrefix)) {
          final parsed = int.tryParse(t.substring(amountPrefix.length));
          if (parsed != null) {
            amount = parsed;
            break;
          }
        }
      }
      if (amount == null) continue;
      final segments = actorKind.split('_');
      final color = segments.isNotEmpty ? segments.last : actorKind;
      final budgetVar = '$budgetPrefix$color';
      final current = state.variables[budgetVar];
      state.variables[budgetVar] = (current is int ? current : 0) + amount;
      state.board.setEntity(layerId, exitPos, null);
      break;
    }
  }

  _PortalConfig _config(GameDefinition game) {
    final config = game.systemConfig(id, {});
    final tagsRaw = config['teleportTags'] as List<dynamic>? ?? ['teleport'];
    final trailClearingRaw = config['trailClearing'] as List<dynamic>? ?? [];
    final exitFoodRaw = config['exitFoodLayers'] as List<dynamic>? ?? [];
    return _PortalConfig(
      tags: tagsRaw.map((t) => t.toString()).toList(),
      matchKey: config['matchKey'] as String? ?? 'channel',
      endMovement: config['endMovement'] as bool? ?? true,
      teleportObjects: config['teleportObjects'] as bool? ?? true,
      clearTrailAtPortalCells:
          config['clearTrailAtPortalCells'] as bool? ?? false,
      actorLayer: config['actorLayer'] as String?,
      actorPositionVariable: config['actorPositionVariable'] as String?,
      trailClearing: trailClearingRaw.map((e) {
        final m = e as Map<String, dynamic>;
        return _TrailClearConfig(
          actorKind: m['actorKind'] as String,
          trailLayer: m['trailLayer'] as String,
          trailKind: m['trailKind'] as String,
          restoreKind: m['restoreKind'] as String?,
          budgetVariable: m['budgetVariable'] as String?,
        );
      }).toList(),
      exitFoodLayers: exitFoodRaw.cast<Map<String, dynamic>>().toList(),
    );
  }
}

class _PortalConfig {
  final List<String> tags;
  final String matchKey;
  final bool endMovement;
  final bool teleportObjects;
  final bool clearTrailAtPortalCells;
  final String? actorLayer;
  final String? actorPositionVariable;
  final List<_TrailClearConfig> trailClearing;
  final List<Map<String, dynamic>> exitFoodLayers;
  const _PortalConfig(
      {required this.tags,
      required this.matchKey,
      required this.endMovement,
      required this.teleportObjects,
      this.clearTrailAtPortalCells = false,
      this.actorLayer,
      this.actorPositionVariable,
      this.trailClearing = const [],
      this.exitFoodLayers = const []});
}

class _TrailClearConfig {
  final String actorKind;
  final String trailLayer;
  final String trailKind;
  final String? restoreKind;
  final String? budgetVariable;
  const _TrailClearConfig({
    required this.actorKind,
    required this.trailLayer,
    required this.trailKind,
    this.restoreKind,
    this.budgetVariable,
  });
}

class _PortalHit {
  final EntityInstance entity;
  final String layerId;
  const _PortalHit(this.entity, this.layerId);
}