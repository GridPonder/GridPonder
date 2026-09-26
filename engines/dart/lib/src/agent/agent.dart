import '../engine/turn_engine.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/level_definition.dart';
import '../models/position.dart';
import 'llm_agent.dart';
import 'py_format.dart';
import 'text_renderer.dart';

/// The result of one agent action, including optional reasoning and memory.
/// What an agent returns when the model's reply cannot be parsed or names no
/// offered action. [AgentRunner] treats it as a rejected action: nothing is
/// executed and no action is spent (it still counts toward `maxSteps`, so a
/// model that never answers cleanly cannot loop forever).
const unrecognisedAction = GameAction('_unrecognised_reply', {});

class AgentActResult {
  /// All actions chosen by the agent this turn (one or more).
  final List<GameAction> actions;

  /// Full chain-of-thought or extended thinking text from the LLM, if available.
  final String? thinking;

  /// The raw text response from the LLM (separate from thinking/reasoning).
  /// Non-null when the model produces a distinct text output alongside thinking.
  final String? responseText;

  /// If non-null, replaces the agent's persistent memory for this level.
  final String? memoryUpdate;

  const AgentActResult(this.actions,
      {this.thinking, this.responseText, this.memoryUpdate});

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

  /// `LlmAgent.statusFingerprint` of the state before [lastAction] (null on
  /// the first turn). "The board did not change." needs it unchanged too;
  /// null skips that comparison.
  final String? previousStatus;

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
    this.previousStatus,
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
    String? previousStatus,
    Map<String, String>? kindSymbolOverrides,
    TurnEngine? engine,
  }) {
    return AgentObservation(
      game: game,
      level: level,
      state: state,
      validActions: enumerateActions(game, state, engine: engine),
      boardText: TextRenderer.render(state, game,
          kindSymbolOverrides: kindSymbolOverrides, level: level),
      attemptNumber: attemptNumber,
      totalActionsAllAttempts: totalActionsAllAttempts,
      lastAction: lastAction,
      previousBoardText: previousBoardText,
      previousInventory: previousInventory,
      previousStatus: previousStatus,
    );
  }

  /// Every action the agent may submit in [state].
  ///
  /// Mirrors `enumerate_actions` in engines/python/action_enum.py — the two
  /// runners must offer identical lists. Actions whose `entityKind` is absent
  /// from the board are skipped. Parameters with a fixed `values` list are
  /// expanded over those values; `position` parameters over every board cell
  /// in row-major order (y, then x).
  ///
  /// When [engine] is given (its state must be [state]), each syntactic
  /// candidate is probed with [TurnEngine.previewTurn] — which never touches
  /// the live state — and kept only when it is effectful: accepted AND (the
  /// state key changed OR it emitted an event other than `turn_ended` OR it
  /// won OR it lost).
  static List<GameAction> enumerateActions(
    GameDefinition game,
    LevelState state, {
    TurnEngine? engine,
  }) {
    // Collect entity kinds currently present on the board for action filtering.
    final presentKinds = <String>{};
    for (final layer in state.board.layers.values) {
      for (final entry in layer.entries()) {
        presentKinds.add(entry.value.kind);
      }
    }

    final actions = <GameAction>[];
    for (final actionDef in game.actions) {
      // Skip actions whose required entity kind(s) are all absent from the board.
      if (actionDef.entityKind != null &&
          !actionDef.entityKind!.any(presentKinds.contains)) {
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
          state,
        );
      }
    }
    if (engine == null) return actions;
    final beforeKey = stateKey(engine.state, game);
    // Asked once per state: whether a turn that only advances the counter
    // still changes what the board will do next.
    final beatMatters = engine.turnCountMatters();
    return actions
        .where((a) => _isEffectful(engine, game, a, beforeKey, beatMatters))
        .toList();
  }

  static void _enumerate(
    String actionId,
    List<MapEntry<String, ActionParamDef>> paramEntries,
    Map<String, dynamic> current,
    List<GameAction> out,
    LevelState state,
  ) {
    if (paramEntries.isEmpty) {
      out.add(GameAction(actionId, Map.from(current)));
      return;
    }
    final head = paramEntries.first;
    final tail = paramEntries.sublist(1);
    final List<Object> values;
    if (head.value.type == 'position') {
      values = [
        for (int y = 0; y < state.board.height; y++)
          for (int x = 0; x < state.board.width; x++) [x, y],
      ];
    } else {
      values = head.value.values ?? const <String>[];
    }
    for (final value in values) {
      _enumerate(actionId, tail, {...current, head.key: value}, out, state);
    }
  }

  /// Events that do not by themselves make an action effectful: the
  /// pipeline's tick, and a selection event that re-selects what is already
  /// selected (a real selection change also changes the state key).
  static const _nonEffectEvents = {'turn_ended', 'actor_selected'};

  /// Accepted AND (state key changed OR a meaningful event OR won OR lost OR
  /// the turn counter advanced while some system's behaviour depends on it).
  static bool _isEffectful(TurnEngine engine, GameDefinition game,
      GameAction action, String before, bool beatMatters) {
    final result = engine.previewTurn(action);
    if (!result.accepted) return false;
    if (result.isWon || result.isLost) return true;
    if (result.events.any((e) => !_nonEffectEvents.contains(e.type))) {
      return true;
    }
    if (beatMatters && result.newState.turnCount != engine.state.turnCount) {
      return true;
    }
    return stateKey(result.newState, game) != before;
  }

  /// Canonical string of the parts of [state] that define a distinct game
  /// state — the equivalent of Python's `GameState.to_key()`: every
  /// non-default board entity (with params), multi-cell objects, avatar
  /// (enabled, position, facing, item), variables and the overlay cursor.
  /// Turn and action counters and the won/lost flags are excluded.
  static String stateKey(LevelState state, GameDefinition game) {
    final defaults = <String, String?>{
      for (final def in game.layers)
        def.id: def.isExactlyOne ? (def.defaultKind ?? 'empty') : null,
    };
    final layerIds = state.board.layers.keys.toList()..sort();
    final board = [
      for (final id in layerIds)
        [
          id,
          [
            for (final e in state.board.layers[id]!.entries())
              if (!(e.value.kind == defaults[id] && e.value.params.isEmpty))
                [e.key.x, e.key.y, e.value.kind, _canon(e.value.params)],
          ],
        ],
    ];
    final mcos = [
      for (final m in state.board.multiCellObjects)
        [
          m.id,
          m.kind,
          [for (final c in m.cells) [c.x, c.y]],
          _canon(m.params),
        ],
    ];
    final av = state.avatar;
    final ov = state.overlay;
    return pyJsonDumps([
      board,
      mcos,
      [
        av.enabled,
        av.position == null ? null : [av.position!.x, av.position!.y],
        av.facing.toJson(),
        av.inventory.slot,
      ],
      _canon(state.variables),
      ov == null ? null : [ov.x, ov.y, ov.width, ov.height],
    ]);
  }

  /// Normalises values so that equal Python values compare equal here
  /// (Python treats `1 == 1.0`; JSON decoding may yield either).
  static Object? _canon(Object? v) {
    if (v is double && v == v.truncateToDouble() && v.abs() < 1e15) {
      return v.toInt();
    }
    if (v is Map) return {for (final e in v.entries) '${e.key}': _canon(e.value)};
    if (v is Iterable) return [for (final x in v) _canon(x)];
    if (v is Position) return [v.x, v.y];
    return v;
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
  /// True when this is the last action in the current batch (all actions from
  /// one LLM call have been applied). In step-by-step mode the UI waits for
  /// the next user press after this event.
  final bool isBatchEnd;
  AgentStepActed({
    required this.result,
    required this.newState,
    required this.isWon,
    required this.isLost,
    this.isBatchEnd = false,
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
    bool anonymize = false,
  }) async* {
    final budgetPathLen = engine.level.solution.budgetPathLength;
    final autoResetThreshold = budgetPathLen > 0
        ? autoResetMultiplier * budgetPathLen
        : (autoResetMultiplier * 10).clamp(10, 60);

    // Anon mode: build kind→label map once (stable for the whole run).
    final kindSymbolOverrides =
        anonymize ? buildAnonKindToLabel(engine.game) : null;

    int totalSteps = 0;
    int attemptNumber = 1;
    int previousAttemptsActions = 0; // sum of actionCounts of completed attempts
    GameAction? lastAction;
    String? previousBoardText;
    String? previousInventory;
    String? previousStatus;

    while (!engine.isWon && totalSteps < maxSteps) {
      // Auto-reset when attempt has used too many actions.
      if (engine.state.actionCount >= autoResetThreshold) {
        previousAttemptsActions += engine.state.actionCount;
        engine.reset();
        attemptNumber++;
        lastAction = null;
        previousBoardText = null;
        previousInventory = null;
        previousStatus = null;
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
        previousStatus: previousStatus,
        kindSymbolOverrides: kindSymbolOverrides,
        engine: engine,
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
          includeLegend: false,
          kindSymbolOverrides: kindSymbolOverrides,
          level: engine.level);
      final batchPrevInventory = engine.state.avatar.enabled
          ? engine.state.avatar.inventory.slot
          : null;
      final batchPrevStatus =
          LlmAgent.statusFingerprint(engine.game, engine.level, engine.state);

      // runDone = true exits the outer while loop (win/loss/no-result).
      // skipPrevUpdate = true skips updating previousBoardText (give_up/win/loss).
      bool runDone = false;
      bool skipPrevUpdate = false;
      GameAction? lastAppliedAction;

      for (int i = 0; i < result.actions.length; i++) {
        final action = result.actions[i];
        final isLast = i == result.actions.length - 1;

        // give_up: reset and discard rest of batch; outer loop continues.
        if (action.actionId == 'give_up') {
          previousAttemptsActions += engine.state.actionCount;
          engine.reset();
          attemptNumber++;
          lastAction = null;
          previousBoardText = null;
          previousInventory = null;
          previousStatus = null;
          yield AgentStepReset(attempt: attemptNumber, auto: false);
          if (stepDelay > Duration.zero) await Future.delayed(stepDelay);
          skipPrevUpdate = true;
          break;
        }

        if (action.actionId == unrecognisedAction.actionId) {
          totalSteps++;
          continue;
        }

        try {
          engine.executeTurn(action);
        } catch (_) {
          // Engine rejected the action — skip and continue batch.
          continue;
        }
        lastAppliedAction = action;
        totalSteps++;

        // isBatchEnd: true when this is the last action that will be applied
        // from this LLM call — either the last in the list, or game over.
        final gameOver = engine.isWon || engine.isLost;
        yield AgentStepActed(
          result: result,
          newState: engine.state,
          isWon: engine.isWon,
          isLost: engine.isLost,
          isBatchEnd: isLast || gameOver,
        );

        if (gameOver) {
          runDone = true;
          skipPrevUpdate = true;
          break;
        }

        // Delay between actions within the batch.
        if (!isLast && stepDelay > Duration.zero) {
          await Future.delayed(stepDelay);
        }
      }

      if (runDone) break;

      if (lastAppliedAction != null) lastAction = lastAppliedAction;

      // After batch completes normally, update prev board for next observation.
      if (!skipPrevUpdate) {
        previousBoardText = batchPrevBoard;
        previousInventory = batchPrevInventory;
        previousStatus = batchPrevStatus;
      }
    }

    yield AgentRunFinished(
      won: engine.isWon,
      lost: engine.isLost,
      steps: totalSteps,
    );
  }
}

// ---------------------------------------------------------------------------
// Anonymous-mode helpers (used by AgentRunner and LlmAgent)
// ---------------------------------------------------------------------------

/// Builds a deterministic entity-kind → single-letter label map.
/// All kind IDs from [game] are sorted alphabetically and assigned A, B, C, …
/// Entities whose public symbol is '.' (empty) or ' ' (void) are
/// excluded — they keep their original symbol so the board stays readable.
/// Kinds that share a public observation symbol (see
/// [GameDefinition.observationKind]) share one label, so anonymous mode
/// conceals exactly what named mode conceals.
/// Used to anonymise board symbols, legend entries, and goal descriptions.
Map<String, String> buildAnonKindToLabel(GameDefinition game) {
  final sortedKinds = game.entityKinds.keys.toList()..sort();
  final map = <String, String>{};
  final groupLabels = <String, String>{};
  int labelIndex = 0;
  for (final kindId in sortedKinds) {
    final sym = game.publicSymbol(kindId) ?? '';
    if (sym == '.' || sym == ' ') continue; // keep original — "empty" stays
    map[kindId] = groupLabels.putIfAbsent(game.observationKind(kindId),
        () => _anonIndexToLabel(labelIndex++));
  }
  return map;
}

/// Builds a reverse map from anonymous action label (a1, a2, …) to the
/// corresponding [GameAction]. Actions are sorted by their JSON representation
/// (Python `json.dumps(a, sort_keys=True)`, so labels match the Python runner),
/// then labelled a1, a2, …
Map<String, GameAction> buildAnonReverseMap(List<GameAction> validActions) {
  final sorted = List<GameAction>.from(validActions)
    ..sort((a, b) => pyJsonDumps(a.toJson()).compareTo(pyJsonDumps(b.toJson())));
  final map = <String, GameAction>{};
  for (int i = 0; i < sorted.length; i++) {
    map['a${i + 1}'] = sorted[i];
  }
  return map;
}

/// Converts a 0-based index to a label: 0→A, 1→B, …, 25→Z, 26→AA, 27→AB, …
/// One character per label, so an anonymous grid stays aligned however many
/// kinds a pack has: A-Z, then a-z, then digits, then a few printable symbols
/// that no grid, legend or stacked-cell syntax uses. Mirrors `_ANON_ALPHABET`
/// in engines/python/anon.py.
const _anonAlphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    'abcdefghijklmnopqrstuvwxyz'
    '0123456789'
    r'!$%&*<>^~';

String _anonIndexToLabel(int i) {
  if (i < _anonAlphabet.length) return _anonAlphabet[i];
  // Beyond the alphabet: Greek capitals (still one narrow character).
  return String.fromCharCode(0x391 + i - _anonAlphabet.length);
}
