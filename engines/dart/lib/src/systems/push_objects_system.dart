import '../engine/game_system.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/layer.dart';
import '../models/position.dart';

class PushObjectsSystem extends GameSystem {
  const PushObjectsSystem({required super.id})
      : super(type: 'push_objects');

  @override
  List<GameEvent> executeMovementResolution(
    LevelState state,
    GameDefinition game,
  ) {
    final pending = state.pendingMove;
    if (pending == null) return const [];

    final config = game.systemConfig(id, {});

    final pushableTagsRaw =
        config['pushableTags'] as List<dynamic>? ?? ['pushable'];
    final pushableTags = pushableTagsRaw.map((t) => t.toString()).toList();

    final validTargetTagsRaw =
        config['validTargetTags'] as List<dynamic>? ?? ['walkable'];
    final validTargetTags =
        validTargetTagsRaw.map((t) => t.toString()).toList();

    final chainPush = config['chainPush'] as bool? ?? false;

    // Parse toolInteractions — generic item-based destruction of entities.
    final toolInteractionsRaw =
        config['toolInteractions'] as List<dynamic>? ?? const [];
    final toolInteractions = toolInteractionsRaw
        .map((e) => e as Map<String, dynamic>)
        .toList();

    final board = state.board;
    final objectsLayer = board.layers['objects'];
    final groundLayer = board.layers['ground'];

    if (objectsLayer == null) return const [];

    final entityAtTarget = objectsLayer.getAt(pending.to);
    if (entityAtTarget == null) return const [];

    final from = pending.from;
    final to = pending.to;
    final direction = pending.direction;
    final dirStr = direction.toJson();

    // Check toolInteractions before pushable check — applies to any solid entity.
    // Each interaction: { item, targetTag, consumeItem?, animation? }
    for (final interaction in toolInteractions) {
      final requiredItem = interaction['item'] as String?;
      final targetTag = interaction['targetTag'] as String?;
      if (requiredItem == null || targetTag == null) continue;
      if (state.avatar.inventory.slot != requiredItem) continue;
      if (!game.hasTag(entityAtTarget.kind, targetTag)) continue;

      // Interaction matches — destroy entity and move avatar.
      board.setEntity('objects', pending.to, null);
      state.pendingMove = null;
      state.avatar = state.avatar.copyWith(position: to, facing: direction);

      final consumeItem = interaction['consumeItem'] as bool? ?? false;
      if (consumeItem) {
        state.avatar = state.avatar.copyWith(
            inventory: state.avatar.inventory.copyWith(slot: null));
      }

      final animName = interaction['animation'] as String?;
      final hasAnim = animName != null &&
          (game.entityKinds[entityAtTarget.kind]?.animations.containsKey(animName) ??
              false);

      return [
        hasAnim
            ? GameEvent.objectRemovedAnimated(
                pending.to, entityAtTarget.kind, animName)
            : GameEvent.objectRemoved(pending.to, entityAtTarget.kind),
        GameEvent.cellCleared(pending.to, entityAtTarget.kind),
        GameEvent.avatarExited(from),
        GameEvent.avatarEntered(to, from, dirStr),
      ];
    }

    final isPushable = pushableTags
        .any((tag) => game.hasTag(entityAtTarget.kind, tag));
    if (!isPushable) return const [];

    final pushDest = pending.to.moved(pending.direction);

    // Validate pushDest: must be in bounds and not void
    if (!board.isInBounds(pushDest)) return const [];
    if (board.isVoid(pushDest)) return const [];

    // Check objects layer at pushDest
    final entityAtPushDest = objectsLayer.getAt(pushDest);
    if (entityAtPushDest != null) {
      if (!chainPush) return const [];
      // chainPush: the object at pushDest must also be pushable
      final chainPushable = pushableTags
          .any((tag) => game.hasTag(entityAtPushDest.kind, tag));
      if (!chainPushable) return const [];
      // For simplicity, chain push only one level deep - check that next cell is free
      final chainDest = pushDest.moved(pending.direction);
      if (!board.isInBounds(chainDest)) return const [];
      if (board.isVoid(chainDest)) return const [];
      final entityAtChainDest = objectsLayer.getAt(chainDest);
      if (entityAtChainDest != null) return const [];
      // Validate ground at chainDest
      if (!_isValidGround(groundLayer, chainDest, validTargetTags, game)) {
        return const [];
      }
      // Execute chain push first
      board.setEntity('objects', pushDest, null);
      board.setEntity('objects', chainDest, entityAtPushDest);
    }

    // Validate ground at pushDest
    if (!_isValidGround(groundLayer, pushDest, validTargetTags, game)) {
      return const [];
    }

    // Execute push
    board.setEntity('objects', pending.to, null);
    board.setEntity('objects', pushDest, entityAtTarget);

    // Clear pending move and move avatar
    state.pendingMove = null;
    state.avatar = state.avatar.copyWith(
      position: to,
      facing: direction,
    );

    return [
      GameEvent.objectPushed(entityAtTarget.kind, pending.to, pushDest, dirStr),
      GameEvent.objectPlaced(pushDest, entityAtTarget.kind, entityAtTarget.params),
      GameEvent.avatarExited(from),
      GameEvent.avatarEntered(to, from, dirStr),
    ];
  }

  bool _isValidGround(
    BoardLayer? groundLayer,
    Position pos,
    List<String> validTargetTags,
    GameDefinition game,
  ) {
    if (groundLayer == null) return false;
    final ground = groundLayer.getAt(pos);
    if (ground == null) return false;
    return validTargetTags.any((tag) => game.hasTag(ground.kind, tag));
  }
}
