import '../engine/game_system.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';
import 'runtime_variable.dart';

/// TerrainEditSystem — see docs/dsl/04_systems.md.
///
/// Consumes a position-carrying action and writes one entity kind onto a
/// layer, optionally spending from a runtime budget and optionally guarding
/// what may be overwritten. This is the generic hook for player-driven
/// terrain change: the rules engine cannot express it, because there is no
/// "player acted at position" event — every action must be consumed by a
/// system.
///
/// The position normally comes from the action's own `position` param, but
/// when that's absent and `config.positionVariable` is set, it's read from
/// `state.variables` instead — lets a zero-param button (e.g. a "place here"
/// action fired after a separate select/aim step) target whatever position
/// another action last wrote to that variable.
class TerrainEditSystem extends GameSystem {
  const TerrainEditSystem({required super.id}) : super(type: 'terrain_edit');

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, {});
    final editAction = config['action'] as String? ?? 'place';
    if (action.actionId != editAction) return const [];

    var pos = _parsePosition(action.params['position']);
    if (pos == null) {
      // Falls back to a runtime variable when the action itself carries no
      // position — lets a zero-param button act on whatever a prior
      // position-carrying action (e.g. `tap_cell`) last selected.
      final posVar = config['positionVariable'] as String?;
      if (posVar != null) pos = _parsePosition(state.variables[posVar]);
    }
    if (pos == null) return const [];
    if (!state.board.isInBounds(pos)) return const [];

    final budgetVar = config['budgetVariable'] as String?;
    var remaining = 0;
    if (budgetVar != null) {
      remaining = readIntVariable(state, budgetVar);
      if (remaining <= 0) return const [];
    }

    final layerId = config['layer'] as String;
    final current = state.board.getEntity(layerId, pos);
    final fromKind = config['fromKind'] as String?;
    if (fromKind != null && current?.kind != fromKind) return const [];

    final toKind = config['kind'] as String;
    state.board.setEntity(layerId, pos, EntityInstance(toKind));
    if (budgetVar != null) state.variables[budgetVar] = remaining - 1;

    // "" rather than null for an empty cell, matching the Python payload.
    return [
      GameEvent.cellTransformed(pos, current?.kind ?? '', toKind, layerId),
    ];
  }

  /// Type guard, not a try/catch: refuses non-list/short shapes and
  /// non-numeric elements instead of throwing. Also refuses non-finite
  /// numbers (`double.infinity`, `double.nan`) before calling `.toInt()`:
  /// only NaN and Infinity throw `UnsupportedError` there — a finite double,
  /// however large, saturates to the `int` range instead of throwing — so
  /// this guard exists specifically for the non-finite case, which would
  /// otherwise turn a malformed action into a raise instead of a refusal.
  Position? _parsePosition(dynamic raw) {
    if (raw is List && raw.length >= 2) {
      final x = raw[0];
      final y = raw[1];
      if (x is num && y is num && x.isFinite && y.isFinite) {
        return Position(x.toInt(), y.toInt());
      }
    }
    return null;
  }
}
