import 'dart:math';

import 'agent.dart';
import '../models/game_action.dart';

/// Agent that picks uniformly at random from all valid actions.
/// Useful as a baseline and for smoke-testing levels.
class RandomAgent implements GridPonderAgent {
  final Random _rng;

  RandomAgent({int? seed}) : _rng = Random(seed);

  @override
  String get name => 'Random';

  @override
  Stream<AgentActEvent> act(AgentObservation obs) async* {
    final actions = obs.validActions;
    final action = actions.isEmpty
        ? GameAction('noop', {})
        : actions[_rng.nextInt(actions.length)];
    yield AgentActCompleted(AgentActResult(action));
  }
}
