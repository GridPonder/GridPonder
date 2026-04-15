import '../engine/game_system.dart';
import '../models/direction.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// Handles sliding movement for avatar and objects on slippery (ice) ground.
///
/// When the avatar or a pushed object lands on a cell tagged [slipperyTag],
/// this system moves them one cell further in the same direction. Because it
/// runs in the cascade phase, each pass slides one cell; the new [avatarEntered]
/// or [objectPlaced] event feeds into the next pass, chaining until something
/// blocks the slide or the cell is no longer slippery.
///
/// Rules (e.g. torch_melts_ice, pickaxe_breaks_ice) fire BEFORE cascade systems
/// in each pass, so a tool interaction that transforms the ground will stop the
/// slide naturally — the system will see non-slippery ground and do nothing.
class IceSlideSystem extends GameSystem {
  const IceSlideSystem({required super.id}) : super(type: 'ice_slide');

  @override
  List<GameEvent> executeCascadeResolution(
    List<GameEvent> triggerEvents,
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, null);
    final slipperyTag = config['slipperyTag'] as String? ?? 'slippery';

    // Handle at most one avatar slide and one object slide per pass.
    // Multiple slides in a single pass would be ambiguous ordering.
    final avatarEvents = _handleAvatarSlide(triggerEvents, state, game, slipperyTag);
    if (avatarEvents.isNotEmpty) return avatarEvents;

    return _handleObjectSlide(triggerEvents, state, game, slipperyTag);
  }

  List<GameEvent> _handleAvatarSlide(
    List<GameEvent> triggerEvents,
    LevelState state,
    GameDefinition game,
    String slipperyTag,
  ) {
    for (final event in triggerEvents) {
      if (event.type != 'avatar_entered') continue;

      final pos = state.avatar.position;
      if (pos == null) continue;

      // Check if the avatar is currently on slippery ground.
      // (Rules may have already transformed the ground in this same pass.)
      final ground = state.board.getEntity('ground', pos);
      if (ground == null || !game.hasTag(ground.kind, slipperyTag)) continue;

      final dirStr = event.payload['direction'] as String?;
      if (dirStr == null) continue;
      final direction = Direction.fromJson(dirStr);

      final nextPos = pos.moved(direction);

      if (!state.board.isInBounds(nextPos)) continue;
      if (state.board.isVoid(nextPos)) continue;

      // If there is a solid object at the next cell, attempt a push.
      final EntityInstance? objAtNext = state.board.getEntity('objects', nextPos);
      if (objAtNext != null && game.hasTag(objAtNext.kind, 'solid')) {
        return _tryPushDuringSlide(state, game, pos, nextPos, direction, dirStr, objAtNext);
      }

      // Stop if the next ground is not walkable.
      final nextGround = state.board.getEntity('ground', nextPos);
      if (nextGround == null || !game.hasTag(nextGround.kind, 'walkable')) continue;

      // Slide one cell.
      final fromPos = pos;
      state.avatar = state.avatar.copyWith(
        position: nextPos,
        facing: direction,
      );

      return [
        GameEvent.avatarExited(fromPos),
        GameEvent.avatarEntered(nextPos, fromPos, dirStr),
      ];
    }
    return const [];
  }

  /// Attempts to push [obj] at [objPos] one cell in [direction] during a slide.
  /// Returns push+move events if successful, or empty list to stop the slide.
  List<GameEvent> _tryPushDuringSlide(
    LevelState state,
    GameDefinition game,
    Position avatarPos,
    Position objPos,
    Direction direction,
    String dirStr,
    EntityInstance obj,
  ) {
    // Read pushable tags from the push_objects system config (game-agnostic).
    final pushSysDef = game.systems.where((s) => s.type == 'push_objects').firstOrNull;
    if (pushSysDef == null) return const [];
    final pushConfig = pushSysDef.config;
    final pushableTagsRaw = pushConfig['pushableTags'] as List<dynamic>? ?? ['pushable'];
    final pushableTags = pushableTagsRaw.map((t) => t.toString()).toList();
    final validTargetTagsRaw = pushConfig['validTargetTags'] as List<dynamic>? ?? ['walkable'];
    final validTargetTags = validTargetTagsRaw.map((t) => t.toString()).toList();

    if (!pushableTags.any((tag) => game.hasTag(obj.kind, tag))) {
      return const []; // not pushable, stop slide
    }

    final pushDest = objPos.moved(direction);
    if (!state.board.isInBounds(pushDest)) return const [];
    if (state.board.isVoid(pushDest)) return const [];

    final objAtPushDest = state.board.getEntity('objects', pushDest);
    if (objAtPushDest != null) return const []; // blocked, stop slide

    final groundAtPushDest = state.board.getEntity('ground', pushDest);
    if (groundAtPushDest == null) return const [];
    if (!validTargetTags.any((tag) => game.hasTag(groundAtPushDest.kind, tag))) {
      return const [];
    }

    // Execute push: move object, then move avatar to where the object was.
    state.board.setEntity('objects', objPos, null);
    state.board.setEntity('objects', pushDest, obj);
    state.avatar = state.avatar.copyWith(position: objPos, facing: direction);

    return [
      GameEvent.objectPushed(obj.kind, objPos, pushDest, dirStr),
      GameEvent.objectPlaced(pushDest, obj.kind, obj.params),
      GameEvent.avatarExited(avatarPos),
      GameEvent.avatarEntered(objPos, avatarPos, dirStr),
    ];
  }

  List<GameEvent> _handleObjectSlide(
    List<GameEvent> triggerEvents,
    LevelState state,
    GameDefinition game,
    String slipperyTag,
  ) {
    // Build a map from destination position → push direction from object_pushed events.
    // This lets us know the direction an object was travelling when it landed.
    final pushedDirections = <Position, String>{};
    for (final event in triggerEvents) {
      if (event.type != 'object_pushed') continue;
      final toPos = event.payload['toPosition'];
      final dirStr = event.payload['direction'] as String?;
      if (toPos == null || dirStr == null) continue;
      final pos = toPos is Position ? toPos : Position.fromJson(toPos);
      pushedDirections[pos] = dirStr;
    }

    for (final event in triggerEvents) {
      if (event.type != 'object_placed') continue;

      final pos = event.position;
      if (pos == null) continue;

      // Check if the object landed on slippery ground.
      final ground = state.board.getEntity('ground', pos);
      if (ground == null || !game.hasTag(ground.kind, slipperyTag)) continue;

      final dirStr = pushedDirections[pos];
      if (dirStr == null) continue;
      final direction = Direction.fromJson(dirStr);

      final entity = state.board.getEntity('objects', pos);
      if (entity == null) continue;

      final nextPos = pos.moved(direction);

      if (!state.board.isInBounds(nextPos)) continue;
      if (state.board.isVoid(nextPos)) continue;

      // Stop if a solid object is at the next cell.
      final objAtNext = state.board.getEntity('objects', nextPos);
      if (objAtNext != null && game.hasTag(objAtNext.kind, 'solid')) continue;

      // The next cell's ground must be walkable (includes water — crate can sink).
      final nextGround = state.board.getEntity('ground', nextPos);
      if (nextGround == null || !game.hasTag(nextGround.kind, 'walkable')) continue;

      // Slide the object one cell.
      state.board.setEntity('objects', pos, null);
      state.board.setEntity('objects', nextPos, entity);

      return [
        GameEvent.cellCleared(pos, entity.kind),
        GameEvent.objectPushed(entity.kind, pos, nextPos, dirStr),
        GameEvent.objectPlaced(nextPos, entity.kind, entity.params),
      ];
    }
    return const [];
  }
}
