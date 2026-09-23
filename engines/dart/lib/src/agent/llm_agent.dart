import 'dart:async';
import 'dart:convert';

import 'package:llm_dart/llm_dart.dart';

import 'agent.dart';
import 'py_format.dart';
import 'text_renderer.dart';
import '../engine/goal_evaluator.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/goal.dart';
import '../models/position.dart';
import '../models/level_definition.dart';

/// Available Anthropic model IDs for the LLM agent.
class AnthropicModel {
  static const haiku = 'claude-haiku-4-5-20251001';
  static const sonnet = 'claude-sonnet-4-6';
  static const opus = 'claude-opus-4-6';

  static const all = [haiku, sonnet, opus];

  static String displayName(String modelId) {
    switch (modelId) {
      case haiku:
        return 'Claude Haiku (fast)';
      case sonnet:
        return 'Claude Sonnet (balanced)';
      case opus:
        return 'Claude Opus (powerful)';
      default:
        return modelId;
    }
  }

  static bool supportsThinking(String modelId) =>
      modelId == sonnet || modelId == opus;
}

/// Available OpenAI model IDs for the LLM agent.
class OpenAIModel {
  static const gpt4oMini = 'gpt-4o-mini';
  static const gpt4o = 'gpt-4o';
  static const o4Mini = 'o4-mini';
  static const o3 = 'o3';

  static const all = [gpt4oMini, gpt4o, o4Mini, o3];

  static String displayName(String modelId) => switch (modelId) {
        gpt4oMini => 'GPT-4o Mini',
        gpt4o => 'GPT-4o',
        o4Mini => 'o4-mini (reasoning)',
        o3 => 'o3 (reasoning)',
        _ => modelId,
      };

  static bool supportsThinking(String modelId) =>
      modelId == o4Mini || modelId == o3;
}

/// Available Google Gemini model IDs for the LLM agent.
class GoogleModel {
  static const flash2 = 'gemini-2.0-flash';
  static const flash25 = 'gemini-2.5-flash-preview-05-20';
  static const pro25 = 'gemini-2.5-pro-preview-06-05';

  static const all = [flash2, flash25, pro25];

  static String displayName(String modelId) => switch (modelId) {
        flash2 => 'Gemini 2.0 Flash',
        flash25 => 'Gemini 2.5 Flash (thinking)',
        pro25 => 'Gemini 2.5 Pro (thinking)',
        _ => modelId,
      };

  static bool supportsThinking(String modelId) =>
      modelId == flash25 || modelId == pro25;
}

/// Available Ollama model tags.
class OllamaModel {
  static const gemma4e2b = 'gemma4:e2b';
  static const gemma4e4b = 'gemma4:e4b';
  static const qwen35_0_8b = 'qwen3.5:0.8b';
  static const qwen35_2b = 'qwen3.5:2b';
  static const qwen35_4b = 'qwen3.5:4b';
  static const qwen35_9b = 'qwen3.5:9b';
  static const gptOss20b = 'gpt-oss:20b';

  static const all = [
    gemma4e2b,
    gemma4e4b,
    qwen35_0_8b,
    qwen35_2b,
    qwen35_4b,
    qwen35_9b,
    gptOss20b,
  ];

  static String displayName(String modelId) => switch (modelId) {
        gemma4e2b => 'Gemma 4 E2B',
        gemma4e4b => 'Gemma 4 E4B',
        qwen35_0_8b => 'Qwen 3.5 0.8B',
        qwen35_2b => 'Qwen 3.5 2B',
        qwen35_4b => 'Qwen 3.5 4B',
        qwen35_9b => 'Qwen 3.5 9B',
        gptOss20b => 'GPT-OSS 20B',
        _ => modelId,
      };

  static bool supportsThinking(String modelId) =>
      modelId == gemma4e2b || modelId == gemma4e4b || modelId == gptOss20b;
}

/// A game-playing agent backed by any [ChatCapability] from llm_dart.
///
/// The caller is responsible for constructing the provider (Anthropic, Ollama,
/// or any other llm_dart backend) and passing it in. This class only handles
/// the game-playing logic: prompt building, streaming, action extraction, and
/// persistent memory across resets.
class LlmAgent implements GridPonderAgent {
  final ChatCapability _provider;
  final String _displayName;

  /// Inference mode: 'single' | 'fixed-n' | 'flex-n' | 'full'
  final String inferenceMode;

  /// Max actions per LLM call for fixed-n mode.
  final int stepSize;

  /// Max actions per LLM call for flex-n mode (null = unlimited).
  final int? maxN;

  /// When true, entity kinds and action IDs are anonymised in the prompt.
  final bool anonymize;

  String _memory;

  /// The most recent prompt sent to the LLM. Null before the first call.
  String? lastPrompt;

  /// Anonymous mode: the labels offered in the most recent prompt (encoded
  /// action → label). The next observation's last action was chosen under
  /// these labels, so it is echoed with them rather than the new state's.
  Map<String, String> _lastLabels = const {};

  LlmAgent({
    required ChatCapability provider,
    required String displayName,
    String initialMemory = '',
    this.inferenceMode = 'single',
    this.stepSize = 3,
    this.maxN,
    this.anonymize = false,
  })  : _provider = provider,
        _displayName = displayName,
        _memory = initialMemory;

  @override
  String get name => _displayName;

  /// Current persistent memory (for inspection / seeding next level).
  String get memory => _memory;

  @override
  Stream<AgentActEvent> act(AgentObservation obs) async* {
    final prompt = LlmAgent.buildPrompt(
      obs,
      memory: _memory,
      inferenceMode: inferenceMode,
      stepSize: stepSize,
      maxN: maxN,
      anonymize: anonymize,
      lastActionLabel: anonymize && obs.lastAction != null
          ? _lastLabels[pyJsonDumps(obs.lastAction!.toJson())]
          : null,
    );
    lastPrompt = prompt;
    if (anonymize) {
      _lastLabels = {
        for (final e in buildAnonReverseMap(obs.validActions).entries)
          pyJsonDumps(e.value.toJson()): e.key,
      };
    }

    final thinkingBuffer = StringBuffer();
    final textBuffer = StringBuffer();

    try {
      await for (final event
          in _provider.chatStream([ChatMessage.user(prompt)])) {
        switch (event) {
          case ThinkingDeltaEvent(:final delta):
            if (delta.isNotEmpty) {
              thinkingBuffer.write(delta);
              yield AgentThinkingDelta(delta);
            }
          case TextDeltaEvent(:final delta):
            textBuffer.write(delta);
          case CompletionEvent():
            break;
          case ErrorEvent(:final error):
            throw LlmAgentException('LLM error: $error');
          default:
            break;
        }
      }
    } catch (e) {
      if (e is LlmAgentException) rethrow;
      throw LlmAgentException('Streaming error: $e');
    }

    final responseText = textBuffer.toString();
    // When the model emits a separate thinking block, keep both distinct.
    // When there is no thinking block, the response text IS the thinking.
    final hasThinking = thinkingBuffer.isNotEmpty;
    final thinking = hasThinking ? thinkingBuffer.toString() : responseText;
    final separateResponse = hasThinking ? responseText : null;

    final anonMap = anonymize ? buildAnonReverseMap(obs.validActions) : null;

    if (inferenceMode == 'single') {
      final action = extractAction(responseText, obs, anonMap: anonMap);
      final memoryUpdate = _extractMemory(responseText);
      if (memoryUpdate != null) _memory = memoryUpdate;
      yield AgentActCompleted(
        AgentActResult([action],
            thinking: thinking,
            responseText: separateResponse,
            memoryUpdate: memoryUpdate),
      );
    } else {
      final (actions, memoryUpdate) =
          extractActionList(responseText, obs, anonMap: anonMap);
      if (memoryUpdate != null) _memory = memoryUpdate;
      yield AgentActCompleted(
        AgentActResult(actions,
            thinking: thinking,
            responseText: separateResponse,
            memoryUpdate: memoryUpdate),
      );
    }
  }

  /// Parses a multi-action LLM response. Returns (actions, memoryUpdate).
  /// Accepts: bare JSON array, {"actions":[...]}, or single {"action":"..."}.
  /// When [anonMap] is provided, action labels (a1, a2, …) are reverse-mapped.
  /// A reply that cannot be parsed, or names no offered action, yields the
  /// [unrecognisedAction] sentinel instead of silently playing some other
  /// action; [AgentRunner] spends no action on it.
  static (List<GameAction>, String?) extractActionList(
      String text, AgentObservation obs,
      {Map<String, GameAction>? anonMap}) {
    // Strip <think>...</think> blocks and markdown code fences.
    final stripped = text
        .replaceAll(RegExp(r'<think>.*?</think>', dotAll: true), '')
        .replaceAll(RegExp(r'```[a-z]*\n?', caseSensitive: false), '')
        .trim();

    dynamic parsed;

    // Try whole stripped text first.
    try {
      parsed = jsonDecode(stripped);
    } catch (_) {}

    // If that failed, find first '[' or '{' and try from there.
    if (parsed == null) {
      final ai = stripped.indexOf('[');
      final oi = stripped.indexOf('{');
      if (ai != -1 && (oi == -1 || ai < oi)) {
        try {
          parsed = jsonDecode(stripped.substring(ai));
        } catch (_) {}
      }
      if (parsed == null && oi != -1) {
        try {
          parsed = jsonDecode(stripped.substring(oi));
        } catch (_) {}
      }
    }

    List<dynamic>? rawList;
    String? memoryUpdate;

    if (parsed is List) {
      rawList = parsed;
      // Memory on the last element.
      if (rawList.isNotEmpty && rawList.last is Map) {
        memoryUpdate = (rawList.last as Map)['memory'] as String?;
      }
    } else if (parsed is Map<String, dynamic>) {
      memoryUpdate = parsed['memory'] as String?;
      if (parsed.containsKey('actions') && parsed['actions'] is List) {
        rawList = parsed['actions'] as List;
      } else if (parsed.containsKey('action')) {
        rawList = [parsed];
      }
    }

    if (rawList == null || rawList.isEmpty) {
      return (const [unrecognisedAction], null);
    }

    final result = <GameAction>[];
    for (final item in rawList) {
      if (item is! Map) continue;
      final actionId = item['action'] as String?;
      if (actionId == null) continue;
      if (actionId == 'give_up') {
        result.add(GameAction('give_up', {}));
        break;
      }
      if (anonMap != null) {
        // Anon mode: reverse-map label (a1, a2, …) to real GameAction.
        final real = anonMap[actionId];
        if (real != null) result.add(real);
        continue;
      }
      final params = Map<String, dynamic>.from(item as Map<String, dynamic>)
        ..remove('action')
        ..remove('memory');
      final match = obs.validActions
          .where((a) =>
              a.actionId == actionId &&
              a.params.length == params.length &&
              params.entries.every((e) => a.params[e.key] == e.value))
          .firstOrNull;
      if (match != null) result.add(match);
    }

    if (result.isEmpty) return (const [unrecognisedAction], memoryUpdate);
    return (result, memoryUpdate);
  }

  /// Builds the LLM prompt for the given observation.
  ///
  /// Public and static so external tools (e.g. the benchmark runner) can
  /// produce identical prompts without instantiating an [LlmAgent].
  ///
  /// When [anonymize] is true, entity kind names, action IDs, and game
  /// description are replaced with opaque labels (ARC-AGI style).
  /// [lastActionLabel] is the label the agent submitted for the last action;
  /// anonymous prompts echo it (falling back to a lookup among the current
  /// labels, which renumber every turn, when it is absent).
  static String buildPrompt(
    AgentObservation obs, {
    String memory = '',
    String inferenceMode = 'single',
    int stepSize = 3,
    int? maxN,
    bool anonymize = false,
    String? previousAttempt,
    Map<String, dynamic>? rejectedAction,
    String? rejectionDetail,
    String? lastActionLabel,
  }) {
    // ── Anon maps ────────────────────────────────────────────────────────────
    final kindToLabel =
        anonymize ? buildAnonKindToLabel(obs.game) : const <String, String>{};
    // Forward map: Python-JSON-encoded action → anon label (a1, a2, …)
    final Map<String, String> actionForward;
    if (anonymize) {
      final sorted = List<GameAction>.from(obs.validActions)
        ..sort(
            (a, b) => pyJsonDumps(a.toJson()).compareTo(pyJsonDumps(b.toJson())));
      actionForward = {
        for (int i = 0; i < sorted.length; i++)
          pyJsonDumps(sorted[i].toJson()): 'a${i + 1}',
      };
    } else {
      actionForward = {};
    }

    // ── Goals ─────────────────────────────────────────────────────────────────
    final goalDescriptions = describeGoals(
      obs.level,
      obs.state,
      obs.game,
      anonymize: anonymize,
      kindToLabel: kindToLabel,
    );

    // ── Actions desc ──────────────────────────────────────────────────────────
    final actionsDesc = anonymize
        ? obs.validActions.map((a) {
            final label = actionForward[pyJsonDumps(a.toJson())] ?? '?';
            return '{"action": "$label"}';
          }).join(', ')
        : obs.validActions.map((a) => pyJsonDumps(a.toJson())).join(', ');

    // ── Board unchanged? ──────────────────────────────────────────────────────
    final inv =
        obs.state.avatar.enabled ? obs.state.avatar.inventory.slot : null;
    var boardUnchanged = false;
    if (obs.lastAction != null &&
        rejectedAction == null &&
        obs.previousBoardText != null) {
      // Same render inputs as the caller's previousBoardText (the runners
      // pass the level), so a system status block that renders in both never
      // makes an unchanged board look changed.
      final currentBare = TextRenderer.render(obs.state, obs.game,
          includeLegend: false,
          kindSymbolOverrides: anonymize ? kindToLabel : null,
          level: obs.level);
      boardUnchanged = currentBare == obs.previousBoardText &&
          inv == obs.previousInventory &&
          (obs.previousStatus == null ||
              obs.previousStatus ==
                  statusFingerprint(obs.game, obs.level, obs.state));
    }

    // ── Inventory / moves ─────────────────────────────────────────────────────
    // The inventory holds a kind id; an anonymous prompt shows its alias, as
    // the board and legend do, so the raw kind name never leaks.
    String shownItem(String item) =>
        anonymize ? (kindToLabel[item] ?? item) : item;
    final inventoryLine = inv != null ? '\nInventory: ${shownItem(inv)}' : '';

    final movesLine = statusLines(obs.game, obs.level, obs.state,
        anonymize: anonymize, kindToLabel: kindToLabel);

    final memorySection =
        memory.isNotEmpty ? '\nMEMORY FROM PREVIOUS ACTION:\n$memory\n' : '';

    final prevInventoryLine = obs.previousInventory != null
        ? '\nInventory: ${shownItem(obs.previousInventory!)}'
        : '';

    // ── Last action section ───────────────────────────────────────────────────
    // In anonymous mode, prefer the label the agent submitted: labels are
    // numbered over the state an action was chosen in, so the new state's
    // labels can name it differently or not at all.
    final String lastActionShown;
    if (obs.lastAction != null && anonymize) {
      final label = (lastActionLabel != null && lastActionLabel.isNotEmpty)
          ? lastActionLabel
          : actionForward[pyJsonDumps(obs.lastAction!.toJson())] ?? '?';
      lastActionShown = '{"action": "$label"}';
    } else if (obs.lastAction != null) {
      lastActionShown = pyJsonDumps(obs.lastAction!.toJson());
    } else {
      lastActionShown = '';
    }

    final String lastActionSection;
    if (rejectedAction != null) {
      // The action exactly as submitted (an anonymous label in anon mode).
      final rejectedLabel = pyJsonDumps(
          Map<String, dynamic>.from(rejectedAction)..remove('memory'));
      lastActionSection = 'LAST ACTION: $rejectedLabel — REJECTED '
          '(${rejectionDetail == null || rejectionDetail.isEmpty ? 'not legal in this state' : rejectionDetail}); '
          'no action was spent, the board is unchanged.\n'
          'CURRENT BOARD:\n'
          '${obs.boardText}$inventoryLine$movesLine';
    } else if (obs.lastAction != null) {
      final unchangedLine = boardUnchanged ? '\nThe board did not change.' : '';
      lastActionSection = '''
LAST ACTION: $lastActionShown
BOARD BEFORE:
${obs.previousBoardText}$prevInventoryLine

BOARD AFTER (current):
${obs.boardText}$inventoryLine$movesLine$unchangedLine

Compare the two boards to understand exactly what your last action did (tiles removed, pushed, merged, etc.).
${(inv != null || obs.previousInventory != null) ? 'If your inventory changed, note what was gained or lost.\n' : ''}Update your memory with any new observations about game mechanics or level layout.
Memory is your only way to retain knowledge across actions.''';
    } else {
      final previousAttemptLine =
          (previousAttempt != null && previousAttempt.isNotEmpty)
              ? 'PREVIOUS ATTEMPT: $previousAttempt\n'
              : '';
      lastActionSection = '''
${previousAttemptLine}CURRENT BOARD (first move of this attempt):
${obs.boardText}$inventoryLine$movesLine''';
    }

    // ── Header ────────────────────────────────────────────────────────────────
    final titleLine = anonymize
        ? 'You are playing a grid puzzle.'
        : 'You are playing a grid puzzle called "${obs.game.title}".';
    final descriptionSection = anonymize
        ? '\n2D grid game. Entities and rules unknown — discover by observation and experimentation.\n'
        : (obs.game.description.isNotEmpty
            ? '\n${obs.game.description}\n'
            : '');

    final header = '''$titleLine
Minimize total actions — give up early if stuck rather than wasting moves.
Attempt ${obs.attemptNumber} | Total actions across all attempts: ${obs.totalActionsAllAttempts}
$descriptionSection$memorySection
GOAL: $goalDescriptions
$lastActionSection

AVAILABLE ACTIONS:
$actionsDesc
{"action": "give_up"} — reset and start a fresh attempt''';

    // ── Examples ──────────────────────────────────────────────────────────────
    final String ex1, ex2;
    if (anonymize) {
      final n = obs.validActions.length;
      ex1 = '{"action": "a1"}';
      ex2 = n > 1 ? '{"action": "a$n"}' : ex1;
    } else {
      final va = obs.validActions;
      ex1 = va.isNotEmpty ? pyJsonDumps(va.first.toJson()) : '{"action": "..."}';
      ex2 = va.length > 1 ? pyJsonDumps(va.last.toJson()) : ex1;
    }

    return '$header\n\n$coordinatesNote\n'
        '${_promptTail(inferenceMode, stepSize, maxN, ex1: ex1, ex2: ex2)}';
  }

  /// The coordinate convention, stated once in every text-mode prompt.
  /// Mirrors `_COORDINATES_NOTE` in engines/python/observation.py.
  static const coordinatesNote =
      'Coordinates: a position [x, y] (written (x,y) under the board) is column '
      'x, row y; (0,0) is the top-left cell, x grows to the right and y grows '
      'downward.';

  static String _promptTail(
    String inferenceMode,
    int stepSize,
    int? maxN, {
    required String ex1,
    required String ex2,
  }) {
    // ex2 with memory field added (insert before closing brace).
    final ex2mem = ex2.substring(0, ex2.length - 1) +
        ', "memory": "Useful observation about the level."}';

    switch (inferenceMode) {
      case 'fixed-n':
        return '''Respond with ONLY a JSON array of up to $stepSize actions on a single line, no explanation or surrounding text. You may output fewer if the goal is reachable in fewer steps.
You will receive updated board state after the batch is applied.
Add a "memory" field to the last action to update your notes (replaces previous memory).
Examples:
  [$ex1, $ex2]
  [$ex2mem]
  [{"action": "give_up", "memory": "Dead end. Must try a different approach."}]

Choose actions most likely to reach the goal in fewest total actions (summed across attempts).''';

      case 'flex-n':
        final countLine = maxN != null
            ? 'Respond with ONLY a JSON array of 1 to $maxN actions on a single line, no explanation or surrounding text.'
            : 'Respond with ONLY a JSON array of one or more actions on a single line, no explanation or surrounding text.';
        return '''$countLine
Each action beyond the first counts as only 0.5 toward your total action score (e.g. outputting 3 actions = 2 effective actions). Minimize your effective total across all attempts.
Add a "memory" field to the last action to update your notes (replaces previous memory).
Examples:
  [$ex1]
  [$ex1, $ex2, $ex2mem]
  [{"action": "give_up", "memory": "Dead end. Must try a different approach."}]

Choose actions most likely to reach the goal in fewest effective actions (summed across attempts).''';

      case 'full':
        return '''Respond with a JSON array containing every action needed to solve the level. No further board state will be shown — plan the complete sequence now.
Add a "memory" field to the last action if useful.
Example:
  [$ex1, $ex2, $ex2mem]

Output the shortest sequence you are confident will solve the level.''';

      default: // single
        return '''Respond with ONLY a JSON object on a single line.
You may optionally update your persistent memory by adding a "memory" field (replaces previous memory).
Examples:
  $ex1
  $ex2mem
  {"action": "give_up", "memory": "Dead end. Must try a different approach."}

Choose the action most likely to reach the goal in fewest total actions (summed across attempts).''';
    }
  }

  /// A description of every goal on the level (joined by [joinGoalParts]).
  ///
  /// Mirror of `render_goals` in engines/python/goal_renderer.py. Split out of
  /// [buildPrompt] so the text an agent is given can be tested on its own —
  /// the `balance` branch below exists because a goal type with no branch
  /// falls through to the default and renders as its own *type name*.
  static String describeGoals(
    LevelDefinition level,
    LevelState state,
    GameDefinition game, {
    bool anonymize = false,
    Map<String, String> kindToLabel = const {},
  }) {
    final goalParts = <String>[];
    for (final g in level.goals) {
      // Per-game goal-text override (set in game.json `goalDescriptions`).
      // Skipped in anonymise mode since the override may name entities.
      // Goal types with live progress keep it after the override text, so a
      // hand-written description never hides how close the board is.
      if (!anonymize) {
        final override = game.goalDescriptions[g.id];
        if (override != null) {
          final progress = _goalProgress(g.type, g.id, g.config, state, game);
          goalParts
              .add(progress != null ? '$override (now: $progress)' : override);
          continue;
        }
      }
      switch (g.type) {
        case 'reach_target':
          final kindId = g.config['targetKind'] as String?;
          final tag = g.config['targetTag'] as String?;
          final name = anonymize
              ? _resolveEntityNameAnon(game, kindId, tag, kindToLabel)
              : _resolveEntityName(game, kindId, tag);
          goalParts.add('Reach the $name');
        case 'board_match':
          final targetGrid = _renderTargetGrid(game, g.config,
              kindToLabel: anonymize ? kindToLabel : null);
          if (targetGrid != null) {
            goalParts
                .add('Arrange tiles to match the target pattern:\n$targetGrid');
          } else {
            goalParts.add('Arrange tiles to match the target pattern');
          }
        case 'sequence_match':
          final sequence = (g.config['sequence'] as List?)
                  ?.map((e) => (e as num).toInt())
                  .toList() ??
              [];
          final matched = state.sequenceIndices[g.id] ?? 0;
          final done = sequence.take(matched).map((n) => '✓$n').join(', ');
          final pending = sequence.skip(matched).map((n) => '$n').join(', ');
          final progress = [
            if (done.isNotEmpty) done,
            if (pending.isNotEmpty) pending
          ].join(', ');
          goalParts.add('Merge numbers in sequence [$progress] '
              '(${_sequenceProgress(g.id, g.config, state)})');
        case 'all_cleared':
          final kindId = g.config['kind'] as String?;
          final tag = g.config['tag'] as String?;
          final name = anonymize
              ? _resolveEntityNameAnon(game, kindId, tag, kindToLabel)
              : _resolveEntityName(game, kindId, tag);
          goalParts.add('Clear all ${name}s from the board');
        case 'sum_constraint':
          goalParts.add(_describeSumConstraint(g.config));
        case 'count_constraint':
          goalParts.add(_describeCountConstraint(g.config));
        case 'balance':
          goalParts.add(_describeBalance(game, g.config, state,
              kindToLabel: anonymize ? kindToLabel : null));
        case 'param_match':
          goalParts.add(_describeParamMatch(game, g.config,
              kindToLabel: anonymize ? kindToLabel : null));
        case 'variable_threshold':
          goalParts.add(_describeVariableThreshold(g.config, state,
              anonymize: anonymize));
        default:
          goalParts.add(g.type);
      }
    }
    return joinGoalParts(goalParts);
  }

  /// Joins goal descriptions with "; ", except that a goal following a
  /// multi-line one (a target grid ending in its legend) starts on its own
  /// line instead of being appended to that goal's last line. Mirror of
  /// `join_goal_parts` in engines/python/goal_renderer.py.
  static String joinGoalParts(List<String> parts) {
    final out = StringBuffer();
    for (var i = 0; i < parts.length; i++) {
      if (i > 0) out.write(parts[i - 1].contains('\n') ? '\n' : '; ');
      out.write(parts[i]);
    }
    return out.toString();
  }

  /// Limit of the level's first `max_actions` lose condition, if any.
  static int? _maxActionsLimit(LevelDefinition level) {
    for (final c in level.loseConditions) {
      if (c.type != 'max_actions') continue;
      final limit = c.config['limit'];
      if (limit is int) return limit;
    }
    return null;
  }

  /// Renders a state variable for the status block. Integral doubles print as
  /// integers so the text matches however the number was stored. Mirrors
  /// `_format_value` in engines/python/observation.py.
  static String formatValue(Object? value) {
    if (value is bool) return value ? 'true' : 'false';
    if (value is int) return '$value';
    if (value is double) {
      if (value.isFinite && value == value.truncateToDouble()) {
        return '${value.toInt()}';
      }
      return pyRepr(value);
    }
    if (value is String) return value;
    return pyJsonDumps(value, compact: true);
  }

  /// The status lines that say something about the board, for deciding
  /// whether an action changed anything: every [statusLines] line except the
  /// move counter (a spent action alone is not a change). Rendered with real
  /// names — the anonymous labels are a bijection, so equality is the same.
  /// Mirrors `status_fingerprint` in engines/python/observation.py.
  static String statusFingerprint(
      GameDefinition game, LevelDefinition level, LevelState state) {
    return statusLines(game, level, state)
        .split('\n')
        .where((l) => l.isNotEmpty && !l.startsWith('Moves this attempt:'))
        .join('\n');
  }

  /// Public status lines printed under the board, each prefixed by a newline.
  ///
  /// In order: the move counter (`k of N allowed` when the level has a
  /// `max_actions` lose condition; the bare count when it has other lose
  /// conditions only; nothing otherwise), the `individual_actors` selection
  /// and per-actor budgets when that system is enabled for the level, then
  /// every `ui.readouts` entry the pack declares. No other variable is
  /// printed. Mirrors `status_lines` in engines/python/observation.py.
  static String statusLines(
    GameDefinition game,
    LevelDefinition level,
    LevelState state, {
    bool anonymize = false,
    Map<String, String> kindToLabel = const {},
  }) {
    String nameOf(String kind) => anonymize
        ? (kindToLabel[kind] ?? kind)
        : game.observationName(kind);

    final lines = <String>[];
    Map<String, dynamic>? config;
    for (final system
        in game.withSystemOverrides(level.systemOverrides).systems) {
      if (system.type == 'individual_actors' && system.enabled) {
        config = system.config;
        break;
      }
    }
    // A turn that only selects a piece is not charged (actionCount skips
    // it), so say so wherever pieces are selected.
    final freeTap = config != null ? ' (a tap that only selects is free)' : '';
    final limit = _maxActionsLimit(level);
    if (limit != null) {
      lines.add(
          'Moves this attempt: ${state.actionCount} of $limit allowed$freeTap');
    } else if (level.loseConditions.isNotEmpty) {
      lines.add('Moves this attempt: ${state.actionCount}$freeTap');
    }

    if (config != null) {
      final selectedKind = state.variables[
          config['selectedVariable'] as String? ?? 'selectedActorKind'];
      final rawPos = state.variables[config['selectedPositionVariable']
              as String? ??
          'selectedActorPosition'];
      final noSelection = selectedKind == null ||
          selectedKind == false ||
          selectedKind == 0 ||
          (selectedKind is String && selectedKind.isEmpty) ||
          (selectedKind is Iterable && selectedKind.isEmpty) ||
          (selectedKind is Map && selectedKind.isEmpty);
      if (noSelection) {
        lines.add('Selected: none');
      } else if (rawPos is List && rawPos.length >= 2) {
        final x = (rawPos[0] as num).toInt();
        final y = (rawPos[1] as num).toInt();
        final entity = state.board.getEntity(
            config['actorLayer'] as String? ?? 'actors', Position(x, y));
        if (entity != null && entity.kind == selectedKind) {
          lines.add('Selected: ${nameOf(pyStr(selectedKind))} at ($x,$y)');
        } else {
          lines.add(
              'Selected: none (the piece selected at ($x,$y) is gone or changed)');
        }
      } else {
        lines.add('Selected: ${nameOf(pyStr(selectedKind))}');
      }

      final budgets = config['budgets'];
      if (budgets is Map && budgets.isNotEmpty) {
        final rawRemaining = state.variables[
            config['budgetVariable'] as String? ?? 'actorMovesRemaining'];
        final remaining = rawRemaining is Map ? rawRemaining : const {};
        final parts = [
          for (final e in budgets.entries)
            '${nameOf(pyStr(e.key))} ${formatValue(remaining.containsKey(e.key) ? remaining[e.key] : e.value)}'
        ];
        lines.add('Moves left: ${parts.join(', ')}');
      }
    }

    final readouts = game.ui.readouts;
    for (int i = 0; i < readouts.length; i++) {
      final readout = readouts[i];
      if (!state.variables.containsKey(readout.variable)) continue;
      final value = state.variables[readout.variable];
      final blank = readout.blankWhen;
      final shown = (blank != null && value is num && value == blank)
          ? '-'
          : formatValue(value);
      final label = anonymize ? 'Readout ${i + 1}' : readout.label;
      lines.add('$label: $shown');
    }

    return lines.map((l) => '\n$l').join();
  }

  /// Player-facing reason for an engine loss. Mirrors `describe_loss` in
  /// engines/python/goal_renderer.py: [loseReason] is the engine's reason code
  /// (`max_actions`, `variable_threshold:<variable>`,
  /// `premature_success:<goalId>`, `balance_budget_exhausted`,
  /// `balance_unreachable`), matched to the first lose condition of the same
  /// type (and variable / trigger goal). Named mode prefers that condition's
  /// `description`; otherwise a generic sentence is built from its type, with
  /// variable and goal names replaced by `#<i>` in anonymous mode.
  static String describeLoss(LevelDefinition level, String? loseReason,
      {bool anonymize = false}) {
    final code = loseReason ?? '';
    final colon = code.indexOf(':');
    final ctype = colon < 0 ? code : code.substring(0, colon);
    final key = colon < 0 ? '' : code.substring(colon + 1);
    var index = 0;
    LoseConditionDef? cond;
    for (int i = 0; i < level.loseConditions.length; i++) {
      final candidate = level.loseConditions[i];
      if (candidate.type != ctype) continue;
      final cfg = candidate.config;
      if (ctype == 'variable_threshold' &&
          key.isNotEmpty &&
          cfg['variable'] != key) {
        continue;
      }
      if (ctype == 'premature_success' &&
          key.isNotEmpty &&
          cfg['triggerGoalId'] != key) {
        continue;
      }
      index = i + 1;
      cond = candidate;
      break;
    }

    if (cond != null && !anonymize) {
      final description = cond.description;
      if (description != null && description.isNotEmpty) return description;
    }

    final cfg = cond?.config ?? const <String, dynamic>{};
    String orKey(Object? v) =>
        (v == null || v == '' || v == false || v == 0) ? key : pyStr(v);
    switch (ctype) {
      case 'max_actions':
        return 'move limit of ${cfg.containsKey('limit') ? pyStr(cfg['limit']) : '?'} reached';
      case 'variable_threshold':
        final name = anonymize ? '#$index' : orKey(cfg['variable']);
        return 'loss condition "$name" reached';
      case 'balance_budget_exhausted':
        return "a piece's remaining moves can no longer complete its share";
      case 'balance_unreachable':
        return 'the balance goal became unreachable';
      case 'premature_success':
        final name = anonymize ? '#$index' : orKey(cfg['triggerGoalId']);
        return 'goal "$name" was met before the other required goals';
      case '':
        return 'the level was lost';
    }
    final name = anonymize ? '#$index' : ctype;
    return 'loss condition "$name" reached';
  }

  /// Describe a numeric threshold goal and expose its live value. A pack's
  /// `goalDescriptions` override replaces this sentence; its live progress
  /// then comes from [_goalProgress] as the shared `(now: ...)` suffix.
  /// Mirrors `_describe_variable_threshold` in goal_renderer.py.
  static String _describeVariableThreshold(
      Map<String, dynamic> config, LevelState state,
      {bool anonymize = false}) {
    final variable = config['variable']?.toString() ?? 'value';
    final comparison = config['comparison']?.toString() ?? 'gte';
    final target = pyStr(config['target'] ?? 0);
    final current = pyStr(state.variables[variable] ?? 0);

    final subject =
        anonymize ? 'Required value' : variable.replaceAll('_', ' ');
    final requirement = switch (comparison) {
      'eq' => 'equal $target',
      'gte' => 'reach at least $target',
      'lte' => 'stay at or below $target',
      _ => 'satisfy $comparison $target',
    };
    return '$subject must $requirement (current: $current)';
  }

  /// Live progress of a `variable_threshold` goal: `current/target` for an
  /// at-least goal, else the current value and the requirement. Mirrors
  /// `_variable_threshold_progress`.
  static String _variableThresholdProgress(
      Map<String, dynamic> config, LevelState state) {
    final variable = config['variable']?.toString() ?? 'value';
    final comparison = config['comparison']?.toString() ?? 'gte';
    final target = pyStr(config['target'] ?? 0);
    final current = pyStr(state.variables[variable] ?? 0);
    if (comparison == 'gte') return '$current/$target';
    return '$current; required: $comparison $target';
  }

  static String _listNames(List<String> names) {
    if (names.isEmpty) return 'the owners';
    if (names.length == 1) return names.first;
    return '${names.sublist(0, names.length - 1).join(', ')} and ${names.last}';
  }

  /// Describes a `balance` goal: divide the claimable cells between owners.
  ///
  /// Generic over the config rather than written for any one pack — the two
  /// flags are what the win condition actually reads, so the sentence changes
  /// with them. In anonymous mode the owners come out as their aliases and the
  /// layer is never named: `territory` is the pack's own vocabulary, and
  /// aliasing covers entity kinds, not layer ids.
  ///
  /// Progress is included for the same reason `sequence_match` includes it — a
  /// goal you cannot tell you are close to meeting is a worse goal, not a
  /// harder one — and is counted by the same function the win condition uses.
  static String _describeBalance(
      GameDefinition game, Map<String, dynamic> config, LevelState state,
      {Map<String, String>? kindToLabel}) {
    final owners = (config['owners'] as List?)?.cast<String>() ?? [];
    final names = [
      for (final owner in owners)
        kindToLabel != null
            ? (kindToLabel[owner] ?? owner)
            : _resolveEntityName(game, owner, null)
    ];

    final listed = _listNames(names);
    final requireEqual = (config['requireEqual'] as bool?) ?? true;
    final requireComplete = (config['requireComplete'] as bool?) ?? true;
    final String head;
    if (requireComplete && requireEqual) {
      head =
          'Claim every claimable cell, and give $listed an equal number each';
    } else if (requireEqual) {
      head = 'Give $listed an equal number of cells each';
    } else if (requireComplete) {
      head = 'Claim every claimable cell for $listed';
    } else {
      head = 'Claim cells for $listed';
    }

    if (owners.isEmpty) return head;
    final progress = _balanceProgress(config, state, game, names);
    var full = head;
    if ((config['requireConnected'] as bool?) ?? false) {
      final sources = config['connectionSources'] as Map? ?? const {};
      final listedSources = [
        for (int i = 0; i < owners.length; i++)
          '${names[i]} ${_formatSource(sources[owners[i]])}'
      ].join(', ');
      full = '$head, and each owner\'s cells must connect orthogonally to its '
          'source cell [$listedSources]';
    }
    return '$full ($progress)';
  }

  static String _formatSource(Object? raw) {
    if (raw is List && raw.length == 2) {
      return '(${(raw[0] as num).toInt()},${(raw[1] as num).toInt()})';
    }
    return '-';
  }

  /// The counts clause of a balance goal: cells per owner (connected/owned per
  /// owner when `requireConnected`), then `N of M claimed`. Counted by the same
  /// functions the win condition uses. Mirrors `_balance_progress`.
  static String _balanceProgress(Map<String, dynamic> config, LevelState state,
      GameDefinition game, List<String> names) {
    final owners = (config['owners'] as List?)?.cast<String>() ?? [];
    final evaluator = GoalEvaluator();
    final (counts, claimable) = evaluator.balanceCounts(config, state, game);
    final String tally;
    if ((config['requireConnected'] as bool?) ?? false) {
      final connected = evaluator.balanceConnectedCounts(config, state, game);
      final cells = [
        for (int i = 0; i < owners.length; i++)
          '${names[i]} ${connected[owners[i]] ?? 0}/${counts[owners[i]] ?? 0}'
      ];
      if (cells.isNotEmpty) cells[0] = '${cells[0]} connected';
      tally = cells.join(', ');
    } else {
      tally = [
        for (int i = 0; i < owners.length; i++)
          '${names[i]} ${counts[owners[i]] ?? 0}'
      ].join(', ');
    }
    final owned = counts.values.fold(0, (a, b) => a + b);
    if (claimable != 0) return '$tally — $owned of $claimable claimed';
    return tally;
  }

  static String _sequenceProgress(
      String goalId, Map<String, dynamic> config, LevelState state) {
    final sequence = config['sequence'] as List? ?? const [];
    final matched = state.sequenceIndices[goalId] ?? 0;
    return '$matched/${sequence.length} done';
  }

  /// Live progress appended to a `goalDescriptions` override, or null for goal
  /// types that carry no progress clause. Mirrors `_goal_progress`.
  static String? _goalProgress(String type, String goalId,
      Map<String, dynamic> config, LevelState state, GameDefinition game) {
    if (type == 'balance') {
      final owners = (config['owners'] as List?)?.cast<String>() ?? [];
      if (owners.isEmpty) return null;
      final names = [for (final o in owners) _resolveEntityName(game, o, null)];
      return _balanceProgress(config, state, game, names);
    }
    if (type == 'sequence_match') {
      return _sequenceProgress(goalId, config, state);
    }
    if (type == 'variable_threshold') {
      return _variableThresholdProgress(config, state);
    }
    return null;
  }

  /// Kind named by one `targetLayers` cell, or null for an unset one. A cell
  /// is a bare kind or the entry form `{"kind": "...", "<param>": ...}`.
  static String? _targetCellKind(Object? cell) {
    if (cell is String) return cell;
    if (cell is Map) {
      final kind = cell['kind'];
      return kind is String ? kind : null;
    }
    return null;
  }

  /// Public name of a target kind: kinds sharing an observationSymbol all
  /// present their group's stable name. Mirrors `_kind_name`.
  static String _kindName(GameDefinition game, String kindId) =>
      game.observationName(kindId);

  /// The target pattern of a `board_match` goal, plus the lines that make it
  /// readable: which cells are free, which are required, and what every symbol
  /// in it means — including kinds that are not on the current board.
  ///
  /// `exact_non_null` (the default) leaves a null target cell unconstrained,
  /// so a cell null in every target layer renders `?`; `exact` requires it to
  /// be empty, so it keeps `.`. Where several target layers constrain one cell
  /// the grid shows the topmost (board-renderer order) and `Also required:`
  /// lists the rest. Mirrors `_render_target_grid` in goal_renderer.py.
  static String? _renderTargetGrid(
      GameDefinition game, Map<String, dynamic> config,
      {Map<String, String>? kindToLabel}) {
    final targetLayers = config['targetLayers'] as Map?;
    if (targetLayers == null || targetLayers.isEmpty) return null;

    final firstRows = targetLayers.values.first as List;
    final height = firstRows.length;
    final width = firstRows.isNotEmpty ? (firstRows.first as List).length : 0;

    final exact = (config['matchMode'] ?? 'exact_non_null') == 'exact';
    final nullSymbol = exact ? '.' : '?';
    final anon = kindToLabel != null;

    String symbolFor(String kindId) {
      if (anon && kindToLabel.containsKey(kindId)) return kindToLabel[kindId]!;
      final sym = game.publicSymbol(kindId);
      return (sym != null && sym.isNotEmpty) ? sym : kindId[0];
    }

    final declared = [for (final l in game.layers) l.id];
    final inBoardOrder = [
      for (final l in declared)
        if (targetLayers.containsKey(l)) l,
    ];
    for (final l in targetLayers.keys) {
      if (!inBoardOrder.contains(l)) inBoardOrder.add(l as String);
    }
    final layerOrder = TextRenderer.orderLayerIds(inBoardOrder, game);

    final grid = List.generate(height, (_) => List.filled(width, nullSymbol));
    var nullUsed = false;
    final gridKinds = <(String, String)>[];
    final also = <String>[];
    for (int y = 0; y < height; y++) {
      for (int x = 0; x < width; x++) {
        final kindsHere = <String>[];
        for (final layerId in layerOrder) {
          final rows = targetLayers[layerId] as List? ?? const [];
          if (y >= rows.length || rows[y] is! List) continue;
          final row = rows[y] as List;
          if (x >= row.length) continue;
          final kind = _targetCellKind(row[x]);
          if (kind != null) kindsHere.add(kind);
        }
        if (kindsHere.isEmpty) {
          nullUsed = true;
          continue;
        }
        final top = kindsHere.first;
        final sym = symbolFor(top);
        grid[y][x] = sym;
        if (!gridKinds.contains((sym, top))) gridKinds.add((sym, top));
        for (final other in kindsHere.skip(1)) {
          also.add(anon
              ? '($x,$y) ${symbolFor(other)}'
              : '($x,$y) ${symbolFor(other)}=${_kindName(game, other)}');
        }
      }
    }

    final legend = <String>[];
    if (nullUsed) legend.add(exact ? '.=must be empty' : '?=any (unconstrained)');
    for (final (sym, kind) in gridKinds) {
      final entry = anon ? sym : '$sym=${_kindName(game, kind)}';
      if (!legend.contains(entry)) legend.add(entry);
    }

    final lines = [for (final row in grid) row.join()];
    lines.add('Target legend: ${legend.join(', ')}');
    if (also.isNotEmpty) lines.add('Also required: ${also.join(', ')}');
    return lines.join('\n');
  }

  static String _describeSumConstraint(Map<String, dynamic> config) {
    final scope = config['scope'] as String? ?? 'board';
    final target = config['target'];
    final comparison = config['comparison'] as String? ?? 'eq';
    final index = config['index'];

    final scopeLabel = switch (scope) {
      'all_rows' => 'every row',
      'all_cols' => 'every column',
      'row' => 'row ${index != null ? pyStr(index) : '?'}',
      'col' => 'column ${index != null ? pyStr(index) : '?'}',
      _ => scope,
    };
    final opLabel = switch (comparison) {
      'eq' => '= ${pyStr(target)}',
      'gte' => '≥ ${pyStr(target)}',
      'lte' => '≤ ${pyStr(target)}',
      _ => '$comparison ${pyStr(target)}',
    };
    return '$scopeLabel sums to $opLabel';
  }

  static String _describeCountConstraint(Map<String, dynamic> config) {
    final scope = config['scope'] as String? ?? 'board';
    final predicate = config['predicate'] as String? ?? '';
    final target = config['target'];
    final comparison = config['comparison'] as String? ?? 'eq';
    final index = config['index'];

    final scopeLabel = switch (scope) {
      'all_rows' => 'every row',
      'all_cols' => 'every column',
      'row' => 'row ${index != null ? pyStr(index) : '?'}',
      'col' => 'column ${index != null ? pyStr(index) : '?'}',
      _ => scope,
    };
    final predicateLabel = switch (predicate) {
      'even' => 'even',
      'odd' => 'odd',
      _ when predicate.startsWith('gte_') => '≥ ${predicate.substring(4)}',
      _ when predicate.startsWith('lte_') => '≤ ${predicate.substring(4)}',
      _ when predicate.startsWith('eq_') => '${predicate.substring(3)}',
      _ => predicate,
    };
    final n = target is int ? target : int.tryParse('$target') ?? 0;
    final countLabel = switch (comparison) {
      'eq' => 'exactly $n',
      'gte' => 'at least $n',
      'lte' => 'at most $n',
      _ => '$comparison $n',
    };
    final tileWord = n == 1 ? 'tile' : 'tiles';
    return 'In $scopeLabel: $countLabel $predicateLabel $tileWord';
  }

  static String _describeParamMatch(
      GameDefinition game, Map<String, dynamic> config,
      {Map<String, String>? kindToLabel}) {
    final markerKind = config['markerKind'] as String?;
    final checkKind = config['checkKind'] as String?;
    final checkParam = config['checkParam'] as String?;
    final checkValue = config['checkValue'];

    String _name(String? kindId, String fallback) {
      if (kindId == null) return fallback;
      if (kindToLabel != null) return kindToLabel[kindId] ?? kindId;
      return game.observationName(kindId);
    }

    final markerName = _name(markerKind, 'target');
    final checkName = _name(checkKind, 'piece');

    if (checkParam == 'sides' && checkValue == 15) {
      return 'Fill every $markerName cell with a complete $checkName (all 4 sides connected)';
    }
    return 'Place a $checkName on every $markerName where $checkParam = ${pyStr(checkValue)}';
  }

  /// Parses a single-action reply; see [extractActionList] for the
  /// [unrecognisedAction] fallback.
  static GameAction extractAction(String text, AgentObservation obs,
      {Map<String, GameAction>? anonMap}) {
    final jsonMatch = RegExp(r'\{[^}]+\}').firstMatch(text);
    if (jsonMatch != null) {
      try {
        final map = jsonDecode(jsonMatch.group(0)!) as Map<String, dynamic>;
        final actionId = map['action'] as String?;
        if (actionId == 'give_up') return GameAction('give_up', {});
        if (actionId != null) {
          if (anonMap != null) {
            final real = anonMap[actionId];
            if (real != null) return real;
          } else {
            final params = Map<String, dynamic>.from(map)
              ..remove('action')
              ..remove('memory');
            final match = obs.validActions
                .where((a) =>
                    a.actionId == actionId &&
                    a.params.length == params.length &&
                    params.entries.every((e) => a.params[e.key] == e.value))
                .firstOrNull;
            if (match != null) return match;
          }
        }
      } catch (_) {}
    }
    return unrecognisedAction;
  }

  /// Returns the UI name of the entity identified by [kindId] or [tag].
  /// Looks up [kindId] directly, or searches for the first entity kind whose
  /// tags contain [tag]. Falls back to the kind id or tag string.
  static String _resolveEntityName(
      GameDefinition game, String? kindId, String? tag) {
    if (kindId != null) {
      return game.observationName(kindId);
    }
    if (tag != null) {
      for (final entry in game.entityKinds.entries) {
        if (entry.value.tags.contains(tag)) {
          return game.observationName(entry.key);
        }
      }
      return tag;
    }
    return 'target';
  }

  /// Anonymous version: resolves entity kind (via kindId or tag) then looks up
  /// its label in [kindToLabel]. Falls back to a generic '?' if unresolved.
  static String _resolveEntityNameAnon(GameDefinition game, String? kindId,
      String? tag, Map<String, String> kindToLabel) {
    // Resolve to a kindId first.
    String? resolvedKind = kindId;
    if (resolvedKind == null && tag != null) {
      for (final entry in game.entityKinds.entries) {
        if (entry.value.tags.contains(tag)) {
          resolvedKind = entry.key;
          break;
        }
      }
    }
    if (resolvedKind != null) {
      return kindToLabel[resolvedKind] ?? resolvedKind;
    }
    return '?';
  }

  String? _extractMemory(String text) {
    final jsonMatch = RegExp(r'\{[^}]+\}').firstMatch(text);
    if (jsonMatch != null) {
      try {
        final map = jsonDecode(jsonMatch.group(0)!) as Map<String, dynamic>;
        return map['memory'] as String?;
      } catch (_) {}
    }
    return null;
  }
}

class LlmAgentException implements Exception {
  final String message;
  const LlmAgentException(this.message);
  @override
  String toString() => 'LlmAgentException: $message';
}
