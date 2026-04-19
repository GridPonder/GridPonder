import '../engine/game_system.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// Toggles between placing a marker entity at the avatar's position and
/// teleporting the avatar to the marker.
///
/// First use of the configured action places [markerKind] in [markerLayer]
/// at the avatar's current cell.  A second use teleports the avatar to the
/// marker's position (unless a [blockedByTags] entity is in the objects layer
/// there) and removes the marker.  At most one marker exists at any time.
///
/// Generic enough for any "save-point recall" or "twin" mechanic — the entity
/// kind, layer, and action are all configurable so the same system type can
/// serve multiple games with different visual representations.
///
/// Config keys:
///   markerKind    (string, required)  entity kind to use as the marker.
///   markerLayer   (string, required)  layer to store the marker on.
///   action        (string, required)  action id that triggers the toggle.
///   blockedByTags (list, default: ["solid"])  tags on the objects layer that
///                 prevent teleportation to the marker cell.
class AnchorPointSystem extends GameSystem {
  const AnchorPointSystem({required super.id}) : super(type: 'anchor_point');

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, null);
    final markerKind = config['markerKind'] as String?;
    final markerLayerId = config['markerLayer'] as String?;
    final actionId = config['action'] as String?;
    if (markerKind == null || markerLayerId == null || actionId == null) {
      return const [];
    }
    if (action.actionId != actionId) return const [];

    final layer = state.board.layers[markerLayerId];
    if (layer == null) return const [];

    final avatarPos = state.avatar.position;
    if (avatarPos == null) return const [];

    // Find existing marker (there should be at most one).
    Position? markerPos;
    for (final entry in layer.entries()) {
      if (entry.value.kind == markerKind) {
        markerPos = entry.key;
        break;
      }
    }

    if (markerPos == null) {
      // Place marker at avatar's current position.
      layer.setAt(avatarPos, EntityInstance(markerKind));
      return const [];
    }

    // Attempt teleport to marker position.
    final blockedByTagsRaw =
        config['blockedByTags'] as List<dynamic>? ?? const ['solid'];
    final blockedByTags = blockedByTagsRaw.map((t) => t.toString()).toList();

    final objAtMarker = state.board.getEntity('objects', markerPos);
    if (objAtMarker != null &&
        blockedByTags.any((tag) => game.hasTag(objAtMarker.kind, tag))) {
      return const []; // destination blocked — keep marker in place
    }

    // Remove marker and move avatar.
    layer.setAt(markerPos, null);
    final fromPos = avatarPos;
    state.avatar = state.avatar.copyWith(position: markerPos);

    // Emit avatar movement events.
    // avatar_entered intentionally omits 'direction' so ice_slide does not
    // trigger a slide after the teleport.
    return [
      GameEvent.avatarExited(fromPos),
      GameEvent('avatar_entered', {
        'position': markerPos,
        'fromPosition': fromPos,
      }),
    ];
  }
}
