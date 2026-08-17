import '../engine/game_system.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';

/// A normalised `sonar` config block.
class _SonarConfig {
  final String sourceLayer;
  final String targetLayer;
  final Map<String, dynamic>? pairing;
  final String variablePrefix;
  final String? aggregate;
  final String aggregateVariable;

  const _SonarConfig({
    required this.sourceLayer,
    required this.targetLayer,
    required this.pairing,
    required this.variablePrefix,
    required this.aggregate,
    required this.aggregateVariable,
  });

  /// Returns null when the system is inert.
  static _SonarConfig? read(Map<String, dynamic> config) {
    final targetLayer = config['targetLayer'];
    if (targetLayer is! String || targetLayer.isEmpty) return null;

    final rawSource = config['sourceLayer'];
    final sourceLayer =
        (rawSource is String && rawSource.isNotEmpty) ? rawSource : 'actors';

    final rawPairing = config['pairing'];
    final pairing = rawPairing is Map<String, dynamic> ? rawPairing : null;

    final rawPrefix = config['variablePrefix'];
    final prefix = rawPrefix is String ? rawPrefix : 'echo_';

    // `metric` is reserved for future distance functions; anything we do not
    // recognise falls back to manhattan rather than raising, so a typo cannot
    // make one engine throw while the other silently continues.
    // An unrecognised reduction degrades to per-kind mode rather than raising,
    // for the same reason `metric` does.
    final rawAggregate = config['aggregate'];
    final aggregate = (rawAggregate == 'sum' ||
            rawAggregate == 'min' ||
            rawAggregate == 'max')
        ? rawAggregate as String
        : null;

    final rawAggVar = config['aggregateVariable'];
    final aggregateVariable = (rawAggVar is String && rawAggVar.isNotEmpty)
        ? rawAggVar
        : '${prefix}total';

    return _SonarConfig(
      sourceLayer: sourceLayer,
      targetLayer: targetLayer,
      pairing: pairing,
      variablePrefix: prefix,
      aggregate: aggregate,
      aggregateVariable: aggregateVariable,
    );
  }
}

/// Combine per-source distances into one crew reading.
///
/// The asymmetry between `sum` and `min`/`max` is deliberate. A partial sum is
/// numerically indistinguishable from a real reading, so a missing target
/// poisons the whole value and must yield -1. A min or max over the sources
/// that *do* have targets is a well-defined answer to the question that
/// reduction asks, so those skip the target-less sources instead.
int _reduce(String mode, List<int> distances) {
  if (distances.isEmpty) return -1;
  if (mode == 'sum') {
    if (distances.any((d) => d < 0)) return -1;
    return distances.reduce((a, b) => a + b);
  }
  final found = distances.where((d) => d >= 0).toList();
  if (found.isEmpty) return -1;
  return mode == 'min'
      ? found.reduce((a, b) => a < b ? a : b)
      : found.reduce((a, b) => a > b ? a : b);
}

/// SonarSystem — see docs/dsl/04_systems.md.
///
/// Writes a distance reading per source entity kind into `state.variables`
/// every turn: for each source, the distance to its paired (or nearest)
/// target entity. The system is **read-only with respect to the board** — it
/// mutates variables and nothing else, and emits no events.
///
/// This is the generic hook for "warmer/colder" sensing: a game can hide the
/// target layer from the player and let them locate it by moving and reading,
/// or use the reading as a proximity alarm, a heat-seeker, or a scoring input.
///
/// Phase: `npc_resolution`. That is the last phase running unconditionally for
/// every system on every turn, after action, movement and cascade resolution
/// have all settled the board, and before goal evaluation. A reading therefore
/// always describes the board the player is looking at when the turn ends.
///
/// Because readings live in `state.variables` they are inside `toKey()`, so
/// undo, `previewTurn` and solver dedup work with no extra handling. They are
/// a pure function of board state, so they add no new state distinctions and
/// cannot inflate a solver's search space.
///
/// Tolerance contract (both engines must agree, so it is stated rather than
/// implied): a missing or non-string `targetLayer` makes the system **inert**
/// — it writes nothing at all. A non-object `pairing` is treated as absent,
/// which selects nearest-target-of-any-kind mode. A `metric` other than
/// `"manhattan"` falls back to `"manhattan"` rather than raising. A
/// non-string `variablePrefix` falls back to `"echo_"`. When a source kind
/// has no reachable target (no target entities, or none paired to it) its
/// variable is set to `-1` rather than being left unwritten, so a level can
/// never read a stale value from a previous turn.
///
/// Two source entities sharing a kind both write the same variable; the value
/// is the **minimum** over them, so the reading is deterministic regardless of
/// iteration order.
///
/// An `aggregate` of `"sum"`, `"min"` or `"max"` makes the system write a
/// single combined reading to `aggregateVariable` (default
/// `variablePrefix + "total"`) instead of one variable per source kind; any
/// other value, or none, selects per-kind mode. A non-string
/// `aggregateVariable` falls back to the default. Under `sum` a single source
/// without a target makes the whole reading `-1`, because a partial sum is
/// numerically indistinguishable from a real one; `min` and `max` instead skip
/// target-less sources and return `-1` only when no source has a target. An
/// empty source layer reads `-1`; a *missing* source layer leaves the system
/// inert, exactly as today.
///
/// One number reducing N sources is one equation in N unknowns, and under
/// lockstep movement consecutive readings are redundant — so a pack using an
/// aggregate for deduction must supply asymmetry through terrain that stops
/// some sources and not others. A gauge over sources that always move together
/// yields no information at all.
class SonarSystem extends GameSystem {
  const SonarSystem({required super.id}) : super(type: 'sonar');

  @override
  List<GameEvent> executeNpcResolution(
    LevelState state,
    GameDefinition game,
  ) {
    final cfg = _SonarConfig.read(game.systemConfig(id, {}));
    if (cfg == null) return const [];

    final board = state.board;
    final sourceLayer = board.layers[cfg.sourceLayer];
    if (sourceLayer == null) return const [];

    final targetLayer = board.layers[cfg.targetLayer];
    final targets = targetLayer?.entries().toList() ?? const [];

    final aggregate = cfg.aggregate;
    final distances = <int>[];
    final readings = <String, int>{};
    for (final source in sourceLayer.entries()) {
      final wanted = cfg.pairing?[source.value.kind] as String?;
      var best = -1;
      for (final target in targets) {
        if (wanted != null && target.value.kind != wanted) continue;
        final dist = (source.key.x - target.key.x).abs() +
            (source.key.y - target.key.y).abs();
        if (best < 0 || dist < best) best = dist;
      }

      if (aggregate != null) {
        // In aggregate mode the per-source distance is an input to the
        // reduction and is never published on its own — a pack wanting both
        // surfaces declares two sonar instances.
        distances.add(best);
        continue;
      }

      // Two sources of the same kind collapse to the minimum, so the written
      // value does not depend on iteration order. -1 (no target) loses to any
      // real distance.
      final name = cfg.variablePrefix + source.value.kind;
      final prev = readings[name];
      if (prev == null || prev < 0 || (best >= 0 && best < prev)) {
        readings[name] = best;
      }
    }

    if (aggregate != null) {
      state.variables[cfg.aggregateVariable] = _reduce(aggregate, distances);
      return const [];
    }

    state.variables.addAll(readings);
    return const [];
  }
}
