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

    // A move clamped to where the overlay already is changes nothing. Packs
    // that count actions can refuse it, so bumping the edge costs no turn.
    final rejectNoOp = config['rejectNoOpMoves'] as bool? ?? false;
    if (rejectNoOp && newX == overlay.x && newY == overlay.y) {
      return [GameEvent.actionVetoed()];
    }

    if (newX != overlay.x || newY != overlay.y) {
      if (!_carry(state, config, overlay, newX, newY)) {
        return [GameEvent.actionVetoed()];
      }
    }
    state.overlay = overlay.copyWith(x: newX, y: newY);
    return [GameEvent.overlayMoved([newX, newY])];
  }

  /// Translates every entity inside the old footprint on each `carryLayers`
  /// layer by the overlay's displacement, so the cursor can hold things.
  ///
  /// The move is atomic: every carried entity must have an in-bounds,
  /// unoccupied destination before any layer is mutated. Cells in the old
  /// footprint are allowed destinations because their contents move in the
  /// same transaction.
  bool _carry(
    LevelState state,
    Map<String, dynamic> config,
    OverlayCursor overlay,
    int newX,
    int newY,
  ) {
    final carryLayers = (config['carryLayers'] as List<dynamic>? ?? const [])
        .map((l) => l.toString())
        .toSet();
    final moves = <(String, Position, Position, EntityInstance)>[];

    bool wasInsideOldFootprint(Position pos) =>
        pos.x >= overlay.x &&
        pos.x < overlay.x + overlay.width &&
        pos.y >= overlay.y &&
        pos.y < overlay.y + overlay.height;

    // Validate the complete move before clearing a single source cell.
    for (final layerId in carryLayers) {
      final layer = state.board.layers[layerId];
      if (layer == null) continue;
      for (int dy = 0; dy < overlay.height; dy++) {
        for (int dx = 0; dx < overlay.width; dx++) {
          final from = Position(overlay.x + dx, overlay.y + dy);
          final entity = layer.getAt(from);
          if (entity == null) continue;
          final to = Position(newX + dx, newY + dy);
          if (!state.board.isInBounds(to)) return false;
          if (!wasInsideOldFootprint(to) && layer.getAt(to) != null) {
            return false;
          }
          moves.add((layerId, from, to, entity));
        }
      }
    }

    for (final (layerId, from, _, _) in moves) {
      state.board.layers[layerId]!.setAt(from, null);
    }
    for (final (layerId, _, to, entity) in moves) {
      state.board.layers[layerId]!.setAt(to, entity);
    }
    return true;
  }
}
