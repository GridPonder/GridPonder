import '../engine/game_system.dart';
import '../models/direction.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';

/// Colored gate cells that only admit a mover travelling light. See
/// docs/dsl/04_systems.md §2.28.
///
/// An empty mover may enter any gate, a mover carrying cargo only a gate whose
/// color matches every item it carries, and never with more than `maxCargo`
/// items. The cargo is the body of a `trailing_body` system, read from that
/// system's state.
///
/// Runs in action resolution and must be listed before the movement system it
/// guards: a refused move is vetoed, so the turn is not spent.
class CargoGateSystem extends GameSystem {
  const CargoGateSystem({required super.id}) : super(type: 'cargo_gate');

  @override
  List<GameEvent> executeActionResolution(
      GameAction action, LevelState state, GameDefinition game) {
    final config = game.systemConfig(id, null);
    if (action.actionId != (config['moveAction'] as String? ?? 'move')) {
      return const [];
    }
    final dirStr = action.params['direction'] as String?;
    final avatar = state.avatar;
    final pos = avatar.position;
    if (dirStr == null || !avatar.enabled || pos == null) return const [];
    final target = pos.moved(Direction.fromJson(dirStr));
    if (!state.board.isInBounds(target)) return const [];

    final gateLayer = config['gateLayer'] as String? ?? 'ground';
    final gate = state.board.getEntity(gateLayer, target);
    if (gate == null ||
        !game.hasTag(gate.kind, config['gateTag'] as String? ?? 'cargo_gate')) {
      return const [];
    }

    final cargo = _cargoColors(state, config);
    final gateColor = gate.param(config['gateParam'] as String? ?? 'color');
    final maxCargo = (config['maxCargo'] as num?)?.toInt() ?? 1;
    final allowed = cargo.isEmpty ||
        (cargo.length <= maxCargo && cargo.every((c) => c == gateColor));
    if (allowed) return const [];
    return [
      GameEvent.actionVetoed(),
      GameEvent.cellBlocked(target, gateLayer, 'cargo', gate.kind),
    ];
  }

  /// Colors of the items the mover carries, one per body segment.
  static List<Object?> _cargoColors(
      LevelState state, Map<String, dynamic> config) {
    final bodySystem = config['cargoSystem'] as String?;
    if (bodySystem == null) return const [];
    final segments =
        state.variables['_trailingBody_${bodySystem}_segments'] as List? ??
            const [];
    return [for (final s in segments) (s as Map)['color']];
  }
}
