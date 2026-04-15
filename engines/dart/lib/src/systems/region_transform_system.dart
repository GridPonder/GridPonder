import '../engine/game_system.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';
import '../models/direction.dart';
import '../models/entity.dart';

class RegionTransformSystem extends GameSystem {
  const RegionTransformSystem({required super.id})
      : super(type: 'region_transform');

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, {});

    final operationsRaw =
        config['operations'] as Map<String, dynamic>? ?? const {};

    // Find which operation matches the incoming action.
    String? matchedOpType;
    for (final opEntry in operationsRaw.entries) {
      final opDef = opEntry.value as Map<String, dynamic>?;
      if (opDef == null) continue;
      final opAction = opDef['action'] as String?;
      if (opAction == action.actionId) {
        matchedOpType = opDef['type'] as String?;
        break;
      }
    }

    if (matchedOpType == null) return const [];

    final overlay = state.overlay;
    if (overlay == null) return const [];

    final affectedLayersRaw =
        config['affectedLayers'] as List<dynamic>? ?? ['objects'];
    final affectedLayers = affectedLayersRaw.map((l) => l.toString()).toList();

    final board = state.board;
    final ox = overlay.x;
    final oy = overlay.y;
    final overlayWidth = overlay.width;
    final overlayHeight = overlay.height;

    // If blockOnVoid is enabled, abort if any overlay cell sits on void ground.
    final blockOnVoid = (config['blockOnVoid'] as bool?) ?? false;
    if (blockOnVoid) {
      for (int dy = 0; dy < overlayHeight; dy++) {
        for (int dx = 0; dx < overlayWidth; dx++) {
          if (board.isVoid(Position(ox + dx, oy + dy))) return const [];
        }
      }
    }

    final List<GameEvent> events = [];

    for (final layerId in affectedLayers) {
      final layer = board.layers[layerId];
      if (layer == null) continue;

      // Read all cells in overlay region first (atomic snapshot).
      final snapshot = <Position, EntityInstance?>{};
      for (int dy = 0; dy < overlayHeight; dy++) {
        for (int dx = 0; dx < overlayWidth; dx++) {
          final pos = Position(ox + dx, oy + dy);
          if (board.isInBounds(pos)) {
            snapshot[pos] = layer.getAt(pos);
          }
        }
      }

      // Compute the destination mapping: oldPos → newPos.
      final mapping = _computeMapping(
        matchedOpType,
        ox,
        oy,
        overlayWidth,
        overlayHeight,
        action.direction,
      );

      // Remove swap pairs that involve void ground cells — void positions
      // cannot participate in swaps, but other corners of the overlay may
      // still be swapped (e.g. void at bottom-left does not block a ↘ swap).
      mapping.removeWhere((src, dst) =>
          board.isVoid(src) || board.isVoid(dst));

      if (mapping.isEmpty) continue;

      // Read source values from snapshot and write to destination atomically.
      // Start with original values so unmapped cells are preserved.
      final newValues = <Position, EntityInstance?>{};
      for (final pos in snapshot.keys) {
        newValues[pos] = snapshot[pos];
      }
      // Apply permutation.
      for (final entry in mapping.entries) {
        final srcPos = entry.key;
        final dstPos = entry.value;
        if (snapshot.containsKey(srcPos) && newValues.containsKey(dstPos)) {
          newValues[dstPos] = snapshot[srcPos];
        }
      }

      // Write all new values to the board.
      for (final entry in newValues.entries) {
        if (board.isInBounds(entry.key)) {
          layer.setAt(entry.key, entry.value);
        }
      }
    }

    events.add(GameEvent('region_transformed', {'type': matchedOpType}));
    return events;
  }

  /// Returns a map of sourcePosition → destinationPosition for the given
  /// operation within the overlay region.
  Map<Position, Position> _computeMapping(
    String opType,
    int ox,
    int oy,
    int w,
    int h,
    Direction? direction,
  ) {
    switch (opType) {
      case 'rotate':
        return _rotateMapping(ox, oy, w, h);
      case 'flip':
        return _flipMapping(ox, oy, w, h);
      case 'diagonal_swap':
        return _diagonalSwapMapping(ox, oy, w, h, direction);
      default:
        return const {};
    }
  }

  /// Clockwise rotation mapping.
  /// General formula (overlay-local): (lx, ly) → (w-1-ly, lx)
  /// i.e. new[w-1-ly][lx] = old[ly][lx]
  /// Expressed as source → destination:
  ///   src (ox+lx, oy+ly) → dst (ox + w-1-ly, oy + lx)
  Map<Position, Position> _rotateMapping(int ox, int oy, int w, int h) {
    // Use the smaller dimension as the rotation size for non-square overlays;
    // for a square overlay size = w = h.
    final mapping = <Position, Position>{};
    for (int ly = 0; ly < h; ly++) {
      for (int lx = 0; lx < w; lx++) {
        final src = Position(ox + lx, oy + ly);
        // Clockwise: (lx, ly) → (h-1-ly, lx) in new coordinate space
        // new width becomes h, new height becomes w for non-square,
        // but for square overlays w==h so this simplifies cleanly.
        final dst = Position(ox + (h - 1 - ly), oy + lx);
        mapping[src] = dst;
      }
    }
    return mapping;
  }

  /// Horizontal flip mapping.
  /// (lx, ly) → (w-1-lx, ly)
  Map<Position, Position> _flipMapping(int ox, int oy, int w, int h) {
    final mapping = <Position, Position>{};
    for (int ly = 0; ly < h; ly++) {
      for (int lx = 0; lx < w; lx++) {
        final src = Position(ox + lx, oy + ly);
        final dst = Position(ox + (w - 1 - lx), oy + ly);
        mapping[src] = dst;
      }
    }
    return mapping;
  }

  /// Diagonal swap: swap two corners based on swipe direction.
  ///   up_left:    swap (ox+1, oy+1) ↔ (ox,   oy)
  ///   up_right:   swap (ox,   oy+1) ↔ (ox+1, oy)
  ///   down_left:  swap (ox+1, oy)   ↔ (ox,   oy+1)
  ///   down_right: swap (ox,   oy)   ↔ (ox+1, oy+1)
  Map<Position, Position> _diagonalSwapMapping(
      int ox, int oy, int w, int h, Direction? direction) {
    if (direction == null) return const {};

    Position posA;
    Position posB;

    switch (direction) {
      case Direction.upLeft:
        posA = Position(ox + 1, oy + 1); // bottom-right
        posB = Position(ox, oy);         // top-left
        break;
      case Direction.upRight:
        posA = Position(ox, oy + 1);     // bottom-left
        posB = Position(ox + 1, oy);     // top-right
        break;
      case Direction.downLeft:
        posA = Position(ox + 1, oy);     // top-right
        posB = Position(ox, oy + 1);     // bottom-left
        break;
      case Direction.downRight:
        posA = Position(ox, oy);         // top-left
        posB = Position(ox + 1, oy + 1); // bottom-right
        break;
      default:
        return const {};
    }

    return {posA: posB, posB: posA};
  }
}
