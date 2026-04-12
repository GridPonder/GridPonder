import '../engine/turn_engine.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/level_definition.dart';
import '../models/position.dart';
import 'text_renderer.dart';

/// The result of one agent action, including optional reasoning and memory.
class AgentActResult {
  /// All actions chosen by the agent this turn (one or more).
  final List<GameAction> actions;

  /// Full chain-of-thought or extended thinking text from the LLM, if available.
  final String? thinking;

  /// If non-null, replaces the agent's persistent memory for this level.
  final String? memoryUpdate;

  const AgentActResult(this.actions, {this.thinking, this.memoryUpdate});

  /// Convenience accessor for single-action results.
  GameAction get action => actions.first;
}

// ---------------------------------------------------------------------------
// Events emitted within a single act() call
// ---------------------------------------------------------------------------

sealed class AgentActEvent {}

/// A streaming thinking delta arriving before the final action is chosen.
class AgentThinkingDelta extends AgentActEvent {
  final String delta;
  AgentThinkingDelta(this.delta);
}

/// The agent has finished reasoning and chosen an action.
class AgentActCompleted extends AgentActEvent {
  final AgentActResult result;
  AgentActCompleted(this.result);
}

/// The observation passed to an agent each turn.
class AgentObservation {
  final GameDefinition game;
  final LevelDefinition level;
  final LevelState state;

  /// All actions the agent may submit (exhaustive enumeration from game.actions).
  final List<GameAction> validActions;

  /// Text (Unicode symbol) render of the current board state.
  final String boardText;

  /// 1-based attempt counter (increments on give_up or auto-reset).
  final int attemptNumber;

  /// Total actions taken across all attempts so far.
  final int totalActionsAllAttempts;

  /// The action that was executed to reach the current state (null on first turn).
  final GameAction? lastAction;

  /// Text render of the board state before [lastAction] was applied (null on first turn).
  final String? previousBoardText;

  /// Inventory slot contents before [lastAction] was applied (null on first turn or if no avatar).
  final String? previousInventory;

  const AgentObservation({
    required this.game,
    required this.level,
    required this.state,
    required this.validActions,
    required this.boardText,
    this.attemptNumber = 1,
    this.totalActionsAllAttempts = 0,
    this.lastAction,
    this.previousBoardText,
    this.previousInventory,
  });

  factory AgentObservation.build(
    GameDefinition game,
    LevelDefinition level,
    LevelState state, {
    int attemptNumber = 1,
    int totalActionsAllAttempts = 0,
    GameAction? lastAction,
    String? previousBoardText,
    String? previousInventory,
  }) {
    // Collect entity kinds currently present on the board for action filtering.
    final presentKinds = <String>{};
    for (final layer in state.board.layers.values) {
      for (final entry in layer.entries()) {
        presentKinds.add(entry.value.kind);
      }
    }

    return AgentObservation(
      game: game,
      level: level,
      state: state,
      validActions: _enumerateActions(game, presentKinds),
      boardText: TextRenderer.render(state, game),
      attemptNumber: attemptNumber,
      totalActionsAllAttempts: totalActionsAllAttempts,
      lastAction: lastAction,
      previousBoardText: previousBoardText,
      previousInventory: previousInventory,
    );
  }

  static List<GameAction> _enumerateActions(
      GameDefinition game, Set<String> presentKinds) {
    final actions = <GameAction>[];
    for (final actionDef in game.actions) {
      // Skip actions whose required entity kind is absent from the board.
      if (actionDef.entityKind != null &&
          !presentKinds.contains(actionDef.entityKind)) {
        continue;
      }
      if (actionDef.params.isEmpty) {
        actions.add(GameAction(actionDef.id, {}));
      } else {
        _enumerate(
          actionDef.id,
          actionDef.params.entries.toList(),
          {},
          actions,
        );
      }
    }
    return actions;
  }

  static void _enumerate(
    String actionId,
    List<MapEntry<String, ActionParamDef>> paramEntries,
    Map<String, dynamic> current,
    List<GameAction> out,
  ) {
    if (paramEntries.isEmpty) {
      out.add(GameAction(actionId, Map.from(current)));
      return;
    }
    final head = paramEntries.first;
    final tail = paramEntries.sublist(1);
    final values = head.value.values ?? const <String>[];
    for (final value in values) {
      _enumerate(actionId, tail, {...current, head.key: value}, out);
    }
  }

  Map<String, dynamic> toJson() {
    return {
      'gameId': game.id,
      'gameTitle': game.title,
      'levelId': level.id,
      'levelTitle': level.title ?? level.id,
      'boardText': boardText,
      'state': _stateToJson(),
      'goals': level.goals
          .map((g) => {'id': g.id, 'type': g.type, 'config': g.config})
          .toList(),
      'validActions': validActions.map((a) => a.toJson()).toList(),
      'attemptNumber': attemptNumber,
      'totalActionsAllAttempts': totalActionsAllAttempts,
    };
  }

  Map<String, dynamic> _stateToJson() {
    final board = state.board;
    final layers = <String, dynamic>{};
    for (final layerId in board.layers.keys) {
      final layer = board.layers[layerId]!;
      final rows = <List<String?>>[];
      for (int y = 0; y < board.height; y++) {
        final row = <String?>[];
        for (int x = 0; x < board.width; x++) {
          row.add(layer.getAt(Position(x, y))?.kind);
        }
        rows.add(row);
      }
      layers[layerId] = rows;
    }
    return {
      'board': {
        'width': board.width,
        'height': board.height,
        'layers': layers,
      },
      'avatar': state.avatar.enabled
          ? {
              'position': state.avatar.position != null
                  ? [state.avatar.position!.x, state.avatar.position!.y]
                  : null,
              'facing': state.avatar.facing.toJson(),
              'inventory': state.avatar.inventory.slot,
            }
          : null,
      'overlay': state.overlay != null
          ? {
              'position': [state.overlay!.x, state.overlay!.y],
              'size': [state.overlay!.width, state.overlay!.height],
            }
          : null,
      'turnCount': state.turnCount,
      'actionCount': state.actionCount,
    };
  }
}

/// Abstract agent interface.
abstract class GridPonderAgent {
  /// Stream events for one turn: zero or more [AgentThinkingDelta]s followed
  /// by exactly one [AgentActCompleted].
  Stream<AgentActEvent> act(AgentObservation obs);

  /// Human-readable name shown in the UI.
  String get name;
}

// ---------------------------------------------------------------------------
// Step events emitted by AgentRunner
// ---------------------------------------------------------------------------

sealed class AgentStepEvent {}

/// A streaming thinking delta received while the agent is still deciding.
class AgentStepThinking extends AgentStepEvent {
  final String delta;
  AgentStepThinking(this.delta);
}

/// The agent has chosen an action and it has been applied to the engine.
class AgentStepActed extends AgentStepEvent {
  final AgentActResult result;
  final LevelState newState;
  final bool isWon;
  final bool isLost;
  AgentStepActed({
    required this.result,
    required this.newState,
    required this.isWon,
    required this.isLost,
  });
}

/// The agent has updated its persistent memory for this level.
class AgentStepMemoryUpdated extends AgentStepEvent {
  final String memory;
  AgentStepMemoryUpdated(this.memory);
}

/// The level was reset — either because the agent chose give_up or hit the
/// auto-reset threshold.
class AgentStepReset extends AgentStepEvent {
  final int attempt; // new attempt number (1-based)
  final bool auto;   // true = auto-reset, false = agent chose give_up
  AgentStepReset({required this.attempt, required this.auto});
}

/// The agent run has ended (won, lost, or max steps reached).
class AgentRunFinished extends AgentStepEvent {
  final bool won;
  final bool lost;
  final int steps;
  AgentRunFinished({
    required this.won,
    required this.lost,
    required this.steps,
  });
}

// ---------------------------------------------------------------------------
// AgentRunner
// ---------------------------------------------------------------------------

/// Drives a [TurnEngine] using a [GridPonderAgent] and emits step events.
class AgentRunner {
  const AgentRunner();

  Stream<AgentStepEvent> run(
    TurnEngine engine,
    GridPonderAgent agent, {
    int maxSteps = 200,
    Duration stepDelay = const Duration(milliseconds: 600),
    int autoResetMultiplier = 3,
  }) async* {
    final goldPathLen = engine.level.solution.goldPath.length;
    final autoResetThreshold = goldPathLen > 0
        ? autoResetMultiplier * goldPathLen
        : (autoResetMultiplier * 10).clamp(10, 60);

    int totalSteps = 0;
    int attemptNumber = 1;
    int previousAttemptsActions = 0; // sum of actionCounts of completed attempts
    GameAction? lastAction;
    String? previousBoardText;
    String? previousInventory;

    while (!engine.isWon && totalSteps < maxSteps) {
      // Auto-reset when attempt has used too many actions.
      if (engine.state.actionCount >= autoResetThreshold) {
        previousAttemptsActions += engine.state.actionCount;
        engine.reset();
        attemptNumber++;
        lastAction = null;
        previousBoardText = null;
        previousInventory = null;
        yield AgentStepReset(attempt: attemptNumber, auto: true);
        if (stepDelay > Duration.zero) await Future.delayed(stepDelay);
        continue;
      }

      final obs = AgentObservation.build(
        engine.game,
        engine.level,
        engine.state,
        attemptNumber: attemptNumber,
        totalActionsAllAttempts:
            previousAttemptsActions + engine.state.actionCount,
        lastAction: lastAction,
        previousBoardText: previousBoardText,
        previousInventory: previousInventory,
      );

      AgentActResult? result;
      await for (final event in agent.act(obs)) {
        if (event is AgentThinkingDelta) {
          yield AgentStepThinking(event.delta);
        } else if (event is AgentActCompleted) {
          result = event.result;
        }
      }
      if (result == null) break;

      // Emit memory update before acting (survives even if we give up).
      if (result.memoryUpdate != null) {
        yield AgentStepMemoryUpdated(result.memoryUpdate!);
      }

      // Capture board state before the batch so the next prompt has before/after.
      final batchPrevBoard = TextRenderer.render(engine.state, engine.game,
          includeLegend: false);
      final batchPrevInventory = engine.state.avatar.enabled
          ? engine.state.avatar.inventory.slot
          : null;

      bool batchTerminated = false;

      for (int i = 0; i < result.actions.length; i++) {
        final action = result.actions[i];

        // give_up: reset without consuming a game action; discard rest of batch.
        if (action.actionId == 'give_up') {
          previousAttemptsActions += engine.state.actionCount;
          engine.reset();
          attemptNumber++;
          lastAction = null;
          previousBoardText = null;
          previousInventory = null;
          yield AgentStepReset(attempt: attemptNumber, auto: false);
          if (stepDelay > Duration.zero) await Future.delayed(stepDelay);
          batchTerminated = true;
          break;
        }

        try {
          engine.executeTurn(action);
        } catch (_) {
          // Engine rejected the action — skip and continue batch.
          continue;
        }
        lastAction = action;
        totalSteps++;

        yield AgentStepActed(
          result: result,
          newState: engine.state,
          isWon: engine.isWon,
          isLost: engine.isLost,
        );

        if (engine.isWon || engine.isLost) {
          batchTerminated = true;
          break;
        }

        // Delay between actions within the batch (and after the last one).
        if (stepDelay > Duration.zero) await Future.delayed(stepDelay);
      }

      if (batchTerminated) break;

      // After batch completes, update prev board for next observation.
      previousBoardText = batchPrevBoard;
      previousInventory = batchPrevInventory;
    }

    yield AgentRunFinished(
      won: engine.isWon,
      lost: engine.isLost,
      steps: totalSteps,
    );
  }
}
