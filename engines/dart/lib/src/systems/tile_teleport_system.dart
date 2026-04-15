import '../engine/game_system.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// Teleports tiles that are resting on a teleporter cell to the paired cell
/// (if the destination is empty).
///
/// Teleporter cells are ground-layer entities tagged "teleport".  Pairs are
/// identified by a matching "channel" param — the same convention used by
/// [PortalsSystem] for avatar teleportation.
///
/// Runs in Phase 6 (NPC resolution) after [QueuedEmittersSystem], so tiles
/// emitted by pipes in the same turn are also subject to teleportation.
///
/// Behaviour:
///   - Bidirectional: a tile on either endpoint is moved to the other.
///   - No merge: teleportation only fires when the destination is empty.
///   - Single pass: each portal pair fires at most once per turn.
class TileTeleportSystem extends GameSystem {
  const TileTeleportSystem({required super.id})
      : super(type: 'tile_teleport');

  @override
  List<GameEvent> executeNpcResolution(
    LevelState state,
    GameDefinition game,
  ) {
    final board = state.board;
    final groundLayer = board.layers['ground'];
    if (groundLayer == null) return const [];

    final config = game.systemConfig(id, {});
    final layerId = config['layer'] as String? ?? 'objects';
    final layer = board.layers[layerId];
    if (layer == null) return const [];

    // Collect teleporter positions grouped by channel.
    final Map<String, List<Position>> channelPositions = {};
    for (final entry in groundLayer.entries()) {
      if (!game.hasTag(entry.value.kind, 'teleport')) continue;
      final channel = entry.value.param('channel') as String? ?? '';
      channelPositions.putIfAbsent(channel, () => []).add(entry.key);
    }

    if (channelPositions.isEmpty) return const [];

    final events = <GameEvent>[];

    for (final positions in channelPositions.values) {
      if (positions.length != 2) continue;
      final p1 = positions[0];
      final p2 = positions[1];

      final e1 = layer.getAt(p1);
      final e2 = layer.getAt(p2);

      if (e1 != null && e2 == null) {
        layer.setAt(p2, e1);
        layer.setAt(p1, null);
        events.add(GameEvent.objectRemoved(p1, e1.kind));
        events.add(GameEvent.objectPlaced(p2, e1.kind, e1.params));
      } else if (e2 != null && e1 == null) {
        layer.setAt(p1, e2);
        layer.setAt(p2, null);
        events.add(GameEvent.objectRemoved(p2, e2.kind));
        events.add(GameEvent.objectPlaced(p1, e2.kind, e2.params));
      }
    }

    return events;
  }
}
