import 'package:gridponder_engine/engine.dart';

/// Idle facing for actors, resolved per entity rather than per kind.
///
/// A kind-wide facing cannot hold two machines of one kind heading opposite
/// ways, and never turns a machine that reverses without moving (an off-beat
/// shaft member flips its `facing` param on a beat it does not step). So the
/// play screen keeps the last facing seen at each cell, and an actor with no
/// entry falls back to its own `facing` param.
const _cardinals = {'up', 'down', 'left', 'right'};

/// The entity's `facing` param when it names a cardinal direction.
String? facingParamOf(EntityInstance entity) {
  final facing = entity.param('facing');
  return facing is String && _cardinals.contains(facing) ? facing : null;
}

/// The idle facing to draw for the actor [entity] standing at [pos].
String? actorIdleFacing(
  EntityInstance entity,
  Position pos,
  Map<Position, String> facingAt,
) => facingAt[pos] ?? facingParamOf(entity);

/// [facingAt] after [moves] land: each mover leaves its origin and faces the
/// way it travelled at its destination. Origins are cleared before
/// destinations are written, because one mover's destination is routinely
/// another's origin.
Map<Position, String> facingAfterMoves(
  Map<Position, String> facingAt,
  Iterable<({Position from, Position to, String direction})> moves,
) {
  if (moves.isEmpty) return facingAt;
  final next = Map<Position, String>.of(facingAt);
  for (final m in moves) {
    next.remove(m.from);
  }
  for (final m in moves) {
    next[m.to] = m.direction;
  }
  return next;
}

/// [facingAt] with every actor that turned this turn facing its new way.
///
/// A turn is an actor whose `facing` param changed while it stayed on its
/// cell: the same kind stands at the same cell before and after, with a
/// different param. Only the engine writes that param mid-level, so a change
/// is always a real turn. A kind whose behavior never writes it (a chaser
/// with an authored facing) never matches, and keeps the facing its moves
/// gave it.
Map<Position, String> facingAfterTurnsInPlace(
  Map<Position, String> facingAt,
  LevelState pre,
  LevelState post,
) {
  final before = pre.board.layers['actors'];
  final after = post.board.layers['actors'];
  if (before == null || after == null) return facingAt;
  Map<Position, String>? next;
  for (final entry in after.entries()) {
    final turned = facingParamOf(entry.value);
    if (turned == null) continue;
    final was = before.getAt(entry.key);
    if (was == null || was.kind != entry.value.kind) continue;
    if (was.param('facing') == turned) continue;
    (next ??= Map<Position, String>.of(facingAt))[entry.key] = turned;
  }
  return next ?? facingAt;
}
