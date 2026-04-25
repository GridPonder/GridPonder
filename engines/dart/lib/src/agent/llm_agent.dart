import 'dart:async';
import 'dart:convert';

import 'package:llm_dart/llm_dart.dart';

import 'agent.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';

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
        gpt4o     => 'GPT-4o',
        o4Mini    => 'o4-mini (reasoning)',
        o3        => 'o3 (reasoning)',
        _         => modelId,
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
        flash2  => 'Gemini 2.0 Flash',
        flash25 => 'Gemini 2.5 Flash (thinking)',
        pro25   => 'Gemini 2.5 Pro (thinking)',
        _       => modelId,
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
    gemma4e2b, gemma4e4b,
    qwen35_0_8b, qwen35_2b, qwen35_4b, qwen35_9b,
    gptOss20b,
  ];

  static String displayName(String modelId) => switch (modelId) {
        gemma4e2b    => 'Gemma 4 E2B',
        gemma4e4b    => 'Gemma 4 E4B',
        qwen35_0_8b  => 'Qwen 3.5 0.8B',
        qwen35_2b    => 'Qwen 3.5 2B',
        qwen35_4b    => 'Qwen 3.5 4B',
        qwen35_9b    => 'Qwen 3.5 9B',
        gptOss20b    => 'GPT-OSS 20B',
        _            => modelId,
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
    );
    lastPrompt = prompt;

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
      final action = _extractAction(responseText, obs, anonMap: anonMap);
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
          _extractActionList(responseText, obs, anonMap: anonMap);
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
  (List<GameAction>, String?) _extractActionList(
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
      return ([
        obs.validActions.isNotEmpty
            ? obs.validActions.first
            : GameAction('noop', {})
      ], null);
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
      final match = obs.validActions.where((a) =>
        a.actionId == actionId &&
        a.params.length == params.length &&
        params.entries.every((e) => a.params[e.key] == e.value)
      ).firstOrNull;
      if (match != null) result.add(match);
    }

    if (result.isEmpty) {
      return ([
        obs.validActions.isNotEmpty
            ? obs.validActions.first
            : GameAction('noop', {})
      ], memoryUpdate);
    }
    return (result, memoryUpdate);
  }

  /// Builds the LLM prompt for the given observation.
  ///
  /// Public and static so external tools (e.g. the benchmark runner) can
  /// produce identical prompts without instantiating an [LlmAgent].
  ///
  /// When [anonymize] is true, entity kind names, action IDs, and game
  /// description are replaced with opaque labels (ARC-AGI style).
  static String buildPrompt(
    AgentObservation obs, {
    String memory = '',
    String inferenceMode = 'single',
    int stepSize = 3,
    int? maxN,
    bool anonymize = false,
  }) {
    // ── Anon maps ────────────────────────────────────────────────────────────
    final kindToLabel =
        anonymize ? buildAnonKindToLabel(obs.game) : const <String, String>{};
    // Forward map: jsonEncoded action → anon label (a1, a2, …)
    final Map<String, String> actionForward;
    if (anonymize) {
      final sorted = List<GameAction>.from(obs.validActions)
        ..sort((a, b) => jsonEncode(a.toJson()).compareTo(jsonEncode(b.toJson())));
      actionForward = {
        for (int i = 0; i < sorted.length; i++)
          jsonEncode(sorted[i].toJson()): 'a${i + 1}',
      };
    } else {
      actionForward = {};
    }

    // ── Goals ─────────────────────────────────────────────────────────────────
    final goalParts = <String>[];
    for (final g in obs.level.goals) {
      // Per-game goal-text override (set in game.json `goalDescriptions`).
      // Skipped in anonymise mode since the override may name entities.
      if (!anonymize) {
        final override = obs.game.goalDescriptions[g.id];
        if (override != null) {
          goalParts.add(override);
          continue;
        }
      }
      switch (g.type) {
        case 'reach_target':
          final kindId = g.config['targetKind'] as String?;
          final tag = g.config['targetTag'] as String?;
          final name = anonymize
              ? _resolveEntityNameAnon(obs.game, kindId, tag, kindToLabel)
              : _resolveEntityName(obs.game, kindId, tag);
          goalParts.add('Reach the $name');
        case 'board_match':
          final targetGrid = _renderTargetGrid(obs.game, g.config,
              kindToLabel: anonymize ? kindToLabel : null);
          if (targetGrid != null) {
            goalParts.add('Arrange tiles to match the target pattern:\n$targetGrid');
          } else {
            goalParts.add('Arrange tiles to match the target pattern');
          }
        case 'sequence_match':
          final sequence = (g.config['sequence'] as List?)
                  ?.map((e) => e as int)
                  .toList() ??
              [];
          final matched = obs.state.sequenceIndices[g.id] ?? 0;
          final done = sequence.take(matched).map((n) => '✓$n').join(', ');
          final pending = sequence.skip(matched).map((n) => '$n').join(', ');
          final progress = [
            if (done.isNotEmpty) done,
            if (pending.isNotEmpty) pending
          ].join(', ');
          goalParts.add(
              'Merge numbers in sequence [$progress] ($matched/${sequence.length} done)');
        case 'all_cleared':
          final kindId = g.config['kind'] as String?;
          final tag = g.config['tag'] as String?;
          final name = anonymize
              ? _resolveEntityNameAnon(obs.game, kindId, tag, kindToLabel)
              : _resolveEntityName(obs.game, kindId, tag);
          goalParts.add('Clear all ${name}s from the board');
        case 'sum_constraint':
          goalParts.add(_describeSumConstraint(g.config));
        case 'count_constraint':
          goalParts.add(_describeCountConstraint(g.config));
        case 'param_match':
          goalParts.add(_describeParamMatch(obs.game, g.config,
              kindToLabel: anonymize ? kindToLabel : null));
        default:
          goalParts.add(g.type);
      }
    }
    final goalDescriptions = goalParts.join('; ');

    // ── Actions desc ──────────────────────────────────────────────────────────
    final actionsDesc = anonymize
        ? obs.validActions
            .map((a) {
              final label = actionForward[jsonEncode(a.toJson())] ?? '?';
              return '{"action": "$label"}';
            })
            .join(', ')
        : obs.validActions.map((a) => jsonEncode(a.toJson())).join(', ');

    // ── Inventory / moves ─────────────────────────────────────────────────────
    final inv = obs.state.avatar.inventory.slot;
    final inventoryLine = inv != null ? '\nInventory: $inv' : '';

    final movesLine = obs.level.loseConditions.isNotEmpty
        ? '\nMoves this attempt: ${obs.state.actionCount}'
        : '';

    final memorySection = memory.isNotEmpty
        ? '\nMEMORY FROM PREVIOUS ACTION:\n$memory\n'
        : '';

    final prevInventoryLine = obs.previousInventory != null
        ? '\nInventory: ${obs.previousInventory}'
        : '';

    // ── Last action section ───────────────────────────────────────────────────
    final String lastActionLabel;
    if (obs.lastAction != null && anonymize) {
      final label = actionForward[jsonEncode(obs.lastAction!.toJson())] ?? '?';
      lastActionLabel = '{"action": "$label"}';
    } else if (obs.lastAction != null) {
      lastActionLabel = jsonEncode(obs.lastAction!.toJson());
    } else {
      lastActionLabel = '';
    }

    final lastActionSection = obs.lastAction != null
        ? '''
LAST ACTION: $lastActionLabel
BOARD BEFORE:
${obs.previousBoardText}$prevInventoryLine

BOARD AFTER (current):
${obs.boardText}$inventoryLine$movesLine

Compare the two boards to understand exactly what your last action did (tiles removed, pushed, merged, etc.).
${(inv != null || obs.previousInventory != null) ? 'If your inventory changed, note what was gained or lost.\n' : ''}Update your memory with any new observations about game mechanics or level layout.
Memory is your only way to retain knowledge across actions.'''
        : '''
CURRENT BOARD (first move of this attempt):
${obs.boardText}$inventoryLine$movesLine''';

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
      ex1 = va.isNotEmpty ? jsonEncode(va.first.toJson()) : '{"action": "..."}';
      ex2 = va.length > 1 ? jsonEncode(va.last.toJson()) : ex1;
    }

    return '$header\n\n${_promptTail(inferenceMode, stepSize, maxN, ex1: ex1, ex2: ex2)}';
  }

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

  /// Renders the targetLayers config of a board_match goal as an ASCII grid.
  /// Returns null if the config has no renderable target.
  /// When [kindToLabel] is provided, entity kinds are shown as their labels.
  static String? _renderTargetGrid(
      GameDefinition game, Map<String, dynamic> config,
      {Map<String, String>? kindToLabel}) {
    final targetLayers = config['targetLayers'] as Map<String, dynamic>?;
    if (targetLayers == null || targetLayers.isEmpty) return null;

    // Collect the dimensions from any layer.
    int? height;
    int? width;
    for (final rows in targetLayers.values) {
      final rowList = rows as List;
      height = rowList.length;
      width = (rowList.first as List).length;
      break;
    }
    if (height == null || width == null) return null;

    final grid = List.generate(height, (_) => List.filled(width!, '.'));

    for (final layerEntry in targetLayers.entries) {
      final rows = layerEntry.value as List;
      for (int y = 0; y < rows.length; y++) {
        final row = rows[y] as List;
        for (int x = 0; x < row.length; x++) {
          final kindId = row[x] as String?;
          if (kindId == null) continue;
          final sym = kindToLabel != null
              ? (kindToLabel[kindId] ?? kindId[0])
              : (game.entityKinds[kindId]?.symbol ?? kindId[0]);
          grid[y][x] = sym;
        }
      }
    }

    return grid.map((row) => row.join()).join('\n');
  }

  static String _describeSumConstraint(Map<String, dynamic> config) {
    final scope = config['scope'] as String? ?? 'board';
    final target = config['target'];
    final comparison = config['comparison'] as String? ?? 'eq';
    final index = config['index'];

    final scopeLabel = switch (scope) {
      'all_rows' => 'every row',
      'all_cols' => 'every column',
      'row' => 'row ${index ?? '?'}',
      'col' => 'column ${index ?? '?'}',
      _ => scope,
    };
    final opLabel = switch (comparison) {
      'eq' => '= $target',
      'gte' => '≥ $target',
      'lte' => '≤ $target',
      _ => '$comparison $target',
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
      'row' => 'row ${index ?? '?'}',
      'col' => 'column ${index ?? '?'}',
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
      return game.entityKinds[kindId]?.uiName ?? kindId.replaceAll('_', ' ');
    }

    final markerName = _name(markerKind, 'target');
    final checkName = _name(checkKind, 'piece');

    if (checkParam == 'sides' && checkValue == 15) {
      return 'Fill every $markerName cell with a complete $checkName (all 4 sides connected)';
    }
    return 'Place a $checkName on every $markerName where $checkParam = $checkValue';
  }

  GameAction _extractAction(String text, AgentObservation obs,
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
    return obs.validActions.isNotEmpty
        ? obs.validActions.first
        : GameAction('noop', {});
  }

  /// Returns the UI name of the entity identified by [kindId] or [tag].
  /// Looks up [kindId] directly, or searches for the first entity kind whose
  /// tags contain [tag]. Falls back to the kind id or tag string.
  static String _resolveEntityName(
      GameDefinition game, String? kindId, String? tag) {
    if (kindId != null) {
      return game.entityKinds[kindId]?.uiName ??
          kindId.replaceAll('_', ' ');
    }
    if (tag != null) {
      for (final entry in game.entityKinds.entries) {
        if (entry.value.tags.contains(tag)) {
          return entry.value.uiName ?? entry.key.replaceAll('_', ' ');
        }
      }
      return tag;
    }
    return 'target';
  }

  /// Anonymous version: resolves entity kind (via kindId or tag) then looks up
  /// its label in [kindToLabel]. Falls back to a generic '?' if unresolved.
  static String _resolveEntityNameAnon(
      GameDefinition game,
      String? kindId,
      String? tag,
      Map<String, String> kindToLabel) {
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
