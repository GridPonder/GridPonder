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
    final routeConfig = _RouteConfig.fromJson(config);

    final moverLayer = state.board.layers[routeConfig.moverLayerId];
    if (moverLayer == null) return const [];

    final movers = moverLayer
        .entries()
        .where((entry) => game.hasTag(entry.value.kind, routeConfig.moverTag))
        .map((entry) => _Mover(entry.key, entry.value))
        .toList();
    if (movers.isEmpty) return const [];

    if (routeConfig.movementMode == 'until_blocked') {
      return _executeUntilBlocked(
        state,
        game,
        movers,
        routeConfig,
      );
    }

    final moverByPosition = {for (final mover in movers) mover.position: mover};
    final intents = <_Intent>[];
    final failures = <_Failure>[];

    for (final mover in movers) {
      final step = _planStep(state, game, mover, routeConfig);
      if (step.failureReason != null) {
        failures.add(_Failure(mover, step.target, step.failureReason!));
        continue;
      }
      intents.add(
        _Intent(
          mover,
          step.target,
          step.nextHeading!,
          removedAtEnd: step.removedAtEnd,
        ),
      );
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
      final oldValue =
          (state.variables[routeConfig.failureVariable] as num?)?.toInt() ?? 0;
      final newValue = oldValue + 1;
      state.variables[routeConfig.failureVariable] = newValue;
      return [
        for (final failure in _dedupeFailures(failures))
          GameEvent('routed_motion_failed', {
            'position': failure.target,
            'kind': failure.mover.entity.kind,
            'fromPosition': failure.mover.position,
            'reason': failure.reason,
          }),
        GameEvent.variableChanged(
          routeConfig.failureVariable,
          oldValue,
          newValue,
        ),
      ];
    }

    for (final mover in movers) {
      moverLayer.setAt(mover.position, null);
    }

    final events = <GameEvent>[];
    for (final intent in intents) {
      final params = Map<String, dynamic>.from(intent.mover.entity.params)
        ..[routeConfig.headingParam] = intent.nextHeading;
      events.add(
        GameEvent.tileMoved(
          intent.mover.position,
          intent.target,
          intent.mover.entity.kind,
          params: params,
          layer: routeConfig.moverLayerId,
        ),
      );
      if (intent.removedAtEnd) {
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
    List<_Mover> movers,
    _RouteConfig config,
  ) {
    final moverLayer = state.board.layers[config.moverLayerId]!;
    final flows = <_FlowMover>[
      for (var i = 0; i < movers.length; i++)
        _FlowMover(i, movers[i].position, movers[i].entity),
    ];
    final blockedEvents = <GameEvent>[];
    final failureEvents = <_Failure>[];
    final seenStates = <String>{};
    final defaultLimit =
        state.board.width * state.board.height * 4 * flows.length;
    final travelLimit =
        config.maxTravelSteps != null && config.maxTravelSteps! > 0
            ? config.maxTravelSteps!
            : (defaultLimit > 0 ? defaultLimit : 1);
    var rounds = 0;

    while (flows.any((flow) => flow.active)) {
      final signature = _flowSignature(flows, config.headingParam);
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
        for (final flow in flows.where((flow) => !flow.removedAtEnd))
          flow.position: flow,
      };
      final intents = <_FlowMover, _FlowIntent>{};
      final blocked = <_FlowMover, _Failure>{};

      for (final flow in flows.where((flow) => flow.active)) {
        final mover = _Mover(flow.position, flow.entity);
        final step = _planStep(state, game, mover, config);
        if (step.failureReason != null) {
          blocked[flow] = _Failure(
            mover,
            step.target,
            step.failureReason!,
          );
          continue;
        }
        intents[flow] = _FlowIntent(
          flow,
          step.target,
          step.nextHeading!,
          step.removedAtEnd,
        );
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

      if (config.blockedBehavior == 'fail' && blocked.isNotEmpty) {
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
          ..[config.headingParam] = intent.nextHeading;
        flow.position = intent.target;
        flow.entity = EntityInstance(flow.entity.kind, params);
        flow.path.add(intent.target);
        if (intent.removedAtEnd) {
          flow.removedAtEnd = true;
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
          layer: config.moverLayerId,
          removedAtEnd: flow.removedAtEnd,
        ),
      for (final flow in flows.where((flow) => flow.removedAtEnd))
        GameEvent.objectRemoved(flow.position, flow.entity.kind),
      ...blockedEvents,
    ];

    if (failureEvents.isNotEmpty) {
      final oldValue =
          (state.variables[config.failureVariable] as num?)?.toInt() ?? 0;
      final newValue = oldValue + 1;
      state.variables[config.failureVariable] = newValue;
      events.addAll([
        for (final failure in _dedupeFailures(failureEvents))
          GameEvent('routed_motion_failed', {
            'position': failure.target,
            'kind': failure.mover.entity.kind,
            'fromPosition': failure.mover.position,
            'reason': failure.reason,
          }),
        GameEvent.variableChanged(config.failureVariable, oldValue, newValue),
      ]);
    }
    return events;
  }

  _StepPlan _planStep(
    LevelState state,
    GameDefinition game,
    _Mover mover,
    _RouteConfig config,
  ) {
    final headingRaw = mover.entity.param(config.headingParam);
    Direction heading;
    try {
      heading = Direction.fromJson(headingRaw?.toString() ?? '');
    } on FormatException {
      return _StepPlan.failure(mover.position, 'invalid_heading');
    }
    if (!heading.isCardinal) {
      return _StepPlan.failure(mover.position, 'invalid_heading');
    }

    final sourceRoute = state.board.getEntity(
      config.routeLayerId,
      mover.position,
    );
    if (sourceRoute == null ||
        !_hasExit(config.routes, sourceRoute.kind, heading.toJson())) {
      return _StepPlan.failure(mover.position, 'invalid_source_route');
    }

    final target = Position(
      mover.position.x + heading.offset.x,
      mover.position.y + heading.offset.y,
    );
    if (!state.board.isInBounds(target)) {
      return _StepPlan.failure(target, 'left_board');
    }

    final exit = state.board.getEntity(config.exitLayerId, target);
    final isExit = exit != null && game.hasTag(exit.kind, config.exitTag);
    if (isExit && !_exitMatches(mover.entity, exit, config)) {
      return _StepPlan.failure(target, 'wrong_exit');
    }

    final bypassTargetRoute = isExit && !config.exitRequiresRoute;
    final targetRoute = state.board.getEntity(config.routeLayerId, target);
    var nextHeading = targetRoute == null
        ? null
        : _route(
            state,
            config.routes,
            targetRoute.kind,
            heading.opposite.toJson(),
            target,
            config.routeSelectorLayerId,
          );
    if (bypassTargetRoute) nextHeading = heading.toJson();
    if (!bypassTargetRoute &&
        (nextHeading == null || !_cardinalNames.contains(nextHeading))) {
      return _StepPlan.failure(target, 'disconnected_route');
    }

    if (_gateIsClosed(
      state,
      game,
      target,
      heading.opposite.toJson(),
      config,
    )) {
      return _StepPlan.failure(target, 'closed_gate');
    }
    if (!config.allowUTurns && nextHeading == heading.opposite.toJson()) {
      return _StepPlan.failure(target, 'u_turn');
    }

    final occupant = state.board.getEntity(config.moverLayerId, target);
    if (occupant != null && !game.hasTag(occupant.kind, config.moverTag)) {
      return _StepPlan.failure(target, 'occupied');
    }

    return _StepPlan.success(target, nextHeading!, removedAtEnd: isExit);
  }

  bool _exitMatches(
    EntityInstance mover,
    EntityInstance exit,
    _RouteConfig config,
  ) {
    final matchParam = config.matchParam;
    if (matchParam == null || matchParam.isEmpty) return true;
    return mover.param(matchParam) == exit.param(config.exitMatchParam!);
  }

  String _flowSignature(List<_FlowMover> flows, String headingParam) => flows
      .where((flow) => !flow.removedAtEnd)
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
    LevelState state,
    Map<String, dynamic> routes,
    String routeKind,
    String incomingSide,
    Position position,
    String? selectorLayerId,
  ) {
    final raw = routes[routeKind];
    if (raw is! Map) return null;
    final value = raw[incomingSide];
    if (value is String) return value;
    if (value is! Map || selectorLayerId == null) return null;
    final selector = state.board.getEntity(selectorLayerId, position);
    if (selector == null) return null;
    final selected = value[selector.kind];
    return selected is String ? selected : null;
  }

  bool _hasExit(Map<String, dynamic> routes, String routeKind, String heading) {
    final raw = routes[routeKind];
    if (raw is! Map) return false;
    for (final value in raw.values) {
      if (value == heading) return true;
      if (value is Map && value.values.contains(heading)) return true;
    }
    return false;
  }

  bool _gateIsClosed(
    LevelState state,
    GameDefinition game,
    Position target,
    String incomingSide,
    _RouteConfig config,
  ) {
    final gateLayerId = config.gateLayerId;
    if (gateLayerId == null || gateLayerId.isEmpty) return false;
    final gate = state.board.getEntity(gateLayerId, target);
    if (gate == null || !game.hasTag(gate.kind, config.gateClosedTag)) {
      return false;
    }
    final controlledSide = gate.param(config.gateEntrySideParam)?.toString();
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
  final bool removedAtEnd;

  const _Intent(
    this.mover,
    this.target,
    this.nextHeading, {
    required this.removedAtEnd,
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
  bool removedAtEnd = false;

  _FlowMover(this.index, this.position, this.entity) : path = [position];
}

class _FlowIntent {
  final _FlowMover flow;
  final Position target;
  final String nextHeading;
  final bool removedAtEnd;

  const _FlowIntent(
    this.flow,
    this.target,
    this.nextHeading,
    this.removedAtEnd,
  );
}

class _StepPlan {
  final Position target;
  final String? nextHeading;
  final bool removedAtEnd;
  final String? failureReason;

  const _StepPlan.success(
    this.target,
    this.nextHeading, {
    required this.removedAtEnd,
  }) : failureReason = null;

  const _StepPlan.failure(this.target, this.failureReason)
      : nextHeading = null,
        removedAtEnd = false;
}

class _RouteConfig {
  final String moverLayerId;
  final String moverTag;
  final String routeLayerId;
  final String headingParam;
  final String? matchParam;
  final String exitLayerId;
  final String exitTag;
  final String? exitMatchParam;
  final bool exitRequiresRoute;
  final String? gateLayerId;
  final String gateClosedTag;
  final String gateEntrySideParam;
  final String? routeSelectorLayerId;
  final String failureVariable;
  final Map<String, dynamic> routes;
  final String movementMode;
  final String blockedBehavior;
  final bool allowUTurns;
  final int? maxTravelSteps;

  const _RouteConfig({
    required this.moverLayerId,
    required this.moverTag,
    required this.routeLayerId,
    required this.headingParam,
    required this.matchParam,
    required this.exitLayerId,
    required this.exitTag,
    required this.exitMatchParam,
    required this.exitRequiresRoute,
    required this.gateLayerId,
    required this.gateClosedTag,
    required this.gateEntrySideParam,
    required this.routeSelectorLayerId,
    required this.failureVariable,
    required this.routes,
    required this.movementMode,
    required this.blockedBehavior,
    required this.allowUTurns,
    required this.maxTravelSteps,
  });

  factory _RouteConfig.fromJson(Map<String, dynamic> json) {
    final matchParam = json['matchParam'] as String?;
    return _RouteConfig(
      moverLayerId: json['moverLayer'] as String? ?? 'objects',
      moverTag: json['moverTag'] as String? ?? 'routed_mover',
      routeLayerId: json['routeLayer'] as String? ?? 'ground',
      headingParam: json['headingParam'] as String? ?? 'heading',
      matchParam: matchParam,
      exitLayerId: json['exitLayer'] as String? ?? 'markers',
      exitTag: json['exitTag'] as String? ?? 'route_exit',
      exitMatchParam: matchParam == null
          ? null
          : json['exitMatchParam'] as String? ?? matchParam,
      exitRequiresRoute: json['exitRequiresRoute'] as bool? ?? true,
      gateLayerId: json['gateLayer'] as String?,
      gateClosedTag: json['gateClosedTag'] as String? ?? 'route_closed',
      gateEntrySideParam: json['gateEntrySideParam'] as String? ?? 'entrySide',
      routeSelectorLayerId: json['routeSelectorLayer'] as String?,
      failureVariable:
          json['failureVariable'] as String? ?? 'routedMotionFailures',
      routes: json['routes'] as Map<String, dynamic>? ?? const {},
      movementMode: json['movementMode'] as String? ?? 'single_step',
      blockedBehavior: json['blockedBehavior'] as String? ?? 'fail',
      allowUTurns: json['allowUTurns'] as bool? ?? true,
      maxTravelSteps: json['maxTravelSteps'] as int?,
    );
  }
}
