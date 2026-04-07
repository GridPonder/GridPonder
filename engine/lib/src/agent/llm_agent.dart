import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

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

/// Agent that calls the Anthropic Messages API to choose actions.
///
/// Maintains a persistent [_memory] string across level resets that survives
/// as long as this agent instance is alive. The memory is injected into every
/// prompt and can be updated by the model by including a "memory" field in its
/// JSON response.
class LlmAgent implements GridPonderAgent {
  final String apiKey;
  final String model;
  final bool thinkingEnabled;
  final int maxTokens;

  /// Seed memory from a previous session on the same level.
  String _memory;

  /// The most recent prompt sent to the API. Null before the first call.
  String? lastPrompt;

  LlmAgent({
    required this.apiKey,
    this.model = AnthropicModel.haiku,
    this.thinkingEnabled = false,
    this.maxTokens = 1024,
    String initialMemory = '',
  }) : _memory = initialMemory;

  @override
  String get name {
    final modelShort = AnthropicModel.displayName(model);
    final thinkTag = thinkingEnabled && AnthropicModel.supportsThinking(model)
        ? ' + thinking'
        : '';
    return 'LLM ($modelShort$thinkTag)';
  }

  /// Current persistent memory (for inspection).
  String get memory => _memory;

  @override
  Stream<AgentActEvent> act(AgentObservation obs) async* {
    final prompt = _buildPrompt(obs);
    lastPrompt = prompt;
    final useThinking =
        thinkingEnabled && AnthropicModel.supportsThinking(model);

    final body = <String, dynamic>{
      'model': model,
      'max_tokens': maxTokens + (useThinking ? 8000 : 0),
      'stream': true,
      'messages': [
        {'role': 'user', 'content': prompt}
      ],
    };

    if (useThinking) {
      body['thinking'] = {'type': 'enabled', 'budget_tokens': 8000};
    }

    final request = http.Request(
      'POST',
      Uri.parse('https://api.anthropic.com/v1/messages'),
    );
    request.headers.addAll({
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
      'content-type': 'application/json',
    });
    request.body = jsonEncode(body);

    final client = http.Client();
    late http.StreamedResponse response;
    try {
      response = await client.send(request);
    } catch (e) {
      client.close();
      throw LlmAgentException('Network error: $e');
    }

    if (response.statusCode != 200) {
      final body = await response.stream.bytesToString();
      client.close();
      throw LlmAgentException(
          'Anthropic API error ${response.statusCode}: $body');
    }

    final thinkingBuffer = StringBuffer();
    final textBuffer = StringBuffer();

    await for (final line in response.stream
        .transform(utf8.decoder)
        .transform(const LineSplitter())) {
      if (!line.startsWith('data: ')) continue;
      final data = line.substring(6).trim();
      if (data == '[DONE]') break;

      Map<String, dynamic> event;
      try {
        event = jsonDecode(data) as Map<String, dynamic>;
      } catch (_) {
        continue;
      }

      if (event['type'] == 'content_block_delta') {
        final delta = event['delta'] as Map<String, dynamic>?;
        if (delta == null) continue;
        switch (delta['type'] as String?) {
          case 'thinking_delta':
            final chunk = delta['thinking'] as String? ?? '';
            if (chunk.isNotEmpty) {
              thinkingBuffer.write(chunk);
              yield AgentThinkingDelta(chunk);
            }
          case 'text_delta':
            textBuffer.write(delta['text'] as String? ?? '');
        }
      }
    }

    client.close();

    final responseText = textBuffer.toString();
    final action = _extractAction(responseText, obs);
    final memoryUpdate = _extractMemory(responseText);

    // Persist updated memory inside this agent instance.
    if (memoryUpdate != null) _memory = memoryUpdate;

    final thinking = thinkingBuffer.isNotEmpty
        ? thinkingBuffer.toString()
        : responseText;

    yield AgentActCompleted(
      AgentActResult(action, thinking: thinking, memoryUpdate: memoryUpdate),
    );
  }

  String _buildPrompt(AgentObservation obs) {
    final goalDescriptions = obs.level.goals.map((g) {
      switch (g.type) {
        case 'reach_target':
          final name = _resolveEntityName(
              obs.game, g.config['targetKind'] as String?,
              g.config['targetTag'] as String?);
          return 'Reach the $name';
        case 'board_match':
          return 'Arrange tiles to match the target pattern';
        case 'sequence_match':
          final sequence = (g.config['sequence'] as List?)
              ?.map((e) => e as int)
              .toList() ?? [];
          final matched = obs.state.sequenceIndices[g.id] ?? 0;
          final done = sequence.take(matched).map((n) => '✓$n').join(', ');
          final pending = sequence.skip(matched).map((n) => '$n').join(', ');
          final progress = [if (done.isNotEmpty) done, if (pending.isNotEmpty) pending].join(', ');
          return 'Merge numbers in sequence [$progress] ($matched/${sequence.length} done)';
        case 'all_cleared':
          final name = _resolveEntityName(
              obs.game, g.config['kind'] as String?,
              g.config['tag'] as String?);
          return 'Clear all ${name}s from the board';
        default:
          return g.type;
      }
    }).join('; ');

    final actionsDesc = obs.validActions
        .map((a) => jsonEncode(a.toJson()))
        .join(', ');

    final inv = obs.state.avatar.inventory.slot;
    final inventoryLine = inv != null ? '\nInventory: $inv' : '';

    final movesLine = obs.level.loseConditions.isNotEmpty
        ? '\nMoves this attempt: ${obs.state.actionCount}'
        : '';

    final memorySection = _memory.isNotEmpty
        ? '\nMEMORY FROM PREVIOUS ACTION:\n$_memory\n'
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
      return game.entityKinds[kindId]?.uiName ?? kindId;
    }
    if (tag != null) {
      for (final entry in game.entityKinds.entries) {
        if (entry.value.tags.contains(tag)) {
          return entry.value.uiName ?? entry.key;
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
