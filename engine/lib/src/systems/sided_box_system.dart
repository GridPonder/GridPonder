import '../engine/game_system.dart';
import '../models/direction.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// Side bit constants: U=1, R=2, D=4, L=8.
const int _sideU = 1;
const int _sideR = 2;
const int _sideD = 4;
const int _sideL = 8;
/// Returns the side bit for a cardinal direction.
int _sideBit(Direction d) => switch (d) {
      Direction.up => _sideU,
      Direction.down => _sideD,
      Direction.left => _sideL,
      Direction.right => _sideR,
      _ => 0,
    };

/// Handles avatar movement with side-aware collision, push, carry, and merge.
///
/// Replaces avatar_navigation + push_objects for games with sided box
/// fragments. Each box entity has a `sides` integer param encoding which
/// walls exist (U=1, R=2, D=4, L=8). Movement through a cell boundary is
/// blocked only if the relevant side bit is set.
class SidedBoxSystem extends GameSystem {
  const SidedBoxSystem({required super.id}) : super(type: 'sided_box');

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, {});
    final moveAction = config['moveAction'] as String? ?? 'move';
    if (action.actionId != moveAction) return const [];

    final dirStr = action.directionStr;
    if (dirStr == null) return const [];
    final direction = action.direction;
    if (direction == null || !direction.isCardinal) return const [];

    final avatar = state.avatar;
    if (!avatar.enabled || avatar.position == null) return const [];

    final pos = avatar.position!;
    final board = state.board;
    final target = pos.moved(direction);

    if (!board.isInBounds(target)) return const [];
    if (board.isVoid(target)) return const [];

    final sidedTag = config['sidedTag'] as String? ?? 'sided';
    final sidesParam = config['sidesParam'] as String? ?? 'sides';
    final validGroundTagsRaw =
        config['validGroundTags'] as List<dynamic>? ?? ['walkable'];
    final validGroundTags =
        validGroundTagsRaw.map((t) => t.toString()).toList();
    final toolInteractionsRaw =
        config['toolInteractions'] as List<dynamic>? ?? const [];
    final toolInteractions =
        toolInteractionsRaw.map((e) => e as Map<String, dynamic>).toList();

    final objectsLayer = board.layers['objects'];
    final groundLayer = board.layers['ground'];

    // Helper: is this entity a sided box?
    bool isSided(EntityInstance? e) =>
        e != null && game.hasTag(e.kind, sidedTag);

    int sides(EntityInstance e) => (e.param(sidesParam) as int?) ?? 0;

    // Helper: validate ground at a position for box placement.
    bool validGround(Position p) {
      if (groundLayer == null) return false;
      final g = groundLayer.getAt(p);
      if (g == null) return false;
      return validGroundTags.any((tag) => game.hasTag(g.kind, tag));
    }

    final entityAtPos = objectsLayer?.getAt(pos);
    final entityAtTarget = objectsLayer?.getAt(target);

    final outBit = _sideBit(direction); // side we exit through
    final inBit = _sideBit(direction.opposite); // side we enter through
    // Sides perpendicular to the push direction — two boxes cannot share these
    // when merging, as their parallel walls would physically overlap.
    final perpMask = (outBit == _sideU || outBit == _sideD)
        ? (_sideL | _sideR)
        : (_sideU | _sideD);

    // ---------------------------------------------------------------
    // CASE 1: Carry — avatar is on a cell with a sided box and exits
    // through an existing side.
    // ---------------------------------------------------------------
    if (isSided(entityAtPos) && (sides(entityAtPos!) & outBit) != 0) {
      // The avatar is "inside" a box and pushes against a wall → carry.

      // Check if the box can land at the target.
      if (!board.isInBounds(target) || board.isVoid(target)) {
        return const []; // Can't carry box off-board / into void
      }

      // If target has a non-sided solid → carry blocked, move blocked.
      if (entityAtTarget != null &&
          !isSided(entityAtTarget) &&
          game.hasTag(entityAtTarget.kind, 'solid')) {
        return const []; // Wall blocks carry
      }

      // If target has a sided box → check inward side first, then carry + merge.
      if (isSided(entityAtTarget)) {
        // The destination box's inward side blocks entry, same as walking.
        if ((sides(entityAtTarget!) & inBit) != 0) return const [];
        // Parallel walls on both boxes would physically overlap — merge blocked.
        if ((sides(entityAtPos) & sides(entityAtTarget!) & perpMask) != 0) return const [];
        final merged = sides(entityAtPos) | sides(entityAtTarget);
        final mergedEntity = EntityInstance(
          entityAtPos.kind,
          {...entityAtPos.params, sidesParam: merged},
        );
        board.setEntity('objects', pos, null);
        board.setEntity('objects', target, mergedEntity);
        state.avatar =
            state.avatar.copyWith(position: target, facing: direction);
        return [
          GameEvent.boxesMerged(
              target, merged, sides(entityAtPos), sides(entityAtTarget)),
          GameEvent.avatarExited(pos),
          GameEvent.avatarEntered(target, pos, dirStr),
        ];
      }

      // Target is clear (or has non-solid, non-sided entity like portal) →
      // carry box there.
      // But if target already has an objects-layer entity that isn't sided,
      // we can't place the box there (zero_or_one occupancy).
      if (entityAtTarget != null && !isSided(entityAtTarget)) {
        // Non-sided, non-solid entity at target (e.g. pickup, portal).
        // Can't place box on occupied cell. Move blocked.
        return const [];
      }

      board.setEntity('objects', pos, null);
      board.setEntity('objects', target, entityAtPos);
      state.avatar =
          state.avatar.copyWith(position: target, facing: direction);
      return [
        GameEvent.objectPushed(entityAtPos.kind, pos, target, dirStr),
        GameEvent.objectPlaced(target, entityAtPos.kind, entityAtPos.params),
        GameEvent.avatarExited(pos),
        GameEvent.avatarEntered(target, pos, dirStr),
      ];
    }

    // ---------------------------------------------------------------
    // CASE 2: Target has a sided box.
    // ---------------------------------------------------------------
    if (isSided(entityAtTarget)) {
      if ((sides(entityAtTarget!) & inBit) != 0) {
        // 2a: PUSH — the inward side blocks entry.
        final pushDest = target.moved(direction);

        if (!board.isInBounds(pushDest)) return const [];
        if (board.isVoid(pushDest)) return const [];
        if (!validGround(pushDest)) return const [];

        final entityAtPushDest = objectsLayer?.getAt(pushDest);

        // Push destination has a sided box → push + merge.
        if (isSided(entityAtPushDest)) {
          // Parallel walls on both boxes would physically overlap — merge blocked.
          if ((sides(entityAtTarget) & sides(entityAtPushDest!) & perpMask) != 0) return const [];
          final merged = sides(entityAtTarget) | sides(entityAtPushDest!);
          final mergedEntity = EntityInstance(
            entityAtTarget.kind,
            {...entityAtTarget.params, sidesParam: merged},
          );
          board.setEntity('objects', target, null);
          board.setEntity('objects', pushDest, mergedEntity);
          state.avatar =
              state.avatar.copyWith(position: target, facing: direction);
          return [
            GameEvent.objectPushed(
                entityAtTarget.kind, target, pushDest, dirStr),
            GameEvent.boxesMerged(pushDest, merged, sides(entityAtTarget),
                sides(entityAtPushDest)),
            GameEvent.avatarExited(pos),
            GameEvent.avatarEntered(target, pos, dirStr),
          ];
        }

        // Push destination has any non-null entity → blocked.
        if (entityAtPushDest != null) return const [];

        // Push to empty cell.
        board.setEntity('objects', target, null);
        board.setEntity('objects', pushDest, entityAtTarget);
        state.avatar =
            state.avatar.copyWith(position: target, facing: direction);
        return [
          GameEvent.objectPushed(
              entityAtTarget.kind, target, pushDest, dirStr),
          GameEvent.objectPlaced(
              pushDest, entityAtTarget.kind, entityAtTarget.params),
          GameEvent.avatarExited(pos),
          GameEvent.avatarEntered(target, pos, dirStr),
        ];
      } else {
        // 2b: ENTER — inward side not set, avatar walks into the cell
        // (co-occupies with the box; avatar is tracked separately).
        state.avatar =
            state.avatar.copyWith(position: target, facing: direction);
        return [
          GameEvent.avatarExited(pos),
          GameEvent.avatarEntered(target, pos, dirStr),
        ];
      }
    }

    // ---------------------------------------------------------------
    // CASE 3: Target has a non-sided solid entity (wall, rock).
    // ---------------------------------------------------------------
    if (entityAtTarget != null && game.hasTag(entityAtTarget.kind, 'solid')) {
      // Check tool interactions (pickaxe breaks rock, etc.)
      for (final interaction in toolInteractions) {
        final requiredItem = interaction['item'] as String?;
        final targetTag = interaction['targetTag'] as String?;
        if (requiredItem == null || targetTag == null) continue;
        if (state.avatar.inventory.slot != requiredItem) continue;
        if (!game.hasTag(entityAtTarget.kind, targetTag)) continue;

        // Interaction matches — destroy entity and move avatar.
        board.setEntity('objects', target, null);
        state.avatar =
            state.avatar.copyWith(position: target, facing: direction);

        final consumeItem = interaction['consumeItem'] as bool? ?? false;
        if (consumeItem) {
          state.avatar = state.avatar.copyWith(
              inventory: state.avatar.inventory.copyWith(slot: null));
        }

        final animName = interaction['animation'] as String?;
        final hasAnim = animName != null &&
            (game.entityKinds[entityAtTarget.kind]
                    ?.animations
                    .containsKey(animName) ??
                false);

        return [
          hasAnim
              ? GameEvent.objectRemovedAnimated(
                  target, entityAtTarget.kind, animName)
              : GameEvent.objectRemoved(target, entityAtTarget.kind),
          GameEvent.cellCleared(target, entityAtTarget.kind),
          GameEvent.avatarExited(pos),
          GameEvent.avatarEntered(target, pos, dirStr),
        ];
      }

      // No matching tool → blocked.
      return const [];
    }

    // ---------------------------------------------------------------
    // CASE 4: Target is clear — normal move.
    // ---------------------------------------------------------------
    state.avatar =
        state.avatar.copyWith(position: target, facing: direction);
    return [
      GameEvent.avatarExited(pos),
      GameEvent.avatarEntered(target, pos, dirStr),
    ];
  }
}
