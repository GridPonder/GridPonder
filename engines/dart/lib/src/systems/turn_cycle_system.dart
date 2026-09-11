import '../engine/game_system.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';

/// Advances configured board entities through a deterministic kind cycle.
///
/// Trigger actions are recorded during action resolution. The actual cycle is
/// applied at this system's position in NPC resolution. Systems declared
/// earlier in `game.json` observe the old kind; systems declared later observe
/// the new kind.
class TurnCycleSystem extends GameSystem {
  // PhaseRunner creates a fresh system list for each turn. This flag only
  // carries the accepted action's decision into that turn's NPC phase.
  bool _advanceThisTurn = false;

  TurnCycleSystem({required super.id}) : super(type: 'turn_cycle');

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, {});
    final rawTriggerActions = config['triggerActions'];
    final triggerActions =
        (rawTriggerActions is List ? rawTriggerActions : const <dynamic>[])
            .map((value) => value.toString())
            .toSet();
    _advanceThisTurn =
        triggerActions.isEmpty || triggerActions.contains(action.actionId);
    return const [];
  }

  @override
  List<GameEvent> executeNpcResolution(
    LevelState state,
    GameDefinition game,
  ) {
    if (!_advanceThisTurn) return const [];

    final config = game.systemConfig(id, {});
    final layerId =
        config['layer'] is String ? config['layer'] as String : 'markers';
    final layer = state.board.layers[layerId];
    final cycles = config['cycles'];
    if (layer == null) return const [];
    if (cycles is! Map) return const [];

    final events = <GameEvent>[];
    for (final entry in layer.entries().toList()) {
      final nextKind = cycles[entry.value.kind];
      if (nextKind is! String || !game.entityKinds.containsKey(nextKind)) {
        continue;
      }
      layer.setAt(
        entry.key,
        EntityInstance(
          nextKind,
          Map<String, dynamic>.from(entry.value.params),
        ),
      );
      events.add(
        GameEvent.cellTransformed(
          entry.key,
          entry.value.kind,
          nextKind,
          layerId,
        ),
      );
    }
    return events;
  }
}
