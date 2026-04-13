// Game-loop runner for AI benchmarking.
//
// Communicates via newline-delimited JSON on stdin/stdout:
//   stdout → Python: state / reset / rejected / won / lost events
//   stdin  ← Python:
//     single mode:  {"action": "...", ...params, "memory": "..."}
//     other modes:  {"actions": [...], "memory": "..."} or single format
//
// Inference modes:
//   single  — one action per LLM call (default, backwards-compatible)
//   fixed-n — up to step-size actions per LLM call (model may output fewer)
//   flex-n  — 1 to max-n actions per call, model chooses; extra steps penalised
//   full    — all actions in one call; no intermediate feedback, one attempt
//
// give_up counts as 1 action toward the total action budget;
// auto-reset triggers when actionCount >= action_limit_per_attempt
// (not applicable in full mode).

import 'dart:convert';
import 'dart:io';

import 'package:args/args.dart';
import 'package:gridponder_engine/engine.dart';

Future<void> main(List<String> arguments) async {
  final parser = ArgParser()
    ..addOption('pack', abbr: 'p', help: 'Pack ID', mandatory: true)
    ..addOption('level', abbr: 'l', help: 'Level ID', mandatory: true)
    ..addOption('packs-dir',
        help: 'Absolute path to the packs/ directory', defaultsTo: null)
    ..addOption('attempt-multiplier',
        help: 'action_limit_per_attempt = M × gold_path_length',
        defaultsTo: '2')
    ..addOption('total-multiplier',
        help: 'action_limit = M × gold_path_length  (give_up counts as 1)',
        defaultsTo: '3')
    ..addOption('mode',
        help: 'Inference mode',
        allowed: ['single', 'fixed-n', 'full', 'flex-n'],
        defaultsTo: 'single')
    ..addOption('step-size',
        help: 'Max actions per LLM call (fixed-n mode)', defaultsTo: '1')
    ..addOption('max-n',
        help: 'Max actions per LLM call (flex-n mode, default: unlimited)',
        defaultsTo: null);

  late final ArgResults args;
  try {
    args = parser.parse(arguments);
  } catch (e) {
    stderr.writeln('Error: $e\n${parser.usage}');
    exitCode = 1;
    return;
  }

  final packId = args['pack'] as String;
  final levelId = args['level'] as String;
  final packsDir = args['packs-dir'] as String? ?? _defaultPacksDir();
  final attemptMul = int.parse(args['attempt-multiplier'] as String);
  final totalMul = int.parse(args['total-multiplier'] as String);
  final mode = args['mode'] as String;
  final stepSize = int.parse(args['step-size'] as String);
  final maxNStr = args['max-n'] as String?;
  final maxN = maxNStr != null ? int.parse(maxNStr) : null;

  // ── Load pack ─────────────────────────────────────────────────────────────
  final packDir = '$packsDir/$packId';
  Map<String, dynamic> manifestJson, gameJson;
  Map<String, dynamic>? themeJson;
  try {
    manifestJson = _readJson('$packDir/manifest.json');
    gameJson = _readJson('$packDir/game.json');
    final themeFile = File('$packDir/theme.json');
    if (themeFile.existsSync()) {
      themeJson = _readJson('$packDir/theme.json');
    }
  } catch (e) {
    _die('Cannot load pack "$packId": $e');
    return;
  }

  final levelJsons = <String, Map<String, dynamic>>{};
  for (final entry in ((gameJson['levelSequence'] as List?)
          ?.cast<Map<String, dynamic>>() ??
      [])) {
    if (entry['type'] != 'level') continue;
    final ref = entry['ref'] as String;
    final f = File('$packDir/levels/$ref.json');
    if (f.existsSync()) {
      levelJsons[ref] = _readJson('$packDir/levels/$ref.json');
    }
  }

  if (!levelJsons.containsKey(levelId)) {
    _die('Level "$levelId" not found in pack "$packId".');
    return;
  }

  final pack = PackLoader.load(
    manifestJson: manifestJson,
    gameJson: gameJson,
    themeJson: themeJson,
    levelJsons: levelJsons,
  );

  final gameDef = pack.game;
  final levelDef = pack.levels[levelId]!;
  final goldPathLen = levelDef.solution.goldPath.length;

  final limitPerAttempt = goldPathLen > 0
      ? attemptMul * goldPathLen
      : (attemptMul * 10).clamp(10, 60);
  final limitTotal = goldPathLen > 0
      ? totalMul * goldPathLen
      : (totalMul * 10).clamp(10, 100);

  // ── Game state ────────────────────────────────────────────────────────────
  final engine = TurnEngine(gameDef, levelDef);
  int attemptNumber = 1;
  int totalGameActions = 0;
  int giveUpCount = 0;
  String memory = '';
  int consecutiveRejections = 0;
  // Cap: if the model can't produce a single accepted action in this many
  // consecutive calls, declare a loss. Prevents infinite loops when a model
  // consistently hallucinates invalid actions for a level.
  const maxConsecutiveRejections = 5;

  GameAction? lastAction;
  String? prevBoardText;
  String? prevInventory;

  // ── Helpers ───────────────────────────────────────────────────────────────
  void out(Map<String, dynamic> event) => stdout.writeln(jsonEncode(event));

  void emitState() {
    final totalNow = totalGameActions + giveUpCount;
    final obs = AgentObservation.build(
      gameDef,
      levelDef,
      engine.state,
      attemptNumber: attemptNumber,
      totalActionsAllAttempts: totalNow,
      lastAction: lastAction,
      previousBoardText: prevBoardText,
      previousInventory: prevInventory,
    );

    final prompt = LlmAgent.buildPrompt(
      obs,
      memory: memory,
      inferenceMode: mode,
      stepSize: stepSize,
      maxN: maxN,
    );

    out({
      'event': 'state',
      'prompt': prompt,
      'valid_actions': [
        ...obs.validActions.map((a) => a.toJson()),
        {'action': 'give_up'},
      ],
      'actions_this_attempt': engine.state.actionCount,
      'actions_total': totalNow,
      'action_limit_per_attempt': limitPerAttempt,
      'action_limit': limitTotal,
      'attempt': attemptNumber,
      'gold_path_length': goldPathLen,
      'level_id': levelId,
      'pack_id': packId,
      'inference_mode': mode,
      if (mode == 'fixed-n') 'step_size': stepSize,
      if (mode == 'flex-n') 'max_n': maxN,
    });
  }

  void doReset({required String reason}) {
    engine.reset();
    attemptNumber++;
    lastAction = null;
    prevBoardText = null;
    prevInventory = null;
    out({
      'event': 'reset',
      'attempt': attemptNumber,
      'reason': reason,
      'actions_total': totalGameActions + giveUpCount,
    });
  }

  Map<String, dynamic> wonEvent() => {
        'event': 'won',
        'actions_this_attempt': engine.state.actionCount,
        'actions_total': totalGameActions + giveUpCount,
        'attempts': attemptNumber,
        'gold_path_length': goldPathLen,
      };

  Map<String, dynamic> lostEvent() => {
        'event': 'lost',
        'actions_this_attempt': engine.state.actionCount,
        'actions_total': totalGameActions + giveUpCount,
        'attempts': attemptNumber,
        'gold_path_length': goldPathLen,
      };

  // ── Initial state ─────────────────────────────────────────────────────────
  emitState();

  // ── Main loop ─────────────────────────────────────────────────────────────
  await for (final raw
      in stdin.transform(utf8.decoder).transform(const LineSplitter())) {
    final trimmed = raw.trim();
    if (trimmed.isEmpty) continue;

    Map<String, dynamic> input;
    try {
      input = jsonDecode(trimmed) as Map<String, dynamic>;
    } catch (_) {
      stderr.writeln('Bad JSON from orchestrator: $trimmed');
      continue;
    }

    // Top-level memory update applies to both single and multi-action input.
    final memUpdate = input['memory'] as String?;
    if (memUpdate != null) memory = memUpdate;

    // ── single mode: exact original behaviour ─────────────────────────────
    if (mode == 'single') {
      final actionId = input['action'] as String?;
      if (actionId == null) {
        stderr.writeln('Missing "action" field: $trimmed');
        continue;
      }

      if (actionId == 'give_up') {
        consecutiveRejections = 0;
        giveUpCount++;
        final totalNow = totalGameActions + giveUpCount;
        doReset(reason: 'voluntary');
        if (totalNow >= limitTotal) {
          out(lostEvent());
          break;
        }
        emitState();
        continue;
      }

      prevBoardText =
          TextRenderer.render(engine.state, gameDef, includeLegend: false);
      prevInventory = engine.state.avatar.enabled
          ? engine.state.avatar.inventory.slot
          : null;

      final params = Map<String, dynamic>.from(input)
        ..remove('action')
        ..remove('memory');
      final gameAction = GameAction(actionId, params);
      final result = engine.executeTurn(gameAction);

      if (!result.accepted) {
        prevBoardText = null;
        prevInventory = null;
        consecutiveRejections++;
        out({'event': 'rejected', 'action': input});
        if (consecutiveRejections >= maxConsecutiveRejections) {
          out(lostEvent());
          break;
        }
        emitState();
        continue;
      }

      consecutiveRejections = 0;
      lastAction = gameAction;
      totalGameActions++;
      final totalNow = totalGameActions + giveUpCount;

      if (engine.isWon) {
        out(wonEvent());
        break;
      }
      if (engine.isLost) {
        out(lostEvent());
        break;
      }
      if (engine.state.actionCount >= limitPerAttempt) {
        doReset(reason: 'limit');
      }
      if (totalNow >= limitTotal) {
        out(lostEvent());
        break;
      }
      emitState();
      continue;
    }

    // ── multi-action modes: fixed-n, flex-n, full ─────────────────────────
    final actions = _extractActionList(input,
        maxAllowed: mode == 'fixed-n'
            ? stepSize
            : mode == 'flex-n'
                ? maxN
                : null);

    if (actions == null || actions.isEmpty) {
      stderr.writeln('No valid actions found in input: $trimmed');
      continue;
    }

    bool outerBreak = false;

    for (final actionInput in actions) {
      final actionId = actionInput['action'] as String?;
      if (actionId == null) continue;

      // give_up: in full mode, treat as "done" → lost.
      // In interactive modes (fixed-n, flex-n), process as normal reset.
      if (actionId == 'give_up') {
        consecutiveRejections = 0;
        if (mode == 'full') {
          out(lostEvent());
          outerBreak = true;
        } else {
          giveUpCount++;
          final totalNow = totalGameActions + giveUpCount;
          doReset(reason: 'voluntary');
          if (totalNow >= limitTotal) {
            out(lostEvent());
            outerBreak = true;
          }
          // Stop batch after give_up regardless; emit new state below.
        }
        break;
      }

      // Capture board before execution (used in next state prompt).
      prevBoardText =
          TextRenderer.render(engine.state, gameDef, includeLegend: false);
      prevInventory = engine.state.avatar.enabled
          ? engine.state.avatar.inventory.slot
          : null;

      final params = Map<String, dynamic>.from(actionInput)
        ..remove('action')
        ..remove('memory');
      final gameAction = GameAction(actionId, params);
      final result = engine.executeTurn(gameAction);

      if (!result.accepted) {
        prevBoardText = null;
        prevInventory = null;
        consecutiveRejections++;
        out({'event': 'rejected', 'action': actionInput});
        if (consecutiveRejections >= maxConsecutiveRejections) {
          outerBreak = true;
          out(lostEvent());
        }
        // Stop batch on first rejection; emit new state below.
        break;
      }

      consecutiveRejections = 0;
      lastAction = gameAction;
      totalGameActions++;
      final totalNow = totalGameActions + giveUpCount;

      if (engine.isWon) {
        out(wonEvent());
        outerBreak = true;
        break;
      }
      if (engine.isLost) {
        out(lostEvent());
        outerBreak = true;
        break;
      }

      // Per-attempt limit hit mid-batch (not applicable in full mode).
      if (mode != 'full' && engine.state.actionCount >= limitPerAttempt) {
        doReset(reason: 'limit');
        if (totalNow >= limitTotal) {
          out(lostEvent());
          outerBreak = true;
        }
        break; // stop batch; emit new state below if not terminal
      }

      if (totalNow >= limitTotal) {
        out(lostEvent());
        outerBreak = true;
        break;
      }
    }

    if (outerBreak) break;

    // full mode: if batch exhausted without winning, it's a loss.
    if (mode == 'full') {
      out(lostEvent());
      break;
    }

    // interactive modes: ask for the next batch of actions.
    emitState();
  }
}

// ── Input parsing ─────────────────────────────────────────────────────────────

/// Parses the actions list from multi-action mode input.
/// Accepts both {"actions": [...]} and single {"action": "..."} (wrapped as list).
/// Caps list length at [maxAllowed] if provided.
List<Map<String, dynamic>>? _extractActionList(
    Map<String, dynamic> input, {int? maxAllowed}) {
  List<dynamic>? raw;
  if (input.containsKey('actions')) {
    raw = input['actions'] as List<dynamic>?;
  } else if (input.containsKey('action')) {
    raw = [input]; // backward-compat: single action wrapped in list
  }
  if (raw == null || raw.isEmpty) return null;

  var actions = raw.whereType<Map<String, dynamic>>().toList();
  if (maxAllowed != null && actions.length > maxAllowed) {
    actions = actions.sublist(0, maxAllowed);
  }
  return actions.isEmpty ? null : actions;
}

// ── Utilities ──────────────────────────────────────────────────────────────────

Map<String, dynamic> _readJson(String path) =>
    jsonDecode(File(path).readAsStringSync()) as Map<String, dynamic>;

String _defaultPacksDir() {
  final exe = File(Platform.script.toFilePath());
  return '${exe.parent.parent.parent.parent.path}/packs';
}

void _die(String msg) {
  stderr.writeln('FATAL: $msg');
  exitCode = 1;
}
