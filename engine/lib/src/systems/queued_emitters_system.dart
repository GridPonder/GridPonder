import '../engine/game_system.dart';
import '../models/direction.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';
import '../models/entity.dart';

/// Releases one item per turn from each queued-emitter MCO whose front cell
/// (exitPosition + exitDirection) is empty.  Runs in Phase 6 (NPC resolution)
/// so it fires once per turn, after all slides and cascades have settled.
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

      // Determine the spawn cell: one step in exitDirection from exitPos.
      // If no exitDirection is given, spawn at exitPos itself (legacy).
      final exitDirStr = mco.params['exitDirection'] as String?;
      final spawnPos = exitDirStr != null
          ? exitPos.moved(Direction.fromJson(exitDirStr))
          : exitPos;

      // Only emit when both the exit cell and the spawn cell are clear.
      if (board.getEntity('objects', exitPos) != null) continue;
      if (spawnPos != exitPos &&
          board.getEntity('objects', spawnPos) != null) continue;

      final queue = mco.params['queue'] as List<dynamic>? ?? [];
      final currentIndex = mco.params['currentIndex'] as int? ?? 0;
      if (currentIndex >= queue.length) continue;

      final nextValue = queue[currentIndex];
      final itemParams = <String, dynamic>{'value': nextValue};
      board.setEntity('objects', spawnPos, EntityInstance('number', itemParams));
      mco.params['currentIndex'] = currentIndex + 1;

      events.add(GameEvent.itemReleased(mco.id, 'number', spawnPos, itemParams));
    }

    return events;
  }
}
