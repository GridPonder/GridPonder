import '../engine/game_system.dart';
import '../models/direction.dart';
import '../models/direction_transform.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';
import 'claim_policy.dart';
import 'runtime_variable.dart';

/// One actor resolved for this turn, with the effective direction it travels
/// in after its `directionTransforms` entry is applied.
class _Mover {
  final Position pos;
  final EntityInstance entity;
  final Position eff;

  const _Mover(this.pos, this.entity, this.eff);
}

/// Next instruction from the tape, advancing the stored index.
///
/// A negative stored index (e.g. from a rewind rule using
/// `increment_variable` with a negative amount) is clamped to 0 rather than
/// wrapping — a rewind-past-the-start is inert, not surprising.
///
/// Returns null when a non-cycling programme is exhausted, which stops the
/// world stepping. A cycling programme wraps, so its index stays bounded by
/// the programme length — that keeps the joint state space finite for a
/// domain solver. `cycle` is compared with `!= true` (not truthy) so a typo
/// like `"cycle": 1` behaves as non-cycling rather than cycling.
String? _tapeDirection(Map<String, dynamic> tape, LevelState state) {
  final program = (tape['program'] as List<dynamic>? ?? const [])
      .map((d) => d.toString())
      .toList();
  if (program.isEmpty) return null;

  final idxVar = tape['indexVariable'] as String? ?? 'tapeIndex';
  var idx = readIntVariable(state, idxVar);
  if (idx < 0) idx = 0;
  if (idx >= program.length) {
    if (tape['cycle'] != true) return null;
    idx %= program.length;
  }
  state.variables[idxVar] = idx + 1;
  return program[idx];
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
///
/// Optionally, a `tape` config block (`{"program": [...], "cycle": bool,
/// "indexVariable": String}`) drives the system from a stored programme
/// instead of from the action's direction. The index lives in
/// `state.variables`, so it is part of the state key and undo, preview and
/// solver dedup all work unchanged. With `cycle` false the world stops
/// stepping once the programme is exhausted; with `cycle` true it repeats
/// forever and the index stays bounded. `cycle` is read strictly — only the
/// boolean `true` cycles, so a non-boolean value (e.g. `"cycle": 1`) behaves
/// as `false`.
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
    final tape = config['tape'] as Map<String, dynamic>?;

    final String? directionStr;
    if (tape == null) {
      final moveAction = config['moveAction'] as String? ?? 'move';
      if (action.actionId != moveAction) return const [];
      directionStr = action.directionStr;
    } else {
      // Tape-driven: the direction comes from the programme, so *any* accepted
      // action steps the world. A vetoed turn cannot leak the advanced index,
      // because the turn engine runs the whole turn on a working copy.
      directionStr = _tapeDirection(tape, state);
    }

    final allowedRaw =
        config['directions'] as List<dynamic>? ?? _defaultDirections;
    final allowed = allowedRaw.map((d) => d.toString()).toList();

    if (directionStr == null || !allowed.contains(directionStr)) {
      return const [];
    }

    // Not a safety guarantee: `allowed` is pack-authored (`directions`
    // config, and — under a `tape` — the tape's own `program`), so a pack
    // that lists an unparseable name in both throws `FormatException` here.
    // That matches the pre-tape `action.direction` path, which threw
    // identically; Python's `dir_delta` instead returns `(0, 0)` for the
    // same input and refuses silently, so a bogus direction name is not
    // symmetric across engines today.
    final delta = Direction.fromJson(directionStr).offset;
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
    // this reproduces the pre-0.8 order exactly.
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

      final claimEvent =
          applyClaim(board, game, claim, groundLayerId, target, entity.kind);
      if (claimEvent != null) events.add(claimEvent);
    }

    return events;
  }
}
