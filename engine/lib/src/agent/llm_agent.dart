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

  String _memory;

  /// The most recent prompt sent to the LLM. Null before the first call.
  String? lastPrompt;

  LlmAgent({
    required ChatCapability provider,
    required String displayName,
    String initialMemory = '',
  })  : _provider = provider,
        _displayName = displayName,
        _memory = initialMemory;

  @override
  String get name => _displayName;

  /// Current persistent memory (for inspection / seeding next level).
  String get memory => _memory;

  @override
  Stream<AgentActEvent> act(AgentObservation obs) async* {
    final prompt = LlmAgent.buildPrompt(obs, memory: _memory);
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
    final action = _extractAction(responseText, obs);
    final memoryUpdate = _extractMemory(responseText);
    if (memoryUpdate != null) _memory = memoryUpdate;

    final thinking = thinkingBuffer.isNotEmpty
        ? thinkingBuffer.toString()
        : responseText;

    yield AgentActCompleted(
      AgentActResult(action, thinking: thinking, memoryUpdate: memoryUpdate),
    );
  }

  /// Builds the LLM prompt for the given observation.
  ///
  /// Public and static so external tools (e.g. the benchmark runner) can
  /// produce identical prompts without instantiating an [LlmAgent].
  static String buildPrompt(AgentObservation obs, {String memory = ''}) {
    final goalParts = <String>[];
    for (final g in obs.level.goals) {
      switch (g.type) {
        case 'reach_target':
          final name = _resolveEntityName(
              obs.game, g.config['targetKind'] as String?,
              g.config['targetTag'] as String?);
          goalParts.add('Reach the $name');
        case 'board_match':
          final targetGrid = _renderTargetGrid(obs.game, g.config);
          if (targetGrid != null) {
            goalParts.add('Arrange tiles to match the target pattern:\n$targetGrid');
          } else {
            goalParts.add('Arrange tiles to match the target pattern');
          }
        case 'sequence_match':
          final sequence = (g.config['sequence'] as List?)
              ?.map((e) => e as int)
              .toList() ?? [];
          final matched = obs.state.sequenceIndices[g.id] ?? 0;
          final done = sequence.take(matched).map((n) => '✓$n').join(', ');
          final pending = sequence.skip(matched).map((n) => '$n').join(', ');
          final progress = [if (done.isNotEmpty) done, if (pending.isNotEmpty) pending].join(', ');
          goalParts.add('Merge numbers in sequence [$progress] ($matched/${sequence.length} done)');
        case 'all_cleared':
          final name = _resolveEntityName(
              obs.game, g.config['kind'] as String?,
              g.config['tag'] as String?);
          goalParts.add('Clear all ${name}s from the board');
        case 'sum_constraint':
          goalParts.add(_describeSumConstraint(g.config));
        case 'count_constraint':
          goalParts.add(_describeCountConstraint(g.config));
        case 'param_match':
          goalParts.add(_describeParamMatch(obs.game, g.config));
        default:
          goalParts.add(g.type);
      }
    }
    final goalDescriptions = goalParts.join('; ');

    final actionsDesc = obs.validActions
        .map((a) => jsonEncode(a.toJson()))
        .join(', ');

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

    final lastActionSection = obs.lastAction != null
        ? '''
LAST ACTION: ${jsonEncode(obs.lastAction!.toJson())}
BOARD BEFORE:
${obs.previousBoardText}$prevInventoryLine

BOARD AFTER (current):
${obs.boardText}$inventoryLine$movesLine

Compare the two boards to understand exactly what your last action did (tiles removed, pushed, merged, etc.).
If your inventory changed, note what was gained or lost.
Update your memory with any new observations about game mechanics or level layout.
Memory is your only way to retain knowledge across actions.'''
        : '''
CURRENT BOARD (first move of this attempt):
${obs.boardText}$inventoryLine$movesLine''';

    final descriptionSection = obs.game.description.isNotEmpty
        ? '\n${obs.game.description}\n'
        : '';

    return '''You are playing a grid puzzle called "${obs.game.title}".
Attempt ${obs.attemptNumber} | Total actions across all attempts: ${obs.totalActionsAllAttempts}
Minimize total actions — give up early if stuck rather than wasting moves.
$descriptionSection$memorySection
GOAL: $goalDescriptions
$lastActionSection

AVAILABLE ACTIONS (pick exactly one):
$actionsDesc
{"action": "give_up"} — reset and start a fresh attempt

Respond with ONLY a JSON object on a single line.
You may optionally update your persistent memory by adding a "memory" field (replaces previous memory).
Examples:
  {"action": "move", "direction": "right"}
  {"action": "move", "direction": "left", "memory": "Torch burns wood. Plan: get torch at top-left first."}
  {"action": "give_up", "memory": "Pushing crate right is a dead end. Must go left first, then up."}

Choose the action most likely to reach the goal in fewest total actions (summed across attempts).''';
  }

  /// Renders the targetLayers config of a board_match goal as an ASCII grid.
  /// Returns null if the config has no renderable target.
  static String? _renderTargetGrid(
      GameDefinition game, Map<String, dynamic> config) {
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
          final sym = game.entityKinds[kindId]?.symbol ?? kindId[0];
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
      GameDefinition game, Map<String, dynamic> config) {
    final markerKind = config['markerKind'] as String?;
    final checkKind = config['checkKind'] as String?;
    final checkParam = config['checkParam'] as String?;
    final checkValue = config['checkValue'];

    final markerName = markerKind != null
        ? (game.entityKinds[markerKind]?.uiName ??
            markerKind.replaceAll('_', ' '))
        : 'target';
    final checkName = checkKind != null
        ? (game.entityKinds[checkKind]?.uiName ??
            checkKind.replaceAll('_', ' '))
        : 'piece';

    if (checkParam == 'sides' && checkValue == 15) {
      return 'Fill every $markerName cell with a complete $checkName (all 4 sides connected)';
    }
    return 'Place a $checkName on every $markerName where $checkParam = $checkValue';
  }

  GameAction _extractAction(String text, AgentObservation obs) {
    final jsonMatch = RegExp(r'\{[^}]+\}').firstMatch(text);
    if (jsonMatch != null) {
      try {
        final map = jsonDecode(jsonMatch.group(0)!) as Map<String, dynamic>;
        final actionId = map['action'] as String?;
        if (actionId == 'give_up') return GameAction('give_up', {});
        if (actionId != null) {
          final params = Map<String, dynamic>.from(map)
            ..remove('action')
            ..remove('memory');
          final candidate = GameAction(actionId, params);
          if (obs.game.isValidAction(candidate)) return candidate;
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
