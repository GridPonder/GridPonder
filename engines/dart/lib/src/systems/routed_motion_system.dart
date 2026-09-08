import '../engine/game_system.dart';
import '../models/direction.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// Advances tagged movers along deterministic route tiles after each turn.
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
    final exitRequiresRoute = config['exitRequiresRoute'] as bool? ?? true;
    final gateLayerId = config['gateLayer'] as String?;
    final gateClosedTag = config['gateClosedTag'] as String? ?? 'route_closed';
    final gateEntrySideParam =
        config['gateEntrySideParam'] as String? ?? 'entrySide';
    final failureVariable =
        config['failureVariable'] as String? ?? 'routedMotionFailures';
    final rawRoutes =
        config['routes'] as Map<String, dynamic>? ?? const <String, dynamic>{};
    final movementMode = config['movementMode'] as String? ?? 'single_step';

    final moverLayer = state.board.layers[moverLayerId];
    if (moverLayer == null) return const [];

    final movers = moverLayer
        .entries()
        .where((entry) => game.hasTag(entry.value.kind, moverTag))
        .map((entry) => _Mover(entry.key, entry.value))
        .toList();
    if (movers.isEmpty) return const [];

    if (movementMode == 'until_blocked') {
      return _executeUntilBlocked(
        state,
        game,
        movers,
        moverLayerId: moverLayerId,
        moverTag: moverTag,
        routeLayerId: routeLayerId,
        headingParam: headingParam,
        colorParam: colorParam,
        exitLayerId: exitLayerId,
        exitTag: exitTag,
        exitColorParam: exitColorParam,
        exitRequiresRoute: exitRequiresRoute,
        gateLayerId: gateLayerId,
        gateClosedTag: gateClosedTag,
        gateEntrySideParam: gateEntrySideParam,
        failureVariable: failureVariable,
        routes: rawRoutes,
        blockedBehavior: config['blockedBehavior'] as String? ?? 'fail',
        allowUTurns: config['allowUTurns'] as bool? ?? true,
        maxTravelSteps: config['maxTravelSteps'] as int?,
      );
    }

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

      final exit = state.board.getEntity(exitLayerId, target);
      final isExit = exit != null && game.hasTag(exit.kind, exitTag);
      final exitMatches = isExit &&
          mover.entity.param(colorParam)?.toString() ==
              exit.param(exitColorParam)?.toString();
      final bypassTargetRoute = exitMatches && !exitRequiresRoute;
      final targetRoad = state.board.getEntity(routeLayerId, target);
      var nextHeading = targetRoad == null
          ? null
          : _route(rawRoutes, targetRoad.kind, heading.opposite.toJson());
      if (bypassTargetRoute) nextHeading = heading.toJson();
      if (!bypassTargetRoute &&
          (nextHeading == null || !_cardinalNames.contains(nextHeading))) {
        failures.add(_Failure(mover, target, 'disconnected_road'));
        continue;
      }

      if (_gateIsClosed(
        state,
        game,
        target,
        heading.opposite.toJson(),
        gateLayerId,
        gateClosedTag,
        gateEntrySideParam,
      )) {
        failures.add(_Failure(mover, target, 'closed_gate'));
        continue;
      }

      final occupant = moverLayer.getAt(target);
      if (occupant != null && !game.hasTag(occupant.kind, moverTag)) {
        failures.add(_Failure(mover, target, 'occupied'));
        continue;
      }

      if (isExit &&
          mover.entity.param(colorParam)?.toString() !=
              exit.param(exitColorParam)?.toString()) {
        failures.add(_Failure(mover, target, 'wrong_exit'));
        continue;
      }

      intents.add(_Intent(mover, target, nextHeading!, delivered: isExit));
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

  List<GameEvent> _executeUntilBlocked(
    LevelState state,
    GameDefinition game,
    List<_Mover> movers, {
    required String moverLayerId,
    required String moverTag,
    required String routeLayerId,
    required String headingParam,
    required String colorParam,
    required String exitLayerId,
    required String exitTag,
    required String exitColorParam,
    required bool exitRequiresRoute,
    required String? gateLayerId,
    required String gateClosedTag,
    required String gateEntrySideParam,
    required String failureVariable,
    required Map<String, dynamic> routes,
    required String blockedBehavior,
    required bool allowUTurns,
    required int? maxTravelSteps,
  }) {
    final moverLayer = state.board.layers[moverLayerId]!;
    final flows = <_FlowMover>[
      for (var i = 0; i < movers.length; i++)
        _FlowMover(i, movers[i].position, movers[i].entity),
    ];
    final blockedEvents = <GameEvent>[];
    final failureEvents = <_Failure>[];
    final seenStates = <String>{};
    final defaultLimit =
        state.board.width * state.board.height * 4 * flows.length;
    final travelLimit = maxTravelSteps != null && maxTravelSteps > 0
        ? maxTravelSteps
        : (defaultLimit > 0 ? defaultLimit : 1);
    var rounds = 0;

    while (flows.any((flow) => flow.active)) {
      final signature = _flowSignature(flows, headingParam);
      if (!seenStates.add(signature)) {
        for (final flow in flows.where((flow) => flow.active)) {
          flow.active = false;
          blockedEvents.add(_blockedEvent(flow, flow.position, 'route_cycle'));
        }
        break;
      }
      if (rounds >= travelLimit) {
        for (final flow in flows.where((flow) => flow.active)) {
          flow.active = false;
          blockedEvents.add(_blockedEvent(flow, flow.position, 'travel_limit'));
        }
        break;
      }
      rounds++;

      final flowByPosition = {
        for (final flow in flows.where((flow) => !flow.delivered))
          flow.position: flow,
      };
      final intents = <_FlowMover, _FlowIntent>{};
      final blocked = <_FlowMover, _Failure>{};

      for (final flow in flows.where((flow) => flow.active)) {
        final headingRaw = flow.entity.param(headingParam);
        Direction heading;
        try {
          heading = Direction.fromJson(headingRaw?.toString() ?? '');
        } on FormatException {
          blocked[flow] = _Failure(
            _Mover(flow.position, flow.entity),
            flow.position,
            'invalid_heading',
          );
          continue;
        }
        if (!heading.isCardinal) {
          blocked[flow] = _Failure(
            _Mover(flow.position, flow.entity),
            flow.position,
            'invalid_heading',
          );
          continue;
        }

        final sourceRoad = state.board.getEntity(routeLayerId, flow.position);
        if (sourceRoad == null ||
            !_hasExit(routes, sourceRoad.kind, heading.toJson())) {
          blocked[flow] = _Failure(
            _Mover(flow.position, flow.entity),
            flow.position,
            'invalid_source_route',
          );
          continue;
        }

        final target = Position(
          flow.position.x + heading.offset.x,
          flow.position.y + heading.offset.y,
        );
        if (!state.board.isInBounds(target)) {
          blocked[flow] = _Failure(
            _Mover(flow.position, flow.entity),
            target,
            'left_board',
          );
          continue;
        }

        final exit = state.board.getEntity(exitLayerId, target);
        final isExit = exit != null && game.hasTag(exit.kind, exitTag);
        final exitMatches = isExit &&
            flow.entity.param(colorParam)?.toString() ==
                exit.param(exitColorParam)?.toString();
        final bypassTargetRoute = exitMatches && !exitRequiresRoute;
        final targetRoad = state.board.getEntity(routeLayerId, target);
        var nextHeading = targetRoad == null
            ? null
            : _route(routes, targetRoad.kind, heading.opposite.toJson());
        if (bypassTargetRoute) nextHeading = heading.toJson();
        if (!bypassTargetRoute &&
            (nextHeading == null || !_cardinalNames.contains(nextHeading))) {
          blocked[flow] = _Failure(
            _Mover(flow.position, flow.entity),
            target,
            'disconnected_road',
          );
          continue;
        }
        if (_gateIsClosed(
          state,
          game,
          target,
          heading.opposite.toJson(),
          gateLayerId,
          gateClosedTag,
          gateEntrySideParam,
        )) {
          blocked[flow] = _Failure(
            _Mover(flow.position, flow.entity),
            target,
            'closed_gate',
          );
          continue;
        }
        if (!allowUTurns && nextHeading == heading.opposite.toJson()) {
          blocked[flow] = _Failure(
            _Mover(flow.position, flow.entity),
            target,
            'u_turn',
          );
          continue;
        }

        final occupant = moverLayer.getAt(target);
        if (occupant != null && !game.hasTag(occupant.kind, moverTag)) {
          blocked[flow] = _Failure(
            _Mover(flow.position, flow.entity),
            target,
            'occupied',
          );
          continue;
        }

        if (isExit &&
            flow.entity.param(colorParam)?.toString() !=
                exit.param(exitColorParam)?.toString()) {
          blocked[flow] = _Failure(
            _Mover(flow.position, flow.entity),
            target,
            'wrong_exit',
          );
          continue;
        }

        intents[flow] = _FlowIntent(flow, target, nextHeading!, isExit);
      }

      final byTarget = <Position, List<_FlowIntent>>{};
      for (final intent in intents.values) {
        byTarget.putIfAbsent(intent.target, () => []).add(intent);
      }
      for (final entry in byTarget.entries) {
        if (entry.value.length < 2) continue;
        for (final intent in entry.value) {
          blocked[intent.flow] = _Failure(
            _Mover(intent.flow.position, intent.flow.entity),
            entry.key,
            'same_destination',
          );
        }
      }

      for (final intent in intents.values) {
        final other = flowByPosition[intent.target];
        final otherIntent = other == null ? null : intents[other];
        if (otherIntent != null && otherIntent.target == intent.flow.position) {
          blocked[intent.flow] = _Failure(
            _Mover(intent.flow.position, intent.flow.entity),
            intent.target,
            'head_on',
          );
        }
      }

      var propagated = true;
      while (propagated) {
        propagated = false;
        for (final intent in intents.values) {
          if (blocked.containsKey(intent.flow)) continue;
          final occupant = flowByPosition[intent.target];
          if (occupant == null) continue;
          if (!intents.containsKey(occupant) || blocked.containsKey(occupant)) {
            blocked[intent.flow] = _Failure(
              _Mover(intent.flow.position, intent.flow.entity),
              intent.target,
              'blocked_by_mover',
            );
            propagated = true;
          }
        }
      }

      if (blockedBehavior == 'fail' && blocked.isNotEmpty) {
        failureEvents.addAll(blocked.values);
        for (final flow in flows.where((flow) => flow.active)) {
          flow.active = false;
        }
        break;
      }

      for (final entry in blocked.entries) {
        entry.key.active = false;
        blockedEvents.add(
          _blockedEvent(entry.key, entry.value.target, entry.value.reason),
        );
      }

      final moving = intents.values
          .where((intent) => !blocked.containsKey(intent.flow))
          .toList();
      if (moving.isEmpty) break;

      for (final intent in moving) {
        moverLayer.setAt(intent.flow.position, null);
      }
      for (final intent in moving) {
        final flow = intent.flow;
        final params = Map<String, dynamic>.from(flow.entity.params)
          ..[headingParam] = intent.nextHeading;
        flow.position = intent.target;
        flow.entity = EntityInstance(flow.entity.kind, params);
        flow.path.add(intent.target);
        if (intent.delivered) {
          flow.delivered = true;
          flow.active = false;
        } else {
          moverLayer.setAt(flow.position, flow.entity);
        }
      }
    }

    final events = <GameEvent>[
      for (final flow in flows.where((flow) => flow.path.length > 1))
        GameEvent.entityPathMoved(
          flow.path,
          flow.entity.kind,
          params: flow.entity.params,
          layer: moverLayerId,
          delivered: flow.delivered,
        ),
      for (final flow in flows.where((flow) => flow.delivered))
        GameEvent.objectRemoved(flow.position, flow.entity.kind),
      ...blockedEvents,
    ];

    if (failureEvents.isNotEmpty) {
      final oldValue = (state.variables[failureVariable] as num?)?.toInt() ?? 0;
      final newValue = oldValue + 1;
      state.variables[failureVariable] = newValue;
      events.addAll([
        for (final failure in _dedupeFailures(failureEvents))
          GameEvent('routed_motion_failed', {
            'position': failure.target,
            'kind': failure.mover.entity.kind,
            'fromPosition': failure.mover.position,
            'reason': failure.reason,
          }),
        GameEvent.variableChanged(failureVariable, oldValue, newValue),
      ]);
    }
    return events;
  }

  String _flowSignature(List<_FlowMover> flows, String headingParam) => flows
      .where((flow) => !flow.delivered)
      .map(
        (flow) => '${flow.index}:${flow.position.x},${flow.position.y}:'
            '${flow.entity.param(headingParam)}:${flow.active}',
      )
      .join('|');

  GameEvent _blockedEvent(_FlowMover flow, Position target, String reason) =>
      GameEvent('routed_motion_blocked', {
        'position': target,
        'kind': flow.entity.kind,
        'fromPosition': flow.position,
        'reason': reason,
      });

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

  bool _gateIsClosed(
    LevelState state,
    GameDefinition game,
    Position target,
    String incomingSide,
    String? gateLayerId,
    String gateClosedTag,
    String gateEntrySideParam,
  ) {
    if (gateLayerId == null || gateLayerId.isEmpty) return false;
    final gate = state.board.getEntity(gateLayerId, target);
    if (gate == null || !game.hasTag(gate.kind, gateClosedTag)) return false;
    final controlledSide = gate.param(gateEntrySideParam)?.toString();
    return controlledSide == null ||
        controlledSide == 'any' ||
        controlledSide == incomingSide;
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

class _FlowMover {
  final int index;
  Position position;
  EntityInstance entity;
  final List<Position> path;
  bool active = true;
  bool delivered = false;

  _FlowMover(this.index, this.position, this.entity) : path = [position];
}

class _FlowIntent {
  final _FlowMover flow;
  final Position target;
  final String nextHeading;
  final bool delivered;

  const _FlowIntent(this.flow, this.target, this.nextHeading, this.delivered);
}
