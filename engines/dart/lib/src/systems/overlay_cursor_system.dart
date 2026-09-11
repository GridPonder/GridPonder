import '../engine/game_system.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/entity.dart';
import '../models/game_state.dart';
import '../models/position.dart';

class OverlayCursorSystem extends GameSystem {
  const OverlayCursorSystem({required super.id})
      : super(type: 'overlay_cursor');

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, {});

    final moveAction = config['moveAction'] as String? ?? 'move';
    if (action.actionId != moveAction) return const [];

    final direction = action.direction;
    if (direction == null) return const [];
    if (!direction.isCardinal) return const [];

    final overlay = state.overlay;
    if (overlay == null) return const [];

    final sizeRaw = config['size'] as List<dynamic>? ?? [2, 2];
    final overlayWidth = sizeRaw.isNotEmpty ? (sizeRaw[0] as int? ?? 2) : 2;
    final overlayHeight = sizeRaw.length > 1 ? (sizeRaw[1] as int? ?? 2) : 2;

    final anchorToAvatar = config['anchorToAvatar'] as bool? ?? false;
    final boundsConstrained = config['boundsConstrained'] as bool? ?? true;

    final board = state.board;

    if (anchorToAvatar) {
      // The avatar_navigation system will update the avatar's position.
      // The overlay tracks the avatar automatically — we only emit the event
      // so downstream systems know the overlay has moved.
      final avatarPos = state.avatar.position;
      final newX = avatarPos?.x ?? overlay.x;
      final newY = avatarPos?.y ?? overlay.y;
      return [GameEvent.overlayMoved([newX, newY])];
    }

    // Compute new position by applying direction offset.
    final offset = direction.offset;
    int newX = overlay.x + offset.x;
    int newY = overlay.y + offset.y;

    if (boundsConstrained) {
      newX = newX.clamp(0, board.width - overlayWidth);
      newY = newY.clamp(0, board.height - overlayHeight);
    }

    if (newX != overlay.x || newY != overlay.y) {
      _carry(state, config, overlay, newX, newY);
    }
    state.overlay = overlay.copyWith(x: newX, y: newY);
    return [GameEvent.overlayMoved([newX, newY])];
  }

  /// Translates every entity inside the old footprint on each `carryLayers`
  /// layer by the overlay's displacement, so the cursor can hold things.
  void _carry(
    LevelState state,
    Map<String, dynamic> config,
    OverlayCursor overlay,
    int newX,
    int newY,
  ) {
    final carryLayers = (config['carryLayers'] as List<dynamic>? ?? const [])
        .map((l) => l.toString());
    for (final layerId in carryLayers) {
      final layer = state.board.layers[layerId];
      if (layer == null) continue;
      final held = <(int, int, EntityInstance)>[];
      for (int dy = 0; dy < overlay.height; dy++) {
        for (int dx = 0; dx < overlay.width; dx++) {
          final pos = Position(overlay.x + dx, overlay.y + dy);
          final entity = layer.getAt(pos);
          if (entity == null) continue;
          held.add((dx, dy, entity));
          layer.setAt(pos, null);
        }
      }
      for (final (dx, dy, entity) in held) {
        layer.setAt(Position(newX + dx, newY + dy), entity);
      }
    }
  }
}
