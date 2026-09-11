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

  const TravellingEntity({
    required this.from,
    required this.to,
    required this.layer,
    required this.entity,
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
/// With both empty this is just [postState], which is why the caller can drop
/// the held board entirely once the last stage lands.
LevelState boardDuringMotion(
  LevelState postState, {
  Iterable<TravellingEntity> pending = const [],
  Iterable<TravellingEntity> inFlight = const [],
}) {
  final state = postState.copy();

  // Clear every destination first, then place: one mover's destination is
  // routinely another's origin, and doing it in two passes keeps that from
  // depending on iteration order.
  for (final m in [...pending, ...inFlight]) {
    if (m.from == m.to) continue;
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
