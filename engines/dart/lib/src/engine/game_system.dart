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
}
