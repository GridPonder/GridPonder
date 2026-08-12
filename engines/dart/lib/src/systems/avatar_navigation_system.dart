import '../engine/game_system.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/entity.dart';

class AvatarNavigationSystem extends GameSystem {
  const AvatarNavigationSystem({required super.id})
      : super(type: 'avatar_navigation');

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, {});

    final moveAction = config['moveAction'] as String? ?? 'move';
    if (action.actionId != moveAction) return const [];

    final configDirections = config['directions'] as List<dynamic>? ??
        ['up', 'down', 'left', 'right'];
    final allowedDirections =
        configDirections.map((d) => d.toString()).toList();

    final dirStr = action.directionStr;
    if (dirStr == null || !allowedDirections.contains(dirStr)) return const [];

    final direction = action.direction;
    if (direction == null) return const [];

    final avatar = state.avatar;
    if (!avatar.enabled) return const [];

    final pos = avatar.position;
    if (pos == null) return const [];

    final board = state.board;
    final target = pos.moved(direction);

    // Turn to face the attempted direction even when the step is refused. A
    // blocked move still spends the turn, so without this the player gets no
    // signal that anything happened — and leaning on an obstacle is a
    // deliberate way to let a turn pass.
    state.avatar = state.avatar.copyWith(facing: direction);

    if (!board.isInBounds(target)) return const [];
    if (board.isVoid(target)) return const [];

    final solidHandling = config['solidHandling'] as String? ?? 'block';

    // Layers checked for a `solid` blocker, in order. Defaults to objects only,
    // so packs that place blockers on other layers (NPCs on `actors`, for
    // instance) have to opt in.
    final solidLayers = (config['solidLayers'] as List<dynamic>? ?? ['objects'])
        .map((l) => l.toString())
        .toList();
    EntityInstance? entityAtTarget;
    for (final layerName in solidLayers) {
      final candidate = board.layers[layerName]?.getAt(target);
      if (candidate != null && game.hasTag(candidate.kind, 'solid')) {
        entityAtTarget = candidate;
        break;
      }
    }

    if (entityAtTarget != null) {
      if (solidHandling == 'block') {
        return const [];
      } else if (solidHandling == 'delegate') {
        state.pendingMove = PendingMove(
          from: pos,
          to: target,
          direction: direction,
        );
        return [
          GameEvent.moveBlocked(target, pos, dirStr, entityAtTarget.kind),
        ];
      }
      return const [];
    }

    // Avatar can move here (entity is null, or non-solid like portals/pickups)
    state.avatar = state.avatar.copyWith(
      position: target,
      facing: direction,
    );

    return [
      GameEvent.avatarExited(pos),
      GameEvent.avatarEntered(target, pos, dirStr),
    ];
  }
}
