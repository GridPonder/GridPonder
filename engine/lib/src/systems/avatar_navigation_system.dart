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

    if (!board.isInBounds(target)) return const [];
    if (board.isVoid(target)) return const [];

    final solidHandling = config['solidHandling'] as String? ?? 'block';

    final objectsLayer = board.layers['objects'];
    EntityInstance? entityAtTarget;
    if (objectsLayer != null) {
      entityAtTarget = objectsLayer.getAt(target);
    }

    if (entityAtTarget != null && game.hasTag(entityAtTarget.kind, 'solid')) {
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
