import 'package:gridponder_engine/engine.dart';

/// One entity travelling between two cells during a turn.
class TravellingEntity {
  final Position from;
  final Position to;
  final String layer;

  /// What the piece looks like *while it travels*, which is not always what it
  /// becomes on arrival — a boulder that shatters on impact is drawn as a
  /// boulder for the whole flight.
  final EntityInstance entity;

  /// True when the mover leaves the board on arrival (an `entity_path` that
  /// exits it). The finished board then holds nothing of it at [to].
  final bool removedAtEnd;

  const TravellingEntity({
    required this.from,
    required this.to,
    required this.layer,
    required this.entity,
    this.removedAtEnd = false,
  });
}

/// The board to show while a turn's motion is still playing out.
///
/// The engine hands the UI the board as it stands *after* the whole turn, plus
/// the moves that produced it. Drawing that board directly puts every mover on
/// its destination cell before its animation has run, so the animation then has
/// to rewind it: the piece jumps ahead, snaps back, and slides the distance a
/// second time. Rewinding to the pre-turn board instead drags everything else
/// back with it — on a Firebreak turn where fifty cells catch, the fire
/// un-burns and the avatar hops back a cell for the length of the NPC's step.
///
/// Neither is right, because the board is not one clock. Terrain, the avatar
/// and each stage of movers finish at different moments, and the only rule that
/// holds for all of them is that nothing on screen may move backwards. So: keep
/// the finished board, and put back *only* the pieces that have not travelled
/// yet.
///
/// [pending] are movers whose stage has not started — drawn at their origins.
/// [inFlight] are movers animating right now — drawn nowhere, because the
/// sprite in flight is the only copy of them that should exist.
///
/// [hiddenTransforms] are `cell_transformed` events the turn resolved after
/// something still travelling, undone newest first so a cell does not change
/// before the mover that precedes it has arrived (see
/// [transformsAfterFirstPath]).
///
/// With all three empty this is just [postState], which is why the caller can
/// drop the held board entirely once the last stage lands.
LevelState boardDuringMotion(
  LevelState postState, {
  Iterable<TravellingEntity> pending = const [],
  Iterable<TravellingEntity> inFlight = const [],
  List<GameEvent> hiddenTransforms = const [],
}) {
  final state = postState.copy();

  for (final event in hiddenTransforms.reversed) {
    final layer = event.payload['layer'] as String?;
    final fromKind = event.payload['fromKind'] as String?;
    final toKind = event.payload['toKind'] as String?;
    final pos = event.position;
    if (layer == null || fromKind == null || pos == null) continue;
    final current = state.board.getEntity(layer, pos);
    // Only undo a transform the board still shows; a cell something else
    // rewrote since is left as it stands.
    if (current == null || current.kind != toKind) continue;
    state.board.setEntity(layer, pos, EntityInstance(fromKind, current.params));
  }

  // Clear every destination first, then place: one mover's destination is
  // routinely another's origin, and doing it in two passes keeps that from
  // depending on iteration order. A mover that left the board on arrival has
  // no destination to clear.
  for (final m in pending) {
    if (m.from == m.to || m.removedAtEnd) continue;
    state.board.setEntity(m.layer, m.to, null);
  }
  // An in-flight mover is cleared even when its path ends where it began.
  for (final m in inFlight) {
    if (m.removedAtEnd) continue;
    state.board.setEntity(m.layer, m.to, null);
  }
  for (final m in pending) {
    if (m.from == m.to) continue;
    // A cell that something else already occupies is left alone — the mover
    // reappears when it lands rather than overwriting whatever is standing
    // there now.
    if (state.board.getEntity(m.layer, m.from) != null) continue;
    state.board.setEntity(m.layer, m.from, m.entity);
  }
  return state;
}

/// The `cell_transformed` events resolved after the turn's first path started,
/// in the order they happened.
///
/// A path mover passes cells whose state the turn may change behind it — a
/// signal that switches once a flow has gone through. Those changes must stay
/// hidden until the paths have landed, or the flow is seen running through the
/// signal's later state. Everything the turn resolved before the paths is
/// already on screen and stays there.
List<GameEvent> transformsAfterFirstPath(Iterable<GameEvent> events) {
  final after = <GameEvent>[];
  var pathStarted = false;
  for (final event in events) {
    if (event.type == 'entity_path_moved') {
      pathStarted = true;
    } else if (pathStarted && event.type == 'cell_transformed') {
      after.add(event);
    }
  }
  return after;
}
