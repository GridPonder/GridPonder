import '../engine/game_system.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

class PortalsSystem extends GameSystem {
  const PortalsSystem({required super.id}) : super(type: 'portals');

  @override
  List<GameEvent> executeMovementResolution(
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, {});

    final teleportTagsRaw =
        config['teleportTags'] as List<dynamic>? ?? ['teleport'];
    final teleportTags = teleportTagsRaw.map((t) => t.toString()).toList();

    final matchKey = config['matchKey'] as String? ?? 'channel';
    final endMovement = config['endMovement'] as bool? ?? true;
    final teleportObjects = config['teleportObjects'] as bool? ?? false;

    final events = <GameEvent>[];

    final avatar = state.avatar;
    final avatarPos = avatar.position;

    if (avatarPos != null) {
      final avatarTeleportEvents = _tryTeleportAvatar(
        state: state,
        game: game,
        avatarPos: avatarPos,
        teleportTags: teleportTags,
        matchKey: matchKey,
        endMovement: endMovement,
      );
      events.addAll(avatarTeleportEvents);
    }

    if (teleportObjects) {
      final objectTeleportEvents = _tryTeleportPushedObject(
        state: state,
        game: game,
        teleportTags: teleportTags,
        matchKey: matchKey,
      );
      events.addAll(objectTeleportEvents);
    }

    return events;
  }

  List<GameEvent> _tryTeleportAvatar({
    required LevelState state,
    required GameDefinition game,
    required Position avatarPos,
    required List<String> teleportTags,
    required String matchKey,
    required bool endMovement,
  }) {
    final board = state.board;
    final objectsLayer = board.layers['objects'];
    if (objectsLayer == null) return const [];

    final entityAtAvatarPos = objectsLayer.getAt(avatarPos);
    if (entityAtAvatarPos == null) return const [];

    final hasPortalTag =
        teleportTags.any((tag) => game.hasTag(entityAtAvatarPos.kind, tag));
    if (!hasPortalTag) return const [];

    final channelValue = entityAtAvatarPos.param(matchKey);
    if (channelValue == null) return const [];

    // Find matching exit portal: same kind, same matchKey value, different position
    Position? exitPos;
    for (final entry in objectsLayer.entries()) {
      if (entry.key == avatarPos) continue;
      final candidate = entry.value;
      if (candidate.kind != entityAtAvatarPos.kind) continue;
      final candidateChannel = candidate.param(matchKey);
      if (candidateChannel == null) continue;
      if (candidateChannel.toString() == channelValue.toString()) {
        exitPos = entry.key;
        break;
      }
    }

    if (exitPos == null) return const [];

    final oldPos = avatarPos;
    state.avatar = state.avatar.copyWith(
      position: exitPos,
    );

    if (endMovement) {
      final facingStr = state.avatar.facing.toJson();
      return [
        GameEvent.avatarExited(oldPos),
        GameEvent.avatarEntered(exitPos, oldPos, facingStr),
      ];
    }

    return const [];
  }

  List<GameEvent> _tryTeleportPushedObject({
    required LevelState state,
    required GameDefinition game,
    required List<String> teleportTags,
    required String matchKey,
  }) {
    // This is called after push has already resolved (pendingMove cleared).
    // We need to detect if an object was recently pushed onto a portal.
    // Since pendingMove is cleared by the push system, we check the overlay
    // or look at recently placed objects.
    // Per the spec: check if there's an object that was just pushed onto a
    // portal (from objectPushed events). Since we don't have those events here,
    // we scan the objects layer for any object sitting on a portal entity
    // that also has a teleport tag.
    final board = state.board;
    final objectsLayer = board.layers['objects'];
    if (objectsLayer == null) return const [];

    final events = <GameEvent>[];

    // Find all cells where there is an object AND also a portal (objects layer
    // would only have one entity per cell in typical usage). The portal and the
    // pushable object would be on different layers. Check if the objects layer
    // cell has a pushable entity AND a portal marker layer or check ground layer.
    // Per the design: portals are in the objects layer. A pushable object being
    // pushed onto a portal cell would occupy the same cell. This scenario would
    // typically be resolved differently (object replacing portal or layered).
    //
    // A simpler reading: after a push, the pushed object lands on pushDest.
    // If pushDest had a portal entity, the push likely failed (portal is solid
    // or not). If portals are non-solid (walkable), the push system would allow
    // placing there. We scan for objects with pushable tags that are co-located
    // with a portal-tagged entity across layers.
    //
    // Practical implementation: scan markers/ground layers for portal entities
    // and check if the objects layer at those cells has a pushable object.
    for (final layerEntry in board.layers.entries) {
      if (layerEntry.key == 'objects' || layerEntry.key == 'actors') continue;
      final layer = layerEntry.value;
      for (final cell in layer.entries()) {
        final entity = cell.value;
        final isPortal =
            teleportTags.any((tag) => game.hasTag(entity.kind, tag));
        if (!isPortal) continue;

        final portalPos = cell.key;
        final channelValue = entity.param(matchKey);
        if (channelValue == null) continue;

        final objectAtPortal = objectsLayer.getAt(portalPos);
        if (objectAtPortal == null) continue;

        // Find matching exit portal in all layers (same kind, same channel,
        // different pos)
        Position? exitPos;
        for (final otherLayerEntry in board.layers.entries) {
          if (otherLayerEntry.key == 'objects' ||
              otherLayerEntry.key == 'actors') continue;
          final otherLayer = otherLayerEntry.value;
          for (final otherCell in otherLayer.entries()) {
            if (otherCell.key == portalPos) continue;
            final otherEntity = otherCell.value;
            if (otherEntity.kind != entity.kind) continue;
            final otherChannel = otherEntity.param(matchKey);
            if (otherChannel == null) continue;
            if (otherChannel.toString() == channelValue.toString()) {
              exitPos = otherCell.key;
              break;
            }
          }
          if (exitPos != null) break;
        }

        if (exitPos == null) continue;

        // Check exit is clear
        final objectAtExit = objectsLayer.getAt(exitPos);
        if (objectAtExit != null) continue;

        // Teleport object
        board.setEntity('objects', portalPos, null);
        board.setEntity('objects', exitPos, objectAtPortal);

        events.add(GameEvent.objectRemoved(portalPos, objectAtPortal.kind));
        events.add(GameEvent.objectPlaced(
            exitPos, objectAtPortal.kind, objectAtPortal.params));
      }
    }

    return events;
  }
}
