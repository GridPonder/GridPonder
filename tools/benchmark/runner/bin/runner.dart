// Game-loop runner for AI benchmarking.
//
// Communicates via newline-delimited JSON on stdin/stdout:
//   stdout → Python: state / reset / rejected / won / lost events
//   stdin  ← Python: {"action": "...", ...params, "memory": "..."}
//
// give_up counts as 1 action toward the total action budget;
// auto-reset triggers when actionCount >= action_limit_per_attempt.

import 'dart:convert';
import 'dart:io';

import 'package:args/args.dart';
import 'package:gridponder_engine/engine.dart';

Future<void> main(List<String> arguments) async {
  final parser = ArgParser()
    ..addOption('pack', abbr: 'p', help: 'Pack ID', mandatory: true)
    ..addOption('level', abbr: 'l', help: 'Level ID', mandatory: true)
    ..addOption('packs-dir',
        help: 'Absolute path to the packs/ directory',
        defaultsTo: null)
    ..addOption('attempt-multiplier',
        help: 'action_limit_per_attempt = M × gold_path_length',
        defaultsTo: '3')
    ..addOption('total-multiplier',
        help:
            'action_limit = M × gold_path_length  (give_up counts as 1 action)',
        defaultsTo: '5');

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
  final packsDir =
      args['packs-dir'] as String? ?? _defaultPacksDir();
  final attemptMul = int.parse(args['attempt-multiplier'] as String);
  final totalMul = int.parse(args['total-multiplier'] as String);

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

  // Limits: fall back to sensible absolute values when gold path is absent.
  final limitPerAttempt = goldPathLen > 0
      ? attemptMul * goldPathLen
      : (attemptMul * 10).clamp(10, 60);
  final limitTotal = goldPathLen > 0
      ? totalMul * goldPathLen
      : (totalMul * 10).clamp(10, 100);

  // ── Game state ────────────────────────────────────────────────────────────
  final engine = TurnEngine(gameDef, levelDef);
  int attemptNumber = 1;
  int totalGameActions = 0; // real game actions (not give_ups)
  int giveUpCount = 0; // each voluntary give_up costs 1 toward total
  String memory = '';

  // For the before/after board comparison in the prompt:
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
    out({
      'event': 'state',
      'prompt': LlmAgent.buildPrompt(obs, memory: memory),
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

    // Memory update is applied regardless of action type.
    final memUpdate = input['memory'] as String?;
    if (memUpdate != null) memory = memUpdate;

    final actionId = input['action'] as String?;
    if (actionId == null) {
      stderr.writeln('Missing "action" field: $trimmed');
      continue;
    }

    // ── give_up ─────────────────────────────────────────────────────────────
    if (actionId == 'give_up') {
      giveUpCount++; // give_up costs 1 action toward total budget
      final totalNow = totalGameActions + giveUpCount;
      doReset(reason: 'voluntary');
      if (totalNow >= limitTotal) {
        out({
          'event': 'lost',
          'actions_this_attempt': engine.state.actionCount,
          'actions_total': totalNow,
          'attempts': attemptNumber,
          'gold_path_length': goldPathLen,
        });
        break;
      }
      emitState();
      continue;
    }

    // ── Game action ──────────────────────────────────────────────────────────
    // Capture board state before executing (used in the *next* state event).
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
      // Invalid action — restore context and re-emit state unchanged.
      prevBoardText = null;
      prevInventory = null;
      out({'event': 'rejected', 'action': input});
      emitState();
      continue;
    }

    lastAction = gameAction;
    totalGameActions++;
    final totalNow = totalGameActions + giveUpCount;

    if (engine.isWon) {
      out({
        'event': 'won',
        'actions_this_attempt': engine.state.actionCount,
        'actions_total': totalNow,
        'attempts': attemptNumber,
        'gold_path_length': goldPathLen,
      });
      break;
    }

    if (engine.isLost) {
      out({
        'event': 'lost',
        'actions_this_attempt': engine.state.actionCount,
        'actions_total': totalNow,
        'attempts': attemptNumber,
        'gold_path_length': goldPathLen,
      });
      break;
    }

    // Auto-reset: per-attempt action limit reached.
    if (engine.state.actionCount >= limitPerAttempt) {
      doReset(reason: 'limit');
    }

    // Total action budget exhausted.
    if (totalNow >= limitTotal) {
      out({
        'event': 'lost',
        'actions_this_attempt': engine.state.actionCount,
        'actions_total': totalNow,
        'attempts': attemptNumber,
        'gold_path_length': goldPathLen,
      });
      break;
    }

    emitState();
  }
}

// ── Utilities ──────────────────────────────────────────────────────────────

Map<String, dynamic> _readJson(String path) =>
    jsonDecode(File(path).readAsStringSync()) as Map<String, dynamic>;

/// Default packs/ directory: four levels up from the compiled binary location.
/// Binary is compiled to tools/benchmark/runner/runner, so:
///   runner → runner/ → benchmark/ → tools/ → project-root → packs/
String _defaultPacksDir() {
  final exe = File(Platform.script.toFilePath());
  return '${exe.parent.parent.parent.parent.path}/packs';
}

void _die(String msg) {
  stderr.writeln('FATAL: $msg');
  exitCode = 1;
}
