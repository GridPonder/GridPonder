import '../models/board.dart';
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

  /// Write variables that are pure functions of the settled state.
  ///
  /// Runs once per accepted turn, after every system's NPC resolution and the
  /// rules pass over NPC events (so after the board has finished changing),
  /// and once at level load, after every system's load settle. A system must
  /// only *read* the board here and write variables derived from it: a derived
  /// variable adds nothing to the state key that the board does not already
  /// determine, so solver dedup, undo and preview are unaffected. Emits no
  /// events.
  void executeDeriveState(LevelState state, GameDefinition game) {}

  /// True when this system's behaviour in [state] reads the turn counter.
  ///
  /// The state key excludes `turnCount`, so two states with the same key can
  /// still play differently when a system gates on the beat (an NPC that acts
  /// every Nth turn). Callers that compare state keys — the effectful-action
  /// probe — ask this to learn that a turn which only advanced the counter
  /// still changed something. Default: no.
  bool dependsOnTurnCount(LevelState state, GameDefinition game) => false;

  // ── Observation hooks (text observations only; never change state) ──────

  /// Public detail lines for one multi-cell object.
  ///
  /// Printed indented under the object in the "Multi-cell objects" block, in
  /// both named and anonymous mode, so they must not contain pack vocabulary
  /// (kind ids, names, layer ids). Default: none. Mirrors Python
  /// `GameSystem.observation_object_lines`.
  List<String> observationObjectLines(MultiCellObjectInstance mco,
          LevelState state, GameDefinition game) =>
      const [];

  /// A public status block this system maintains (header line first).
  ///
  /// [initialBoard] is the level's authored board (read-only). The renderer
  /// prints the block only in named mode, one block per system in
  /// declaration order. Default: none. Mirrors Python
  /// `GameSystem.observation_status_lines`.
  List<String> observationStatusLines(
          LevelState state, GameDefinition game, Board initialBoard) =>
      const [];
}
