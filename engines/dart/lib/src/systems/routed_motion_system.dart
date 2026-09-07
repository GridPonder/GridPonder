import '../engine/game_system.dart';
import '../models/direction.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// Advances every tagged mover by one cell after each accepted player turn.
///
/// All intents are computed from one snapshot and committed atomically, so
/// list order cannot change collision outcomes.
class RoutedMotionSystem extends GameSystem {
  const RoutedMotionSystem({required super.id}) : super(type: 'routed_motion');

  @override
  List<GameEvent> executeNpcResolution(LevelState state, GameDefinition game) {
    final config = game.systemConfig(id, {});
    final moverLayerId = config['moverLayer'] as String? ?? 'objects';
    final moverTag = config['moverTag'] as String? ?? 'routed_mover';
    final routeLayerId = config['routeLayer'] as String? ?? 'ground';
    final headingParam = config['headingParam'] as String? ?? 'heading';
    final colorParam = config['colorParam'] as String? ?? 'color';
    final exitLayerId = config['exitLayer'] as String? ?? 'markers';
    final exitTag = config['exitTag'] as String? ?? 'route_exit';
    final exitColorParam = config['exitColorParam'] as String? ?? colorParam;
    final failureVariable =
        config['failureVariable'] as String? ?? 'routedMotionFailures';
    final rawRoutes =
        config['routes'] as Map<String, dynamic>? ?? const <String, dynamic>{};

    final moverLayer = state.board.layers[moverLayerId];
    if (moverLayer == null) return const [];

    final movers = moverLayer
        .entries()
        .where((entry) => game.hasTag(entry.value.kind, moverTag))
        .map((entry) => _Mover(entry.key, entry.value))
        .toList();
    if (movers.isEmpty) return const [];

    final moverByPosition = {for (final mover in movers) mover.position: mover};
    final intents = <_Intent>[];
    final failures = <_Failure>[];

    for (final mover in movers) {
      final headingRaw = mover.entity.param(headingParam);
      Direction heading;
      try {
        heading = Direction.fromJson(headingRaw?.toString() ?? '');
      } on FormatException {
        failures.add(_Failure(mover, mover.position, 'invalid_heading'));
        continue;
      }
      if (!heading.isCardinal) {
        failures.add(_Failure(mover, mover.position, 'invalid_heading'));
        continue;
      }

      final sourceRoad = state.board.getEntity(routeLayerId, mover.position);
      if (sourceRoad == null ||
          !_hasExit(rawRoutes, sourceRoad.kind, heading.toJson())) {
        failures.add(_Failure(mover, mover.position, 'invalid_source_route'));
        continue;
      }

      final target = Position(
        mover.position.x + heading.offset.x,
        mover.position.y + heading.offset.y,
      );
      if (!state.board.isInBounds(target)) {
        failures.add(_Failure(mover, target, 'left_board'));
        continue;
      }

      final targetRoad = state.board.getEntity(routeLayerId, target);
      final nextHeading = targetRoad == null
          ? null
          : _route(rawRoutes, targetRoad.kind, heading.opposite.toJson());
      if (nextHeading == null || !_cardinalNames.contains(nextHeading)) {
        failures.add(_Failure(mover, target, 'disconnected_road'));
        continue;
      }

      final occupant = moverLayer.getAt(target);
      if (occupant != null && !game.hasTag(occupant.kind, moverTag)) {
        failures.add(_Failure(mover, target, 'occupied'));
        continue;
      }

      final exit = state.board.getEntity(exitLayerId, target);
      final isExit = exit != null && game.hasTag(exit.kind, exitTag);
      if (isExit &&
          mover.entity.param(colorParam)?.toString() !=
              exit.param(exitColorParam)?.toString()) {
        failures.add(_Failure(mover, target, 'wrong_exit'));
        continue;
      }

      intents.add(_Intent(mover, target, nextHeading, delivered: isExit));
    }

    final intentsByTarget = <Position, List<_Intent>>{};
    for (final intent in intents) {
      intentsByTarget.putIfAbsent(intent.target, () => []).add(intent);
    }
    for (final entry in intentsByTarget.entries) {
      if (entry.value.length > 1) {
        for (final intent in entry.value) {
          failures.add(_Failure(intent.mover, entry.key, 'same_destination'));
        }
      }
    }

    final intentBySource = {
      for (final intent in intents) intent.mover.position: intent,
    };
    for (final intent in intents) {
      final other = intentBySource[intent.target];
      if (other != null && other.target == intent.mover.position) {
        failures.add(_Failure(intent.mover, intent.target, 'head_on'));
      }
    }

    for (final intent in intents) {
      final occupant = moverByPosition[intent.target];
      if (occupant != null && !intentBySource.containsKey(occupant.position)) {
        failures.add(_Failure(intent.mover, intent.target, 'blocked_by_mover'));
      }
    }

    if (failures.isNotEmpty) {
      final oldValue = (state.variables[failureVariable] as num?)?.toInt() ?? 0;
      final newValue = oldValue + 1;
      state.variables[failureVariable] = newValue;
      return [
        for (final failure in _dedupeFailures(failures))
          GameEvent('routed_motion_failed', {
            'position': failure.target,
            'kind': failure.mover.entity.kind,
            'fromPosition': failure.mover.position,
            'reason': failure.reason,
          }),
        GameEvent.variableChanged(failureVariable, oldValue, newValue),
      ];
    }

    for (final mover in movers) {
      moverLayer.setAt(mover.position, null);
    }

    final events = <GameEvent>[];
    for (final intent in intents) {
      final params = Map<String, dynamic>.from(intent.mover.entity.params)
        ..[headingParam] = intent.nextHeading;
      events.add(
        GameEvent.tileMoved(
          intent.mover.position,
          intent.target,
          intent.mover.entity.kind,
          params: params,
          layer: moverLayerId,
        ),
      );
      if (intent.delivered) {
        events.add(
          GameEvent.objectRemoved(intent.target, intent.mover.entity.kind),
        );
      } else {
        moverLayer.setAt(
          intent.target,
          EntityInstance(intent.mover.entity.kind, params),
        );
      }
    }
    return events;
  }

  String? _route(
    Map<String, dynamic> routes,
    String roadKind,
    String incomingSide,
  ) {
    final raw = routes[roadKind];
    if (raw is! Map) return null;
    final value = raw[incomingSide];
    return value is String ? value : null;
  }

  bool _hasExit(Map<String, dynamic> routes, String roadKind, String heading) {
    final raw = routes[roadKind];
    return raw is Map && raw.values.contains(heading);
  }

  List<_Failure> _dedupeFailures(List<_Failure> failures) {
    final seen = <String>{};
    final result = <_Failure>[];
    for (final failure in failures) {
      final key = '${failure.mover.position.x},${failure.mover.position.y}:'
          '${failure.target.x},${failure.target.y}:${failure.reason}';
      if (seen.add(key)) result.add(failure);
    }
    return result;
  }
}

const _cardinalNames = {'up', 'down', 'left', 'right'};

class _Mover {
  final Position position;
  final EntityInstance entity;
  const _Mover(this.position, this.entity);
}

class _Intent {
  final _Mover mover;
  final Position target;
  final String nextHeading;
  final bool delivered;

  const _Intent(
    this.mover,
    this.target,
    this.nextHeading, {
    required this.delivered,
  });
}

class _Failure {
  final _Mover mover;
  final Position target;
  final String reason;
  const _Failure(this.mover, this.target, this.reason);
}
