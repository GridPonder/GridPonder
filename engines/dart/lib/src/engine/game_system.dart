import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';

/// Abstract base for all engine systems.
abstract class GameSystem {
  final String id;
  final String type;

  const GameSystem({required this.id, required this.type});

  /// Phase 2: action resolution — primary action executes.
  List<GameEvent> executeActionResolution(
      GameAction action, LevelState state, GameDefinition game) => const [];

  /// Phase 3: movement resolution — secondary movement.
  List<GameEvent> executeMovementResolution(
      LevelState state, GameDefinition game) => const [];

  /// Phase 5: cascade resolution — emitters, gravity, etc.
  List<GameEvent> executeCascadeResolution(
      List<GameEvent> triggerEvents, LevelState state, GameDefinition game) => const [];

  /// Phase 6: NPC resolution.
  List<GameEvent> executeNpcResolution(
      LevelState state, GameDefinition game) => const [];

  /// Level load: settle derived board state before the first turn.
  ///
  /// Systems whose output is a pure function of the board need the opening
  /// board to agree with their own rules before the player sees it, otherwise
  /// an authored level can contradict itself for exactly one turn. Events are
  /// returned for symmetry with the phases and discarded by the engine.
  List<GameEvent> executeLoadSettle(
      LevelState state, GameDefinition game) => const [];
}
