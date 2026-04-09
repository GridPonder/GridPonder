import '../engine/game_system.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';
import '../models/direction.dart';
import '../models/entity.dart';

class SlideMergeSystem extends GameSystem {
  const SlideMergeSystem({required super.id}) : super(type: 'slide_merge');

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, {});

    final mergeAction = config['mergeAction'] as String? ?? 'move';
    if (action.actionId != mergeAction) return const [];

    final direction = action.direction;
    if (direction == null) return const [];

    final mergeableTagsRaw =
        config['mergeableTags'] as List<dynamic>? ?? ['mergeable'];
    final mergeableTags = mergeableTagsRaw.map((t) => t.toString()).toList();

    final blockerTagsRaw =
        config['blockerTags'] as List<dynamic>? ?? ['solid'];
    final blockerTags = blockerTagsRaw.map((t) => t.toString()).toList();

    final mergePredicate =
        config['mergePredicate'] as String? ?? 'equal_value';
    final mergeResult = config['mergeResult'] as String? ?? 'sum';
    final mergeLimit = config['mergeLimit'] as int? ?? 1;
    final wrapAround = config['wrapAround'] as bool? ?? false;

    final board = state.board;
    final objectsLayer = board.layers['objects'];
    if (objectsLayer == null) return const [];

    // Collect all mergeable tiles.
    final mergeableTiles = <MapEntry<Position, EntityInstance>>[];
    for (final entry in objectsLayer.entries()) {
      final isMergeable = mergeableTags
          .any((tag) => game.hasTag(entry.value.kind, tag));
      if (isMergeable) mergeableTiles.add(entry);
    }

    if (mergeableTiles.isEmpty) return const [];

    // Sort tiles so we process from the side they are sliding toward first.
    // This prevents tiles from merging into newly merged tiles in the same pass.
    mergeableTiles.sort((a, b) {
      switch (direction) {
        case Direction.left:
          return a.key.x.compareTo(b.key.x); // leftmost first
        case Direction.right:
          return b.key.x.compareTo(a.key.x); // rightmost first
        case Direction.up:
          return a.key.y.compareTo(b.key.y); // topmost first
        case Direction.down:
          return b.key.y.compareTo(a.key.y); // bottommost first
        default:
          return 0;
      }
    });

    // Working state: map from current position to entity (tracks moves within
    // this resolution step before we commit to the board).
    final workingBoard = <Position, EntityInstance>{};
    for (final entry in mergeableTiles) {
      workingBoard[entry.key] = entry.value;
    }

    // Track which positions have already merged this action (per mergeLimit).
    // Key = destination position, value = merge count at that position.
    final mergeCounts = <Position, int>{};

    // Track results to emit events.
    final List<GameEvent> events = [];
    int movedCount = 0;

    // Helper: check board edge / void.
    bool _isBlockedByBoardOrVoid(Position pos) {
      if (!board.isInBounds(pos)) return true;
      if (board.isVoid(pos)) return true;
      return false;
    }

    // Original positions of all mergeable tiles (for real-board solid checks).
    final originalPositions = Set<Position>.from(mergeableTiles.map((e) => e.key));

    for (final entry in mergeableTiles) {
      final startPos = entry.key;
      final entity = workingBoard[startPos];
      // entity may have been consumed by an earlier merge (removed from workingBoard).
      if (entity == null) continue;

      // Step the tile through the direction until it can go no further.
      Position currentPos = startPos;
      Position nextPos = _wrapOrMove(currentPos, direction, board, wrapAround);
      bool didMerge = false;

      while (true) {
        if (_isBlockedByBoardOrVoid(nextPos)) break;

        final nextEntity = workingBoard[nextPos];
        if (nextEntity == null) {
          // Check real board for solid objects that are not mergeable tiles.
          if (!originalPositions.contains(nextPos)) {
            final realEntity = objectsLayer.getAt(nextPos);
            if (realEntity != null &&
                blockerTags.any((tag) => game.hasTag(realEntity.kind, tag))) {
              break;
            }
          }
          // Stop ON teleporter cells (ground layer entity with "teleport" tag).
          currentPos = nextPos;
          final groundAtNext = board.getEntity('ground', nextPos);
          if (groundAtNext != null &&
              game.hasTag(groundAtNext.kind, 'teleport')) break;
          nextPos = _wrapOrMove(currentPos, direction, board, wrapAround);
          continue;
        }

        // There is another tile at nextPos.
        final nextIsMergeable =
            mergeableTags.any((tag) => game.hasTag(nextEntity.kind, tag));
        if (!nextIsMergeable) {
          // Solid blocker.
          break;
        }

        // Check merge eligibility (mergeLimit enforcement).
        final mergeCount = mergeCounts[nextPos] ?? 0;
        final currentMergeCount = mergeCounts[currentPos] ?? 0;
        if (mergeCount >= mergeLimit || currentMergeCount >= mergeLimit) {
          break;
        }

        bool canMerge = false;
        if (mergePredicate == 'equal_value') {
          final aVal = entity.param('value');
          final bVal = nextEntity.param('value');
          canMerge = aVal != null && bVal != null && aVal == bVal;
        } else if (mergePredicate == 'same_kind') {
          canMerge = entity.kind == nextEntity.kind;
        }

        if (!canMerge) break;

        // Merge: remove both source positions, place merged tile at nextPos.
        final aVal = entity.param('value') as int? ?? 0;
        final bVal = nextEntity.param('value') as int? ?? 0;
        final resultValue = mergeResult == 'double' ? aVal * 2 : aVal + bVal;

        final mergedParams = Map<String, dynamic>.from(nextEntity.params)
          ..['value'] = resultValue;
        final mergedEntity = nextEntity.copyWith(params: mergedParams);

        // Remove the moving tile from its current working position (startPos,
        // since we haven't moved it in the working board yet).
        workingBoard.remove(startPos);
        workingBoard[nextPos] = mergedEntity;
        mergeCounts[nextPos] = mergeCount + 1;

        if (startPos != currentPos) {
          // The tile slid before merging — emit cleared for its original position.
          events.add(GameEvent.cellCleared(startPos, entity.kind));
        }
        events.add(GameEvent.tilesMerged(nextPos, resultValue, [aVal, bVal]));
        movedCount++;
        didMerge = true;
        break;
      }

      if (!didMerge && currentPos != startPos) {
        // Tile slid to currentPos without merging.
        workingBoard.remove(startPos);
        workingBoard[currentPos] = entity;
        movedCount++;
        events.add(GameEvent.cellCleared(startPos, entity.kind));
      }
    }

    // Commit working board to the real board.
    // First clear all original mergeable positions.
    for (final pos in mergeableTiles.map((e) => e.key)) {
      objectsLayer.setAt(pos, null);
    }
    // Then write new positions.
    for (final entry in workingBoard.entries) {
      objectsLayer.setAt(entry.key, entry.value);
    }

    if (movedCount == 0) return const [];

    final dirStr = direction.toJson();
    return [GameEvent.tilesSlid(dirStr, movedCount), ...events];
  }

  Position _wrapOrMove(
      Position pos, Direction direction, dynamic board, bool wrapAround) {
    if (!wrapAround) return pos.moved(direction);
    final moved = pos.moved(direction);
    final w = board.width as int;
    final h = board.height as int;
    return Position(
      (moved.x + w) % w,
      (moved.y + h) % h,
    );
  }
}
