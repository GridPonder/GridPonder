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
          board, mco, events, queue,
          exitPos, spawnPos, exit2Pos, spawn2Pos,
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

  /// Physical slot-based bidirectional pipe emission.
  ///
  /// Items occupy cells within the pipe and move one step per turn toward
  /// their nearest exit.  An item only exits when it is already at the exit
  /// cell at the start of the turn.
  ///
  /// State is stored in `mco.params['pipeSlots']` — a list of length
  /// `pipeLength` (== mco.cells.length) where each entry is a queue value
  /// (int) or null.  Initialised on first call from the `queue` param.
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
    final pipeLen = mco.cells.length;

    // Initialise pipeSlots on first invocation.
    if (mco.params['pipeSlots'] == null) {
      final slots = List<int?>.filled(pipeLen, null);
      for (int i = 0; i < queue.length && i < pipeLen; i++) {
        slots[i] = queue[i] as int?;
      }
      mco.params['pipeSlots'] = slots;
    }

    final slots = (mco.params['pipeSlots'] as List<dynamic>)
        .map((e) => e as int?)
        .toList();
    final last = pipeLen - 1;

    // Check whether anything remains.
    if (slots.every((v) => v == null)) return;

    // A spawn cell is considered clear when it carries no object entity.
    bool clear(Position exit, Position spawn) =>
        board.getEntity('objects', exit) == null &&
        (spawn == exit || board.getEntity('objects', spawn) == null);

    final can1 = clear(exit1Pos, spawn1Pos);
    final can2 = clear(exit2Pos, spawn2Pos);

    // ── Phase 1: Emit items already at exit cells ───────────────────────
    if (slots[0] != null && can1) {
      final val = slots[0]!;
      final p = <String, dynamic>{'value': val};
      board.setEntity('objects', spawn1Pos, EntityInstance('number', p));
      events.add(GameEvent.itemReleased(mco.id, 'number', spawn1Pos, p));
      slots[0] = null;
    }
    if (slots[last] != null && can2) {
      final val = slots[last]!;
      final p = <String, dynamic>{'value': val};
      board.setEntity('objects', spawn2Pos, EntityInstance('number', p));
      events.add(GameEvent.itemReleased(mco.id, 'number', spawn2Pos, p));
      slots[last] = null;
    }

    // ── Phase 2: Move remaining items one step toward their nearest exit ─
    // Process from both ends inward so moves don't collide.
    // Left-moving items (closer to exit1): process left-to-right.
    // Right-moving items (closer to exit2): process right-to-left.
    // Midpoint items: apply stuck rule.
    final newSlots = List<int?>.filled(pipeLen, null);

    // Mark occupied destinations to prevent collisions.
    for (int i = 0; i < pipeLen; i++) {
      if (slots[i] == null) continue;

      final distToE1 = i;
      final distToE2 = last - i;

      int target;
      if (distToE1 < distToE2) {
        // Closer to exit1 → move left.
        target = i - 1;
      } else if (distToE2 < distToE1) {
        // Closer to exit2 → move right.
        target = i + 1;
      } else {
        // Equidistant (midpoint). Apply stuck rule.
        if (can1 && !can2) {
          target = i - 1; // move toward open exit1
        } else if (can2 && !can1) {
          target = i + 1; // move toward open exit2
        } else {
          target = i; // stuck (both open or both blocked)
        }
      }

      // Clamp to pipe bounds and avoid collisions.
      if (target < 0) target = 0;
      if (target > last) target = last;
      if (newSlots[target] != null) target = i; // blocked by another item

      newSlots[target] = slots[i];
    }

    // Write back.
    mco.params['pipeSlots'] = newSlots;
  }
}
