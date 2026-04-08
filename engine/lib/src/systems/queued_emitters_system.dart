import '../engine/game_system.dart';
import '../models/board.dart';
import '../models/direction.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';
import '../models/entity.dart';

/// Releases one item per turn from each queued-emitter MCO whose front cell
/// (exitPosition + exitDirection) is empty.  Runs in Phase 6 (NPC resolution)
/// so it fires once per turn, after all slides and cascades have settled.
///
/// Supports both unidirectional and bidirectional pipes:
///   - Unidirectional: single exit defined by exitPosition + exitDirection.
///   - Bidirectional:  two exits; presence of exit2Position activates this
///     mode.  Numbers route to the nearer open exit each turn.  A number at
///     the midpoint of an odd-length pipe is stuck when both exits are clear.
///     See docs/dsl/04_systems.md §2.5 for the full routing rules.
class QueuedEmittersSystem extends GameSystem {
  const QueuedEmittersSystem({required super.id})
      : super(type: 'queued_emitters');

  @override
  List<GameEvent> executeNpcResolution(
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, {});
    final emitterKind = config['emitterKind'] as String? ?? 'pipe';

    final board = state.board;
    final List<GameEvent> events = [];

    for (final mco in board.multiCellObjects) {
      if (mco.kind != emitterKind) continue;

      final exitPosRaw = mco.params['exitPosition'];
      if (exitPosRaw == null) continue;
      final exitPos = Position.fromJson(exitPosRaw);

      final exitDirStr = mco.params['exitDirection'] as String?;
      final spawnPos = exitDirStr != null
          ? exitPos.moved(Direction.fromJson(exitDirStr))
          : exitPos;

      final queue = mco.params['queue'] as List<dynamic>? ?? [];

      final exit2PosRaw = mco.params['exit2Position'];
      if (exit2PosRaw != null) {
        // ── Bidirectional pipe ──────────────────────────────────────────────
        final exit2Pos = Position.fromJson(exit2PosRaw);
        final exit2DirStr = mco.params['exit2Direction'] as String?;
        final spawn2Pos = exit2DirStr != null
            ? exit2Pos.moved(Direction.fromJson(exit2DirStr))
            : exit2Pos;

        _emitBidirectional(
          board, mco, events, queue, exitPos, spawnPos, exit2Pos, spawn2Pos,
        );
      } else {
        // ── Unidirectional pipe (original behaviour) ────────────────────────
        final currentIndex = mco.params['currentIndex'] as int? ?? 0;
        if (currentIndex >= queue.length) continue;

        if (board.getEntity('objects', exitPos) != null) continue;
        if (spawnPos != exitPos &&
            board.getEntity('objects', spawnPos) != null) continue;

        final nextValue = queue[currentIndex];
        final itemParams = <String, dynamic>{'value': nextValue};
        board.setEntity('objects', spawnPos, EntityInstance('number', itemParams));
        mco.params['currentIndex'] = currentIndex + 1;

        events.add(GameEvent.itemReleased(mco.id, 'number', spawnPos, itemParams));
      }
    }

    return events;
  }

  void _emitBidirectional(
    Board board,
    MultiCellObjectInstance mco,
    List<GameEvent> events,
    List<dynamic> queue,
    Position exit1Pos,
    Position spawn1Pos,
    Position exit2Pos,
    Position spawn2Pos,
  ) {
    final n = queue.length;
    final e1 = mco.params['currentIndex'] as int? ?? 0;
    final e2 = mco.params['exit2Index'] as int? ?? 0;
    final remaining = n - e1 - e2;

    if (remaining <= 0) return;

    // A spawn cell is considered clear when it carries no object entity.
    bool _clear(Position exit, Position spawn) =>
        board.getEntity('objects', exit) == null &&
        (spawn == exit || board.getEntity('objects', spawn) == null);

    final can1 = _clear(exit1Pos, spawn1Pos);
    final can2 = _clear(exit2Pos, spawn2Pos);

    if (!can1 && !can2) return;

    void emitFrom1(dynamic val) {
      final p = <String, dynamic>{'value': val};
      board.setEntity('objects', spawn1Pos, EntityInstance('number', p));
      mco.params['currentIndex'] = e1 + 1;
      events.add(GameEvent.itemReleased(mco.id, 'number', spawn1Pos, p));
    }

    void emitFrom2(dynamic val) {
      final p = <String, dynamic>{'value': val};
      board.setEntity('objects', spawn2Pos, EntityInstance('number', p));
      mco.params['exit2Index'] = e2 + 1;
      events.add(GameEvent.itemReleased(mco.id, 'number', spawn2Pos, p));
    }

    if (remaining == 1) {
      // Single number left; its position in the pipe = e1 (== n-1-e2).
      // dist to exit1 = e1, dist to exit2 = e2.
      final val = queue[e1];
      if (e1 < e2) {
        // Closer to exit 1 — prefer exit 1, fall back to exit 2.
        if (can1) { emitFrom1(val); } else { emitFrom2(val); }
      } else if (e2 < e1) {
        // Closer to exit 2 — prefer exit 2, fall back to exit 1.
        if (can2) { emitFrom2(val); } else { emitFrom1(val); }
      } else {
        // Equidistant (midpoint of odd-length pipe): stuck if both clear.
        if (can1 && !can2) { emitFrom1(val); }
        else if (can2 && !can1) { emitFrom2(val); }
        // Both clear or both blocked → no emission this turn (stuck).
      }
    } else {
      // Multiple remaining: pick the candidate closest to its respective exit.
      // e1 candidate: queue[e1], dist from exit1 = e1.
      // e2 candidate: queue[n-1-e2], dist from exit2 = e2.
      // Prefer exit 1 on tie.
      final useE1 = can1 && (!can2 || e1 <= e2);
      if (useE1) {
        emitFrom1(queue[e1]);
      } else {
        emitFrom2(queue[n - 1 - e2]);
      }
    }
  }
}
