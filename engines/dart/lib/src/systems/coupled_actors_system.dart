import '../engine/game_system.dart';
import '../models/direction_transform.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// One actor resolved for this turn, with the effective direction it travels
/// in after its `directionTransforms` entry is applied.
class _Mover {
  final Position pos;
  final EntityInstance entity;
  final Position eff;

  const _Mover(this.pos, this.entity, this.eff);
}

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

  /// Buckets resolve in this fixed order so that a board whose actors travel in
  /// several directions at once is still fully deterministic.
  static const _canonicalBuckets = [
    Position(0, -1), // up
    Position(0, 1), // down
    Position(-1, 0), // left
    Position(1, 0), // right
  ];

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

    final transforms =
        config['directionTransforms'] as Map<String, dynamic>? ?? const {};

    // Each actor travels in its own effective direction.
    final movers = [
      for (final e in actors)
        _Mover(
          e.key,
          e.value,
          transformDelta(
            Position(delta.x, delta.y),
            transforms[e.value.kind] as String?,
          ),
        ),
    ];

    // Bucket by effective direction; buckets resolve in canonical order. Within
    // a bucket, front-first exactly as before: projection onto that bucket's
    // direction descending, then the other-axis coordinate, then kind — fully
    // deterministic. With all-identity transforms there is a single bucket and
    // this reproduces the pre-0.10 order exactly.
    final ordered = <_Mover>[];
    for (final bucket in _canonicalBuckets) {
      final members = movers.where((m) => m.eff == bucket).toList();
      members.sort((a, b) {
        final projA = a.pos.x * bucket.x + a.pos.y * bucket.y;
        final projB = b.pos.x * bucket.x + b.pos.y * bucket.y;
        if (projA != projB) return projB.compareTo(projA);
        final otherA = a.pos.x * bucket.y.abs() + a.pos.y * bucket.x.abs();
        final otherB = b.pos.x * bucket.y.abs() + b.pos.y * bucket.x.abs();
        if (otherA != otherB) return otherA.compareTo(otherB);
        return a.entity.kind.compareTo(b.entity.kind);
      });
      ordered.addAll(members);
    }

    final occupied = {for (final e in actors) e.key};
    final events = <GameEvent>[];

    for (final mover in ordered) {
      final pos = mover.pos;
      final entity = mover.entity;
      final target = Position(pos.x + mover.eff.x, pos.y + mover.eff.y);

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
