// Game-loop runner for AI benchmarking.
//
// Dart twin of tools/benchmark/runner.py (the reference implementation): same
// flags, same newline-delimited JSON protocol, same prompts.
//
//   stdout → orchestrator: state / reset / rejected / won / lost events
//   stdin  ← orchestrator:
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
// the attempt ends when actionCount >= action_limit_per_attempt
// (not applicable in full mode).
//
// Not ported from runner.py: `--input image` / `text+image` (the sprite
// renderer is Python-only); only text input is supported here.

import 'dart:convert';
import 'dart:io';

import 'package:args/args.dart';
import 'package:gridponder_engine/engine.dart';
import 'package:gridponder_engine/src/agent/py_format.dart';

// Two guards, because the two rejection kinds mean opposite things: five
// unparseable payloads in a row says the agent cannot express itself; illegal
// moves are ordinary probing (see runner.py).
const _maxConsecutiveSchema = 5;
const _maxConsecutiveIllegal = 25;

// Short reasons for losses the runner itself decides (the engine's own losses
// are described from the level's lose conditions by LlmAgent.describeLoss).
const _reasonHarnessCap = 'harness action cap reached';
const _reasonTotalBudget = 'total action budget exhausted';
const _reasonSchema = 'too many consecutive unparseable actions';
const _reasonIllegal = 'too many consecutive rejected actions';
const _reasonGiveUp = 'given up';
const _reasonPlanEnded = 'plan ended without solving the level';

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
    ..addOption('max-attempts',
        help: 'Attempts before the run ends. Above 1 a lost attempt resets '
            'the board and costs one attempt instead of ending the run.',
        defaultsTo: '1')
    ..addFlag('full-attempts',
        help: "Give every attempt the level's own action budget (its "
            'max_actions lose condition), and make the total their sum.',
        defaultsTo: false)
    ..addOption('mode',
        help: 'Inference mode',
        allowed: ['single', 'fixed-n', 'full', 'flex-n'],
        defaultsTo: 'single')
    ..addOption('step-size',
        help: 'Max actions per LLM call (fixed-n mode)', defaultsTo: '1')
    ..addOption('max-n',
        help: 'Max actions per LLM call (flex-n mode, default: unlimited)',
        defaultsTo: null)
    ..addFlag('anon',
        help: 'Anonymise entity kinds and action IDs in the prompt',
        defaultsTo: false)
    ..addOption('observation',
        help: "Observation payload: 'full' (prompt + valid_actions) or "
            "'harness' (board-only, no legal-move list)",
        allowed: ['full', 'harness'],
        defaultsTo: 'full')
    ..addOption('input',
        help: 'What the model sees. Only text is supported by this runner.',
        allowed: ['text', 'image', 'text+image'],
        defaultsTo: 'text');

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
  final maxAttemptsArg = int.parse(args['max-attempts'] as String);
  final maxAttempts = maxAttemptsArg < 1 ? 1 : maxAttemptsArg;
  final fullAttempts = args['full-attempts'] as bool;
  final mode = args['mode'] as String;
  final stepSize = int.parse(args['step-size'] as String);
  final maxNStr = args['max-n'] as String?;
  final maxN = maxNStr != null ? int.parse(maxNStr) : null;
  final anon = args['anon'] as bool;
  final observationMode = args['observation'] as String;
  var inputMode = args['input'] as String;
  // Anon mode would defeat itself with a sprite-rendered board: force text.
  if (anon) inputMode = 'text';
  if (inputMode != 'text') {
    _die('--input $inputMode is only supported by the Python runner.');
    return;
  }

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
  for (final entry
      in ((gameJson['levelSequence'] as List?)?.cast<Map<String, dynamic>>() ??
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

  // Anon mode: kind→label map (stable for the whole run).
  final Map<String, String>? kindSymbolOverrides =
      anon ? buildAnonKindToLabel(gameDef) : null;

  var limitPerAttempt = goldPathLen > 0
      ? attemptMul * goldPathLen
      : (attemptMul * 10).clamp(10, 60);
  var limitTotal =
      goldPathLen > 0 ? totalMul * goldPathLen : (totalMul * 10).clamp(10, 100);
  if (fullAttempts) {
    limitPerAttempt = _levelActionCap(levelDef) ?? limitPerAttempt;
    limitTotal = limitPerAttempt * maxAttempts;
  }

  // ── Game state ────────────────────────────────────────────────────────────
  final engine = TurnEngine(gameDef, levelDef);
  int attemptNumber = 1;
  int totalGameActions = 0;
  int giveUpCount = 0;
  int losses = 0;
  String memory = '';
  int consecutiveSchema = 0;
  int consecutiveIllegal = 0;
  int rejectedSchema = 0;
  int rejectedIllegal = 0;

  // Harness runs anonymise the action *schema* once, up front.
  final harnessAnon = anon && observationMode == 'harness';
  final anonActionTable =
      harnessAnon ? _buildAnonActionTable(gameDef) : <String, _AnonAction>{};

  // Repeated-state tracking, scoped per attempt.
  var seenStates = <String>{AgentObservation.stateKey(engine.state, gameDef)};
  int repeatedStateCount = 0;

  GameAction? lastAction;
  String? prevBoardText;
  String? prevInventory;
  String? prevStatus;
  // Anon mode: label (a1, a2, …) → real action, rebuilt on every emitState().
  Map<String, GameAction> currentAnonMap = {};
  // How the previous attempt ended, shown once on the next attempt's first
  // prompt; and the most recent submission when it was rejected.
  String? previousAttempt;
  (Map<String, dynamic>, String)? lastRejected;

  // ── Helpers ───────────────────────────────────────────────────────────────
  void out(Map<String, dynamic> event) => stdout.writeln(jsonEncode(event));

  String? currentInventory() =>
      engine.state.avatar.enabled ? engine.state.avatar.inventory.slot : null;

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
      previousStatus: prevStatus,
      kindSymbolOverrides: kindSymbolOverrides,
      // Probe candidates on the live engine so only effectful actions are
      // offered, exactly as the Python runner does.
      engine: engine,
    );

    if (anon) currentAnonMap = buildAnonReverseMap(obs.validActions);

    if (observationMode == 'harness') {
      var inv = currentInventory();
      // The inventory holds a kind id; an anonymous run sees its alias.
      if (inv != null && kindSymbolOverrides != null) {
        inv = kindSymbolOverrides[inv] ?? inv;
      }
      out({
        'event': 'state',
        'board_text': obs.boardText,
        'goals': LlmAgent.describeGoals(levelDef, engine.state, gameDef,
            anonymize: anon, kindToLabel: kindSymbolOverrides ?? const {}),
        'inventory': inv ?? '',
        'moves_this_attempt': engine.state.actionCount,
        'actions_total': totalNow,
        'attempt': attemptNumber,
        'level_id': levelId,
        'pack_id': packId,
      });
      return;
    }

    final prompt = LlmAgent.buildPrompt(
      obs,
      memory: memory,
      inferenceMode: mode,
      stepSize: stepSize,
      maxN: maxN,
      anonymize: anon,
      previousAttempt: previousAttempt,
      rejectedAction: lastRejected?.$1,
      rejectionDetail: lastRejected?.$2,
    );
    previousAttempt = null;

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
      'input_mode': inputMode,
      if (mode == 'fixed-n') 'step_size': stepSize,
      if (mode == 'flex-n') 'max_n': maxN,
    });
  }

  void doReset({required String reason, String? lossReason}) {
    engine.reset();
    attemptNumber++;
    lastAction = null;
    lastRejected = null;
    if (reason == 'lost') {
      previousAttempt = 'lost — $lossReason';
    } else if (reason == 'limit') {
      previousAttempt = 'ended — $_reasonHarnessCap';
    } else {
      previousAttempt = _reasonGiveUp;
    }
    prevBoardText = null;
    prevInventory = null;
    prevStatus = null;
    seenStates = {AgentObservation.stateKey(engine.state, gameDef)};
    out({
      'event': 'reset',
      'attempt': attemptNumber,
      'reason': reason,
      'actions_total': totalGameActions + giveUpCount,
    });
  }

  void recordState() {
    final key = AgentObservation.stateKey(engine.state, gameDef);
    if (!seenStates.add(key)) repeatedStateCount++;
  }

  Map<String, dynamic> terminal(String event) => {
        'event': event,
        'actions_this_attempt': engine.state.actionCount,
        'actions_total': totalGameActions + giveUpCount,
        'attempts': attemptNumber,
        'losses': losses,
        'gold_path_length': goldPathLen,
        'repeated_states': repeatedStateCount,
        'rejected_schema': rejectedSchema,
        'rejected_illegal': rejectedIllegal,
      };

  Map<String, dynamic> wonEvent() => terminal('won');
  Map<String, dynamic> lostEvent(String lossReason) =>
      {...terminal('lost'), 'loss_reason': lossReason};

  String engineLossReason(TurnResult result) =>
      LlmAgent.describeLoss(levelDef, result.loseReason, anonymize: anon);

  /// Close the current attempt. True when that ends the whole run.
  bool endAttempt(String reason, [String? lossReason]) {
    if (reason == 'lost') losses++;
    if (attemptNumber >= maxAttempts) return true;
    doReset(reason: reason, lossReason: lossReason);
    return false;
  }

  /// Emit one rejection under its counter. [reason] is schema|illegal;
  /// [promptDetail] is what the next prompt says about it.
  void reject(Map<String, dynamic> actionInput, String reason, String detail,
      [String? promptDetail]) {
    lastRejected = (
      Map<String, dynamic>.from(actionInput)..remove('memory'),
      promptDetail ?? detail,
    );
    if (reason == 'schema') {
      rejectedSchema++;
      consecutiveSchema++;
    } else {
      rejectedIllegal++;
      consecutiveIllegal++;
    }
    prevBoardText = null;
    prevInventory = null;
    prevStatus = null;
    out({
      'event': 'rejected',
      'action': actionInput,
      'reason': reason,
      'detail': detail,
    });
  }

  /// (event detail, prompt detail) for an engine rejection. An engine reason
  /// carried on `action_vetoed` wins over the generic text. The reason names
  /// kinds, so an anonymous run keeps the generic text (the harness shows the
  /// event detail to the agent too).
  (String, String) illegalDetails(GameAction real, TurnResult result) {
    for (final e in result.events) {
      final r = e.payload['reason'];
      if (!anon && e.type == 'action_vetoed' && r is String && r.isNotEmpty) {
        return (r, r);
      }
    }
    final detail = '${real.actionId} is not legal in this state';
    return (detail, anon ? 'not legal in this state' : detail);
  }

  /// Turn one submitted action into (real action, schema error).
  (GameAction?, String?) resolve(Map<String, dynamic> actionInput) {
    final submittedId = actionInput['action'];
    if (submittedId is! String) {
      return (null, '"action" must be a string, got ${pyRepr(submittedId)}');
    }
    final GameAction real;
    if (harnessAnon) {
      final resolved = _resolveAnonAction(anonActionTable, actionInput);
      if (resolved == null) {
        return (
          null,
          'unknown anonymous action or parameter: ${pyRepr(actionInput)}'
        );
      }
      real = resolved;
    } else if (anon) {
      final mapped = currentAnonMap[submittedId];
      if (mapped == null) {
        return (null, 'unknown action label ${pyRepr(submittedId)}');
      }
      real = mapped;
    } else {
      final params = Map<String, dynamic>.from(actionInput)
        ..remove('action')
        ..remove('memory');
      real = GameAction(submittedId, params);
    }
    final err = _validateParams(gameDef, real.actionId, real.params);
    if (err != null) return (null, err);
    return (real, null);
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

    final memUpdate = input['memory'];
    if (memUpdate is String) memory = memUpdate;

    // ── single mode ─────────────────────────────────────────────────────────
    if (mode == 'single') {
      final actionId = input['action'];
      if (actionId == null) {
        stderr.writeln('Missing "action" field: $trimmed');
        continue;
      }

      if (actionId == 'give_up') {
        consecutiveSchema = consecutiveIllegal = 0;
        giveUpCount++;
        final totalNow = totalGameActions + giveUpCount;
        doReset(reason: 'voluntary');
        if (totalNow >= limitTotal) {
          out(lostEvent(_reasonTotalBudget));
          break;
        }
        emitState();
        continue;
      }

      prevBoardText = TextRenderer.render(engine.state, gameDef,
          includeLegend: false, kindSymbolOverrides: kindSymbolOverrides);
      prevInventory = currentInventory();
      prevStatus = LlmAgent.statusFingerprint(gameDef, levelDef, engine.state);

      final (real, schemaError) =
          resolve(Map<String, dynamic>.from(input)..remove('memory'));
      if (schemaError != null) {
        reject(input, 'schema', schemaError);
        if (consecutiveSchema >= _maxConsecutiveSchema) {
          out(lostEvent(_reasonSchema));
          break;
        }
        emitState();
        continue;
      }

      final result = engine.executeTurn(real!);

      if (!result.accepted) {
        final (detail, promptDetail) = illegalDetails(real, result);
        reject(input, 'illegal', detail, promptDetail);
        if (consecutiveIllegal >= _maxConsecutiveIllegal) {
          out(lostEvent(_reasonIllegal));
          break;
        }
        emitState();
        continue;
      }

      consecutiveSchema = consecutiveIllegal = 0;
      lastAction = real;
      lastRejected = null;
      totalGameActions++;
      final totalNow = totalGameActions + giveUpCount;
      recordState();

      if (engine.isWon) {
        out(wonEvent());
        break;
      }
      if (engine.isLost) {
        final lossReason = engineLossReason(result);
        if (endAttempt('lost', lossReason)) {
          out(lostEvent(lossReason));
          break;
        }
      } else if (engine.state.actionCount >= limitPerAttempt) {
        if (endAttempt('limit')) {
          out(lostEvent(_reasonHarnessCap));
          break;
        }
      }
      if (totalNow >= limitTotal) {
        out(lostEvent(_reasonTotalBudget));
        break;
      }
      emitState();
      continue;
    }

    // ── multi-action modes: fixed-n, flex-n, full ───────────────────────────
    final actions = _extractActionList(input,
        maxAllowed: mode == 'fixed-n'
            ? stepSize
            : mode == 'flex-n'
                ? maxN
                : null);

    if (actions.isEmpty) {
      stderr.writeln('No valid actions found in input: $trimmed');
      continue;
    }

    bool outerBreak = false;

    for (final actionInput in actions) {
      final actionId = actionInput['action'];
      if (actionId == null) continue;

      if (actionId == 'give_up') {
        consecutiveSchema = consecutiveIllegal = 0;
        if (mode == 'full') {
          out(lostEvent(_reasonGiveUp));
          outerBreak = true;
        } else {
          giveUpCount++;
          final totalNow = totalGameActions + giveUpCount;
          doReset(reason: 'voluntary');
          if (totalNow >= limitTotal) {
            out(lostEvent(_reasonTotalBudget));
            outerBreak = true;
          }
        }
        break;
      }

      prevBoardText = TextRenderer.render(engine.state, gameDef,
          includeLegend: false, kindSymbolOverrides: kindSymbolOverrides);
      prevInventory = currentInventory();
      prevStatus = LlmAgent.statusFingerprint(gameDef, levelDef, engine.state);

      final (real, schemaError) =
          resolve(Map<String, dynamic>.from(actionInput)..remove('memory'));
      if (schemaError != null) {
        reject(actionInput, 'schema', schemaError);
        if (consecutiveSchema >= _maxConsecutiveSchema) {
          out(lostEvent(_reasonSchema));
          outerBreak = true;
        }
        break;
      }

      final result = engine.executeTurn(real!);

      if (!result.accepted) {
        final (detail, promptDetail) = illegalDetails(real, result);
        reject(actionInput, 'illegal', detail, promptDetail);
        if (consecutiveIllegal >= _maxConsecutiveIllegal) {
          out(lostEvent(_reasonIllegal));
          outerBreak = true;
        }
        break;
      }

      consecutiveSchema = consecutiveIllegal = 0;
      lastAction = real;
      lastRejected = null;
      totalGameActions++;
      final totalNow = totalGameActions + giveUpCount;
      recordState();

      if (engine.isWon) {
        out(wonEvent());
        outerBreak = true;
        break;
      }
      if (engine.isLost) {
        final lossReason = engineLossReason(result);
        if (endAttempt('lost', lossReason)) {
          out(lostEvent(lossReason));
          outerBreak = true;
          break;
        }
        if (totalNow >= limitTotal) {
          out(lostEvent(_reasonTotalBudget));
          outerBreak = true;
        }
        break;
      }

      if (mode != 'full' && engine.state.actionCount >= limitPerAttempt) {
        if (endAttempt('limit')) {
          out(lostEvent(_reasonHarnessCap));
          outerBreak = true;
          break;
        }
        if (totalNow >= limitTotal) {
          out(lostEvent(_reasonTotalBudget));
          outerBreak = true;
        }
        break;
      }

      if (totalNow >= limitTotal) {
        out(lostEvent(_reasonTotalBudget));
        outerBreak = true;
        break;
      }
    }

    if (outerBreak) break;

    if (mode == 'full') {
      out(lostEvent(_reasonPlanEnded));
      break;
    }

    emitState();
  }
}

// ── Validation ──────────────────────────────────────────────────────────────

/// Check one action's params against game.json. Returns an error, or null.
/// Mirrors `_validate_params` in runner.py.
String? _validateParams(
    GameDefinition game, String actionId, Map<String, dynamic> params) {
  ActionDef? spec;
  for (final a in game.actions) {
    if (a.id == actionId) {
      spec = a;
      break;
    }
  }
  if (spec == null) return 'unknown action ${pyRepr(actionId)}';
  final declared = spec.params;

  for (final name in params.keys) {
    if (!declared.containsKey(name)) {
      return '$actionId takes no parameter ${pyRepr(name)}';
    }
  }
  for (final entry in declared.entries) {
    final name = entry.key;
    if (!params.containsKey(name)) {
      return '$actionId requires parameter ${pyRepr(name)}';
    }
    final value = params[name];
    final values = entry.value.values;
    final ptype = entry.value.type;
    if (values != null && values.isNotEmpty) {
      if (!values.contains(value)) {
        return '${pyRepr(name)} must be one of ${pyRepr(values)}, got ${pyRepr(value)}';
      }
    } else if (ptype == 'position') {
      if (value is! List ||
          value.length != 2 ||
          !value.every((c) => c is int)) {
        return '${pyRepr(name)} must be an [x, y] pair of integers, got ${pyRepr(value)}';
      }
    } else if (ptype == 'integer') {
      if (value is! int) {
        return '${pyRepr(name)} must be an integer, got ${pyRepr(value)}';
      }
    } else if (ptype == 'string') {
      if (value is! String) {
        return '${pyRepr(name)} must be a string, got ${pyRepr(value)}';
      }
    }
  }
  return null;
}

/// The action budget the level itself declares (its first positive integer
/// `max_actions` limit), if any.
int? _levelActionCap(LevelDefinition level) {
  for (final c in level.loseConditions) {
    if (c.type != 'max_actions') continue;
    final limit = c.config['limit'];
    if (limit is int && limit > 0) return limit;
  }
  return null;
}

// ── Harness-mode anonymous action schema ────────────────────────────────────

class _AnonParam {
  final String name;
  final Map<String, dynamic>? values; // alias → real value, null = free
  _AnonParam(this.name, this.values);
}

class _AnonAction {
  final String action;
  final Map<String, _AnonParam> params; // param alias → param
  _AnonAction(this.action, this.params);
}

/// Mirror of `build_anon_action_shapes` (table half) in engines/python/anon.py:
/// actions, params and enumerated values aliased a1../p1../v1.. in
/// alphabetical order.
Map<String, _AnonAction> _buildAnonActionTable(GameDefinition game) {
  final table = <String, _AnonAction>{};
  final actions = List<ActionDef>.from(game.actions)
    ..sort((a, b) => a.id.compareTo(b.id));
  for (int a = 0; a < actions.length; a++) {
    final action = actions[a];
    final names = action.params.keys.toList()..sort();
    final params = <String, _AnonParam>{};
    for (int p = 0; p < names.length; p++) {
      final values = action.params[names[p]]!.values;
      Map<String, dynamic>? aliases;
      if (values != null && values.isNotEmpty) {
        final sorted = List<String>.from(values)..sort();
        aliases = {
          for (int v = 0; v < sorted.length; v++) 'v${v + 1}': sorted[v],
        };
      }
      params['p${p + 1}'] = _AnonParam(names[p], aliases);
    }
    table['a${a + 1}'] = _AnonAction(action.id, params);
  }
  return table;
}

/// Mirror of `resolve_anon_action`: null on any unknown alias.
GameAction? _resolveAnonAction(
    Map<String, _AnonAction> table, Map<String, dynamic> submitted) {
  final entry = table[submitted['action']];
  if (entry == null) return null;
  final params = <String, dynamic>{};
  for (final e in submitted.entries) {
    if (e.key == 'action') continue;
    final param = entry.params[e.key];
    if (param == null) return null;
    if (param.values != null) {
      if (!param.values!.containsKey(e.value)) return null;
      params[param.name] = param.values![e.value];
    } else {
      params[param.name] = e.value;
    }
  }
  return GameAction(entry.action, params);
}

// ── Input parsing ─────────────────────────────────────────────────────────────

/// Parses the actions list from multi-action mode input.
/// Accepts both {"actions": [...]} and single {"action": "..."} (wrapped as list).
/// Caps list length at [maxAllowed] if provided.
List<Map<String, dynamic>> _extractActionList(Map<String, dynamic> input,
    {int? maxAllowed}) {
  List<dynamic>? raw;
  if (input.containsKey('actions')) {
    final a = input['actions'];
    raw = a is List ? a : null;
  } else if (input.containsKey('action')) {
    raw = [input];
  }
  if (raw == null || raw.isEmpty) return [];
  var actions = [
    for (final a in raw)
      if (a is Map<String, dynamic> && a.containsKey('action')) a,
  ];
  if (maxAllowed != null && actions.length > maxAllowed) {
    actions = actions.sublist(0, maxAllowed);
  }
  return actions;
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
