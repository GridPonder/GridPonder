import '../engine/game_system.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// A synchronous threshold cascade over parameterised board cells.
///
/// The clicked cell gains charge, then every unstable cell explodes once from
/// the same per-wave snapshot. Threshold subtraction and all incoming charge
/// are committed together. The complete transition stays in action resolution
/// so an over-limit cascade can veto and roll back the whole turn.
class CascadeCellsSystem extends GameSystem {
  final Map<String, dynamic>? config;

  const CascadeCellsSystem({required super.id, this.config})
      : super(type: 'cascade_cells');

  static const Map<String, List<List<int>>> _defaultKernels = {
    'plus': [
      [0, -1],
      [1, 0],
      [0, 1],
      [-1, 0],
    ],
    'x': [
      [-1, -1],
      [1, -1],
      [1, 1],
      [-1, 1],
    ],
    'h': [
      [-1, 0],
      [1, 0],
    ],
    'v': [
      [0, -1],
      [0, 1],
    ],
  };

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final effectiveConfig = config ?? game.systemConfig(id, {});
    final actionId = effectiveConfig['action'] is String
        ? effectiveConfig['action'] as String
        : 'tap_cell';
    if (action.actionId != actionId) return const [];

    final clicked = _parsePosition(action.params['position']);
    if (clicked == null || !state.board.isInBounds(clicked)) {
      return [GameEvent.actionVetoed()];
    }

    final layerId = effectiveConfig['cellLayer'] is String
        ? effectiveConfig['cellLayer'] as String
        : 'objects';
    final cellTag = effectiveConfig['cellTag'] is String
        ? effectiveConfig['cellTag'] as String
        : 'cascade_cell';
    final chargeParam = effectiveConfig['chargeParam'] is String
        ? effectiveConfig['chargeParam'] as String
        : 'charge';
    final thresholdParam = effectiveConfig['thresholdParam'] is String
        ? effectiveConfig['thresholdParam'] as String
        : 'threshold';
    final kernelParam = effectiveConfig['kernelParam'] is String
        ? effectiveConfig['kernelParam'] as String
        : 'kernel';
    if ([layerId, cellTag, chargeParam, thresholdParam, kernelParam]
        .any((value) => value.isEmpty)) {
      return [GameEvent.actionVetoed()];
    }

    final clickDelta = effectiveConfig['clickDelta'] ?? 1;
    final maxWaves = effectiveConfig['maxWaves'] ?? 1000;
    if (clickDelta is! int || clickDelta <= 0) {
      return [GameEvent.actionVetoed()];
    }
    if (maxWaves is! int || maxWaves <= 0) {
      return [GameEvent.actionVetoed()];
    }

    final kernels = _parseKernels(effectiveConfig['kernels']);
    if (kernels == null) return [GameEvent.actionVetoed()];
    final layer = state.board.layers[layerId];
    if (layer == null) return [GameEvent.actionVetoed()];

    final initial = _snapshotCells(
      state,
      game,
      layerId,
      cellTag,
      chargeParam,
      thresholdParam,
      kernelParam,
      kernels,
    );
    if (initial == null) return [GameEvent.actionVetoed()];
    final clickedData = initial[clicked];
    if (clickedData == null) return [GameEvent.actionVetoed()];

    final events = <GameEvent>[];
    final clickedCharge = clickedData.charge;
    final newClickedCharge = clickedCharge + clickDelta;
    _setCharge(
      state,
      layerId,
      clicked,
      clickedData.entity,
      chargeParam,
      newClickedCharge,
    );
    events.add(GameEvent.cellCharged(
      clicked,
      beforeCharge: clickedCharge,
      afterCharge: newClickedCharge,
      delta: clickDelta,
      wave: 0,
      source: 'click',
      layer: layerId,
    ));

    var completedWaves = 0;
    while (true) {
      final snapshot = _snapshotCells(
        state,
        game,
        layerId,
        cellTag,
        chargeParam,
        thresholdParam,
        kernelParam,
        kernels,
      );
      if (snapshot == null) return [GameEvent.actionVetoed()];

      final unstable = snapshot.entries
          .where((entry) => entry.value.charge >= entry.value.threshold)
          .map((entry) => entry.key)
          .toList()
        ..sort(_comparePositions);
      if (unstable.isEmpty) {
        events.add(GameEvent.cascadeSettled(completedWaves));
        return events;
      }
      if (completedWaves >= maxWaves) {
        return [GameEvent.actionVetoed()];
      }

      final wave = completedWaves + 1;
      events.add(GameEvent.cascadeWaveStarted(wave, unstable));

      final incoming = <Position, int>{};
      final afterSubtraction = <Position, int>{
        for (final entry in snapshot.entries) entry.key: entry.value.charge,
      };

      for (final position in unstable) {
        final data = snapshot[position]!;
        final remainder = data.charge - data.threshold;
        afterSubtraction[position] = remainder;
        events.add(GameEvent.cellExploded(
          position,
          beforeCharge: data.charge,
          afterCharge: remainder,
          threshold: data.threshold,
          kernel: data.kernel,
          wave: wave,
          layer: layerId,
        ));
        for (final offset in kernels[data.kernel]!) {
          final destination =
              Position(position.x + offset.x, position.y + offset.y);
          if (snapshot.containsKey(destination)) {
            incoming[destination] = (incoming[destination] ?? 0) + 1;
          }
        }
      }

      final positions = snapshot.keys.toList()..sort(_comparePositions);
      for (final position in positions) {
        final data = snapshot[position]!;
        final base = afterSubtraction[position]!;
        final delta = incoming[position] ?? 0;
        final after = base + delta;
        _setCharge(
          state,
          layerId,
          position,
          data.entity,
          chargeParam,
          after,
        );
        if (delta != 0) {
          events.add(GameEvent.cellCharged(
            position,
            beforeCharge: base,
            afterCharge: after,
            delta: delta,
            wave: wave,
            source: 'cascade',
            layer: layerId,
          ));
        }
      }

      events.add(GameEvent.cascadeWaveCompleted(wave, unstable));
      completedWaves = wave;
    }
  }

  static Position? _parsePosition(dynamic raw) {
    if (raw is List && raw.length >= 2 && raw[0] is num && raw[1] is num) {
      return Position((raw[0] as num).toInt(), (raw[1] as num).toInt());
    }
    if (raw is Map && raw['x'] is num && raw['y'] is num) {
      return Position((raw['x'] as num).toInt(), (raw['y'] as num).toInt());
    }
    return null;
  }

  static Map<String, List<Position>>? _parseKernels(dynamic raw) {
    final source = raw == null ? _defaultKernels : raw;
    if (source is! Map || source.isEmpty) return null;
    final parsed = <String, List<Position>>{};
    for (final entry in source.entries) {
      final name = entry.key;
      final offsets = entry.value;
      if (name is! String || name.isEmpty || offsets is! List) return null;
      final converted = <Position>[];
      for (final offset in offsets) {
        if (offset is! List ||
            offset.length != 2 ||
            offset[0] is! int ||
            offset[1] is! int) {
          return null;
        }
        converted.add(Position(offset[0] as int, offset[1] as int));
      }
      parsed[name] = converted;
    }
    return parsed;
  }

  static Map<Position, _CascadeCell>? _snapshotCells(
    LevelState state,
    GameDefinition game,
    String layerId,
    String cellTag,
    String chargeParam,
    String thresholdParam,
    String kernelParam,
    Map<String, List<Position>> kernels,
  ) {
    final layer = state.board.layers[layerId];
    if (layer == null) return null;
    final cells = <Position, _CascadeCell>{};
    for (final entry in layer.entries()) {
      final entity = entry.value;
      if (!game.hasTag(entity.kind, cellTag)) continue;
      final charge = entity.param(chargeParam);
      final threshold = entity.param(thresholdParam);
      final kernel = entity.param(kernelParam);
      if (charge is! int ||
          charge < 0 ||
          threshold is! int ||
          threshold <= 0 ||
          kernel is! String ||
          !kernels.containsKey(kernel)) {
        return null;
      }
      cells[entry.key] = _CascadeCell(entity, charge, threshold, kernel);
    }
    return cells;
  }

  static void _setCharge(
    LevelState state,
    String layerId,
    Position position,
    EntityInstance entity,
    String chargeParam,
    int charge,
  ) {
    final params = Map<String, dynamic>.from(entity.params);
    params[chargeParam] = charge;
    state.board.setEntity(
      layerId,
      position,
      EntityInstance(entity.kind, params),
    );
  }

  static int _comparePositions(Position a, Position b) {
    final row = a.y.compareTo(b.y);
    return row != 0 ? row : a.x.compareTo(b.x);
  }
}

class _CascadeCell {
  final EntityInstance entity;
  final int charge;
  final int threshold;
  final String kernel;

  const _CascadeCell(this.entity, this.charge, this.threshold, this.kernel);
}
