import '../engine/game_system.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// CoupledActorsSystem — see docs/dsl/04_systems.md.
///
/// On the configured move action, shifts every actor entity on a layer
/// (default `actors`) one cell in the given direction, all together. Actors
/// are resolved front-first (the actor closest to the destination edge
/// first) so that a trailing actor can "train" into a cell the actor ahead
/// of it just vacated. An actor whose target cell is out of bounds, blocked
/// by a wall (tagged `wallTag` on `groundLayer`), or still occupied by
/// another actor stays in place instead of moving — and because the
/// `occupied` set is updated live as each actor resolves, an actor blocked
/// by a wall correctly "traps" the actor behind it (its target cell never
/// frees up).
///
/// Optionally, when the system config has a `claim` block (`{"layer": ...,
/// "map": {kind: territoryKind, ...}}`), an actor that successfully moves to
/// a new cell also claims that cell in the named territory layer — but only
/// if the cell is currently empty there; an already-owned territory cell is
/// never overwritten. Claiming applies only to cells reached by a move this
/// turn, not to blocked/staying actors or to actors' initial cells.
class CoupledActorsSystem extends GameSystem {
  const CoupledActorsSystem({required super.id})
      : super(type: 'coupled_actors');

  static const _defaultDirections = ['up', 'down', 'left', 'right'];

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, {});

    final moveAction = config['moveAction'] as String? ?? 'move';
    if (action.actionId != moveAction) return const [];

    final allowedRaw =
        config['directions'] as List<dynamic>? ?? _defaultDirections;
    final allowed = allowedRaw.map((d) => d.toString()).toList();

    final directionStr = action.directionStr;
    if (directionStr == null || !allowed.contains(directionStr)) {
      return const [];
    }

    final direction = action.direction;
    if (direction == null) return const [];

    final delta = direction.offset;
    if (delta.x == 0 && delta.y == 0) return const [];

    final actorLayerId = config['actorLayer'] as String? ?? 'actors';
    final groundLayerId = config['groundLayer'] as String? ?? 'ground';
    final wallTag = config['wallTag'] as String? ?? 'solid';
    final claim = config['claim'] as Map<String, dynamic>?;

    final board = state.board;
    final actorLayer = board.layers[actorLayerId];
    if (actorLayer == null) return const [];

    final actors = actorLayer.entries().toList();
    if (actors.isEmpty) return const [];

    // Front-first order: sort by the projection of position onto the
    // direction of travel, descending (the actor nearest the direction of
    // travel resolves first). Ties broken by the other-axis coordinate then
    // kind, for a fully deterministic order.
    actors.sort((a, b) {
      final projA = a.key.x * delta.x + a.key.y * delta.y;
      final projB = b.key.x * delta.x + b.key.y * delta.y;
      if (projA != projB) return projB.compareTo(projA);
      final otherA = a.key.x * delta.y.abs() + a.key.y * delta.x.abs();
      final otherB = b.key.x * delta.y.abs() + b.key.y * delta.x.abs();
      if (otherA != otherB) return otherA.compareTo(otherB);
      return a.value.kind.compareTo(b.value.kind);
    });

    final occupied = {for (final e in actors) e.key};
    final events = <GameEvent>[];

    for (final entry in actors) {
      final pos = entry.key;
      final entity = entry.value;
      final target = Position(pos.x + delta.x, pos.y + delta.y);

      final blocked = !board.isInBounds(target) ||
          board.hasTagAt(groundLayerId, target, wallTag, game.entityKinds) ||
          occupied.contains(target);

      if (blocked) {
        events.add(GameEvent.actorBlocked(entity.kind, pos));
        continue;
      }

      occupied.remove(pos);
      occupied.add(target);
      board.setEntity(actorLayerId, pos, null);
      board.setEntity(actorLayerId, target, entity);
      events.add(GameEvent.actorMoved(entity.kind, pos, target, directionStr));
      events
          .add(GameEvent.actorEntered(entity.kind, target, pos, directionStr));

      if (claim != null) {
        final claimLayerId = claim['layer'] as String;
        final claimMap = claim['map'] as Map<String, dynamic>? ?? const {};
        final claimKind = claimMap[entity.kind] as String?;
        if (claimKind != null &&
            board.getEntity(claimLayerId, target) == null) {
          board.setEntity(claimLayerId, target, EntityInstance(claimKind));
          events.add(GameEvent.cellClaimed(
              target, claimLayerId, claimKind, entity.kind));
        }
      }
    }

    return events;
  }
}
