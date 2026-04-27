import 'dart:async';
import 'package:flutter/foundation.dart' show kDebugMode, kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:gridponder_engine/engine.dart';
import 'package:llm_dart/llm_dart.dart';
import '../services/hint_service.dart';
import '../services/pack_service.dart';
import '../services/progress_service.dart';
import '../services/settings_service.dart';
import '../widgets/board_renderer.dart' show BoardRenderer, TargetBoardRenderer, cellNamedColor;
import '../widgets/controls_widget.dart';

class PlayScreen extends StatefulWidget {
  final PackService packService;
  final SettingsService settings;
  final ProgressService? progress;
  final String? startLevelId;

  const PlayScreen({
    super.key,
    required this.packService,
    required this.settings,
    this.progress,
    this.startLevelId,
  });

  @override
  State<PlayScreen> createState() => _PlayScreenState();
}

class _PlayScreenState extends State<PlayScreen> {
  late List<SequenceEntry> _sequence;
  late int _seqIndex;
  late List<String> _levelIds;
  late LevelDefinition _levelDef;
  late TurnEngine _engine;
  late HintService _hintService;

  SequenceEntry get _currentEntry => _sequence[_seqIndex];
  bool get _isShowingStory => _currentEntry.type == 'story';

  /// 0-based index of the current level among all levels (for status bar).
  int get _levelIndex {
    int count = 0;
    for (int i = 0; i < _seqIndex; i++) {
      if (_sequence[i].type == 'level') count++;
    }
    return count;
  }

  // Swipe detection (covers full screen)
  Offset? _panStart;
  static const double _swipeThreshold = 18.0;

  // Periodic timer to refresh hint dot availability
  Timer? _hintRefreshTimer;

  // Animation state: non-null while an entity animation is playing.
  LevelState? _preAnimState;
  Map<Position, String>? _animOverlays;
  bool _animating = false;
  // Non-null during ice slide: overrides the avatar's rendered position.
  Position? _avatarSlidePos;

  // Flood Colors: color of the last successfully applied flood action.
  Color? _lastFloodColor;

  // True once the current level's win has been recorded to ProgressService.
  bool _wonHandled = false;

  // AI play state
  bool _aiRunning = false;
  String? _lastThinking;
  String? _lastResponse;
  int _agentAttempt = 1;
  StreamSubscription<AgentStepEvent>? _agentSub;
  GridPonderAgent? _currentAgent;

  /// Persistent memory per level ID — survives stop/start, cleared on level change.
  final Map<String, String> _agentMemory = {};

  @override
  void initState() {
    super.initState();
    _sequence = widget.packService.sequence;
    _levelIds = widget.packService.levelIds;
    final startId = widget.startLevelId;
    if (startId != null) {
      // For integration tests: jump directly to the requested level.
      final idx = _sequence.indexWhere(
          (e) => e.type == 'level' && e.ref == startId);
      _seqIndex = idx >= 0 ? idx : 0;
    } else {
      _seqIndex = 0; // may start on a story entry
    }
    if (!_isShowingStory) _loadLevelById(_currentEntry.ref!);

    // Refresh hint dots every 10 s so they light up promptly when time elapses
    _hintRefreshTimer = Timer.periodic(const Duration(seconds: 5), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _hintRefreshTimer?.cancel();
    _agentSub?.cancel();
    super.dispose();
  }

  SettingsService get s => widget.settings;

  void _loadLevelById(String levelId) {
    _stopAgent();
    _levelDef = widget.packService.level(levelId);
    _engine = TurnEngine(widget.packService.game, _levelDef);
    _hintService = HintService(hintStops: _levelDef.solution.hintStops);
    _lastThinking = null;
    _lastResponse = null;
    _agentAttempt = 1;
    _agentMemory.clear();
    _lastFloodColor = null;
    _wonHandled = false;
  }

  Future<void> _onAction(GameAction action) async {
    if (_aiRunning || _animating) return;
    await _runAction(action);
  }

  /// Runs [action] through the engine and plays its full animation queue.
  /// Used by user input ([_onAction]) and replay paths ([_onSolve],
  /// [_playHint]) so all entry points show the same animations.
  Future<void> _runAction(GameAction action) async {
    final preState = _engine.state.copy();
    final result = _engine.executeTurn(action);
    if (!result.accepted) return;

    if (action.actionId.startsWith('flood_')) {
      final colorName = action.actionId.substring(6); // e.g. "red"
      _lastFloodColor = cellNamedColor(colorName);
    }

    final avatarMoves = result.animations
        .where((s) => s.type == 'avatar_move')
        .toList();
    final hasSlide = avatarMoves.length > 1;

    setState(() => _animating = true);

    // Avatar ice-slide: hold the pre-turn board so pushed objects stay at their
    // original positions while Pip slides. Skip last avatarMove — it's the
    // final position already shown by the engine state.
    if (hasSlide) {
      setState(() => _preAnimState = preState);
      for (int i = 0; i < avatarMoves.length - 1; i++) {
        if (!mounted) return;
        final toRaw = avatarMoves[i].extra['to'] as List;
        setState(() => _avatarSlidePos = Position(toRaw[0] as int, toRaw[1] as int));
        await Future.delayed(const Duration(milliseconds: 130));
      }
      // _avatarSlidePos now holds Pip's last ice cell. Do NOT clear it yet —
      // if a push follows, it keeps Pip visible at the correct position while
      // the object animates. Cleared after the object animation (or below if
      // no push follows).
    }

    // Animate objects that were pushed. Two cases:
    //   (a) Pip slid on ice and pushed an object at the end of her slide.
    //   (b) An object was pushed onto ice and slid on its own (2+ push events).
    final pushEvents = result.events
        .where((e) => e.type == 'object_pushed')
        .toList();
    if (pushEvents.isNotEmpty) {
      final pushByKind = <String, List<GameEvent>>{};
      for (final e in pushEvents) {
        final k = e.payload['kind'] as String?;
        if (k != null) pushByKind.putIfAbsent(k, () => []).add(e);
      }
      for (final entry in pushByKind.entries) {
        if (hasSlide || entry.value.length > 1) {
          await _playObjectSlide(preState, entry.key, entry.value);
        }
      }
    }

    // Clear slide overrides: _playObjectSlide already cleared _preAnimState and
    // _animOverlays, but _avatarSlidePos needs explicit cleanup here.
    if (hasSlide) {
      if (!mounted) return;
      setState(() {
        _preAnimState = null;    // no-op if _playObjectSlide already cleared it
        _avatarSlidePos = null;
      });
    }

    // Stage-aware playback for new motion primitives.
    // Group remaining animations by stage; play each stage to completion
    // before starting the next.
    final remaining = result.animations
        .where((s) => s.type == 'entity_move' || s.type == 'entity_animation')
        .toList()
      ..sort((a, b) => a.stage.compareTo(b.stage));

    int? currentStage;
    final stageBuf = <AnimationStep>[];
    Future<void> flushStage() async {
      if (stageBuf.isEmpty) return;
      final moves = stageBuf.where((s) => s.type == 'entity_move').toList();
      final anims = stageBuf.where((s) => s.type == 'entity_animation').toList();
      if (moves.isNotEmpty) {
        await _playSlideMotion(preState, moves);
      }
      for (final step in anims) {
        if (!mounted) return;
        await _playEntityAnimation(preState, step);
      }
      stageBuf.clear();
    }

    for (final step in remaining) {
      if (currentStage == null || step.stage == currentStage) {
        currentStage = step.stage;
        stageBuf.add(step);
      } else {
        await flushStage();
        if (!mounted) return;
        currentStage = step.stage;
        stageBuf.add(step);
      }
    }
    await flushStage();

    if (remaining.isNotEmpty) {
      if (!mounted) return;
      setState(() {
        _preAnimState = null;
        _animOverlays = null;
      });
    }

    if (!mounted) return;
    setState(() => _animating = false);
  }

  /// Animates a sliding object through its sequence of ice-slide positions.
  Future<void> _playObjectSlide(
    LevelState preState,
    String kind,
    List<GameEvent> pushEvents,
  ) async {
    final kindDef = widget.packService.game.entityKinds[kind];
    final sprite = kindDef?.sprite;
    if (sprite == null) return;
    final spritePath = sprite;

    // Build full position sequence: [from of first push, to of each push].
    Position posFromPayload(dynamic p) =>
        p is Position ? p : Position.fromJson(p);
    final positions = <Position>[];
    final firstFrom = pushEvents.first.payload['fromPosition'];
    if (firstFrom == null) return;
    positions.add(posFromPayload(firstFrom));
    for (final e in pushEvents) {
      final to = e.payload['toPosition'];
      if (to == null) return;
      positions.add(posFromPayload(to));
    }

    // Build animation board: remove object from its starting position so the
    // overlay is the only rendered copy of it throughout the animation.
    final animState = preState.copy();
    animState.board.setEntity('objects', positions.first, null);

    // Show object at each position in turn; skip the last because clearing
    // _preAnimState afterwards reveals the final engine state there.
    for (int i = 0; i < positions.length - 1; i++) {
      if (!mounted) return;
      setState(() {
        _preAnimState = animState;
        _animOverlays = {positions[i]: spritePath};
      });
      await Future.delayed(const Duration(milliseconds: 130));
    }
    if (!mounted) return;
    setState(() {
      _preAnimState = null;
      _animOverlays = null;
    });
  }

  /// Animates `entity_move` steps (tiles sliding across cells) in parallel.
  /// Each frame is a fresh board snapshot with the moving entities relocated
  /// to their current path position, so the existing cell renderer handles
  /// both sprite-backed and procedurally-drawn entities (e.g. number tiles).
  Future<void> _playSlideMotion(
    LevelState preState,
    List<AnimationStep> moves,
  ) async {
    if (moves.isEmpty) return;

    final paths = <List<Position>>[];
    final entities = <EntityInstance>[];
    final layers = <String>[];

    for (final step in moves) {
      final fromRaw = step.extra['from'];
      if (fromRaw is! List) continue;
      final from = Position(fromRaw[0] as int, fromRaw[1] as int);
      final to = step.position;

      // Cardinal-direction path; sign() handles non-cardinal degenerate cases.
      final dx = (to.x - from.x).sign;
      final dy = (to.y - from.y).sign;
      final path = <Position>[from];
      var p = from;
      while (p != to && path.length < 64) {
        p = Position(p.x + dx, p.y + dy);
        path.add(p);
      }

      final layer = step.extra['layer'] as String? ?? 'objects';
      final paramsRaw = step.extra['params'];
      final params = (paramsRaw is Map)
          ? paramsRaw.cast<String, dynamic>()
          : const <String, dynamic>{};
      final entity = EntityInstance(step.entityKind ?? '', params);

      paths.add(path);
      entities.add(entity);
      layers.add(layer);
    }

    if (paths.isEmpty) return;

    // Per-cell pacing — engine's `moveDurationMs` is per-cell, matching the
    // ice-slide convention. Falls back to 130ms when not provided.
    final frameMs = moves.first.durationMs > 0
        ? moves.first.durationMs.clamp(40, 400)
        : 130;

    final maxLen = paths.map((p) => p.length).reduce((a, b) => a > b ? a : b);
    // Iterate every path cell including the destination so single-cell moves
    // (pipe shifts, exit-to-spawn) are visible. The trailing post-loop snap
    // shows the same final state, so there is no visual discontinuity.
    for (int frame = 0; frame < maxLen; frame++) {
      if (!mounted) return;
      final animState = preState.copy();
      // Clear all source positions in the moving entity's layer.
      for (int i = 0; i < paths.length; i++) {
        animState.board.setEntity(layers[i], paths[i].first, null);
      }
      // Place each entity at its current frame position, but never overwrite
      // an existing entity (merge target sits at the path's end).
      for (int i = 0; i < paths.length; i++) {
        final path = paths[i];
        final pos = path[frame.clamp(0, path.length - 1)];
        if (animState.board.getEntity(layers[i], pos) == null) {
          animState.board.setEntity(layers[i], pos, entities[i]);
        }
      }
      setState(() {
        _preAnimState = animState;
        _animOverlays = null;
      });
      await Future.delayed(Duration(milliseconds: frameMs));
    }
  }

  Future<void> _playEntityAnimation(LevelState preState, AnimationStep step) async {
    final kindDef = widget.packService.game.entityKinds[step.entityKind];
    final animDef = kindDef?.animations[step.animationName!];
    if (animDef == null || animDef.frames.isEmpty) return;

    // For object-layer entities (wood, rock…), remove them from the board so
    // animation frames render cleanly without the original sprite bleeding through.
    // For ground-layer entities (ice…), keep the original tile visible beneath
    // the overlay frames — clearing ground would show void/black behind the anim.
    final cleanState = preState.copy();
    final layer = widget.packService.game.entityKinds[step.entityKind]?.layer ?? 'objects';
    if (layer == 'objects') {
      cleanState.board.setEntity('objects', step.position, null);
    }

    final frameMs = (animDef.durationMs / animDef.frames.length).round();
    for (final framePath in animDef.frames) {
      if (!mounted) return;
      setState(() {
        _preAnimState = cleanState;
        _animOverlays = {step.position: framePath};
      });
      await Future.delayed(Duration(milliseconds: frameMs));
    }
  }

  void _onUndo() {
    if (_aiRunning) return;
    setState(() {
      _engine.undo();
      _lastFloodColor = null;
    });
  }

  void _onReset() {
    _stopAgent();
    setState(() {
      _engine.reset();
      _lastThinking = null;
      _lastResponse = null;
      _lastFloodColor = null;
    });
  }

  /// Advance to the next sequence entry. If it's a level, load it.
  // ---------------------------------------------------------------------------
  // Progress / unlock helpers
  // ---------------------------------------------------------------------------

  /// Returns the next sequence entry that is a playable level, or null.
  SequenceEntry? get _nextLevelEntry {
    for (int i = _seqIndex + 1; i < _sequence.length; i++) {
      if (_sequence[i].type == 'level') return _sequence[i];
    }
    return null;
  }

  /// True when the next level in the sequence is locked.
  bool get _nextIsLocked {
    final progress = widget.progress;
    if (progress == null) return false;
    final next = _nextLevelEntry;
    if (next == null) return false;
    return !progress.isUnlocked(next.ref!, _sequence);
  }

  void _advance() {
    if (_seqIndex >= _sequence.length - 1) return; // already at end

    // Check lock: if the next *level* entry is locked, block navigation.
    final nextEntry = _sequence[_seqIndex + 1];
    if (nextEntry.type == 'level' && _nextIsLocked) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Complete this level to continue.'),
          behavior: SnackBarBehavior.floating,
          duration: Duration(seconds: 2),
        ),
      );
      return;
    }

    setState(() {
      _seqIndex++;
      if (!_isShowingStory) _loadLevelById(_currentEntry.ref!);
    });
  }

  /// Jump back one sequence entry (story or level).
  void _prevEntry() {
    setState(() {
      if (_seqIndex > 0) {
        _seqIndex--;
        if (!_isShowingStory) _loadLevelById(_currentEntry.ref!);
      }
    });
  }

  /// Jump back to the previous level (skipping story entries).
  void _prevLevel() {
    setState(() {
      var i = _seqIndex - 1;
      while (i >= 0 && _sequence[i].type != 'level') i--;
      if (i >= 0) {
        _seqIndex = i;
        _loadLevelById(_currentEntry.ref!);
      }
    });
  }

  void _onExit() => Navigator.pop(context);

  // ---------------------------------------------------------------------------
  // Swipe detection (full-screen)
  // ---------------------------------------------------------------------------

  bool get _hasDiagonalSwap =>
      widget.packService.game.actions.any((a) => a.id == 'diagonal_swap');
  bool get _hasMoveAction =>
      widget.packService.game.actions.any((a) => a.id == 'move');
  bool get _hasCellTapGesture =>
      widget.packService.theme?.controls?.gestureMap
          .any((b) => b.gesture == 'tap_cell') ??
      false;

  /// Action IDs whose colour is currently adjacent to the flood region.
  /// Only computed when the game has flood_<colour> actions.
  Set<String>? _availableFloodActions(LevelState state) {
    final hasFloodActions =
        widget.packService.game.actions.any((a) => a.id.startsWith('flood_'));
    if (!hasFloodActions) return null;

    final layer = state.board.layers['objects'];
    if (layer == null) return null;

    final available = <String>{};
    for (int y = 0; y < state.board.height; y++) {
      for (int x = 0; x < state.board.width; x++) {
        final entity = layer.getAt(Position(x, y));
        if (entity?.kind != 'cell_flooded') continue;
        for (final delta in [(-1, 0), (1, 0), (0, -1), (0, 1)]) {
          final nx = x + delta.$1, ny = y + delta.$2;
          if (nx < 0 || ny < 0 ||
              nx >= state.board.width || ny >= state.board.height) continue;
          final nb = layer.getAt(Position(nx, ny));
          final kind = nb?.kind;
          if (kind != null && kind.startsWith('cell_') &&
              kind != 'cell_flooded' && kind != 'cell_wall') {
            available.add('flood_${kind.substring(5)}');
          }
        }
      }
    }
    return available;
  }

  void _onCellTap(int x, int y) {
    final gestureMap =
        widget.packService.theme?.controls?.gestureMap ?? const [];
    for (final binding in gestureMap) {
      if (binding.gesture != 'tap_cell') continue;
      final params = <String, dynamic>{};
      binding.paramMapping?.forEach((key, value) {
        params[key] = value == 'tap_position' ? [x, y] : value;
      });
      if (binding.params != null) params.addAll(binding.params!);
      _onAction(GameAction(binding.action, params));
      break;
    }
  }

  void _onPanStart(DragStartDetails d) => _panStart = d.globalPosition;
  void _onPanCancel() => _panStart = null;
  void _onPanEnd(DragEndDetails _) => _panStart = null;

  void _onPanUpdate(DragUpdateDetails details) {
    if (_panStart == null) return;
    final delta = details.globalPosition - _panStart!;
    if (delta.distance < _swipeThreshold) return;

    final action = _detectSwipeAction(delta);
    if (action == null) return;

    _panStart = null;
    _onAction(action);
  }

  GameAction? _detectSwipeAction(Offset delta) {
    final ax = delta.dx.abs();
    final ay = delta.dy.abs();
    if (ax < _swipeThreshold && ay < _swipeThreshold) return null;

    if (_hasDiagonalSwap &&
        ax > _swipeThreshold * 0.5 &&
        ay > _swipeThreshold * 0.5) {
      final diagDir = _diagonalDir(delta);
      if (diagDir != null) {
        return GameAction('diagonal_swap', {'direction': diagDir});
      }
    }

    if (!_hasMoveAction) return null;
    final String dir;
    if (ax > ay) {
      dir = delta.dx > 0 ? 'right' : 'left';
    } else {
      dir = delta.dy > 0 ? 'down' : 'up';
    }
    return GameAction('move', {'direction': dir});
  }

  String? _diagonalDir(Offset delta) {
    final ax = delta.dx.abs();
    final ay = delta.dy.abs();
    if (ax < ay * 0.35 || ay < ax * 0.35) return null;
    if (delta.dx < 0 && delta.dy < 0) return 'up_left';
    if (delta.dx > 0 && delta.dy < 0) return 'up_right';
    if (delta.dx < 0 && delta.dy > 0) return 'down_left';
    return 'down_right';
  }

  // ---------------------------------------------------------------------------
  // Hint system
  // ---------------------------------------------------------------------------

  Future<void> _onHint() async {
    final idx = _hintService.nextIndex;
    if (idx < 0) return;

    // If not at the starting state, confirm before resetting
    if (_engine.undoDepth > 0) {
      final proceed = await _showHintConfirmation();
      if (!proceed) return;
    }

    await _playHint(idx);
  }

  Future<bool> _showHintConfirmation() async {
    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Row(
          children: [
            Icon(Icons.lightbulb_outline,
                color: Colors.amber.shade600, size: 26),
            const SizedBox(width: 10),
            const Text('Use Hint',
                style:
                    TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Hints replay the gold path from the start.',
              style: TextStyle(fontSize: 15, height: 1.4),
            ),
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: Colors.orange.shade50,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.orange.shade200),
              ),
              child: Row(
                children: [
                  Icon(Icons.refresh,
                      color: Colors.orange.shade700, size: 18),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: Text(
                      'The level will be reset to its starting state.',
                      style: TextStyle(
                          fontSize: 13, fontWeight: FontWeight.w500),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text('Cancel',
                style: TextStyle(color: Colors.grey.shade600)),
          ),
          ElevatedButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.amber.shade600,
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8)),
            ),
            child: const Text('Reset & Play Hint',
                style: TextStyle(fontWeight: FontWeight.w600)),
          ),
        ],
      ),
    );
    return result == true;
  }

  Future<void> _onSolve() async {
    final goldPath = _levelDef.solution.goldPath;
    if (goldPath.isEmpty) return;
    setState(() => _engine.reset());
    await Future.delayed(Duration.zero);
    for (int i = 0; i < goldPath.length; i++) {
      if (!mounted) return;
      await _runAction(goldPath[i]);
      await Future.delayed(const Duration(milliseconds: 300));
    }
  }

  Future<void> _playHint(int hintIndex) async {
    _hintService.markUsed(hintIndex);
    final stopCount = _levelDef.solution.hintStops[hintIndex];
    final goldPath = _levelDef.solution.goldPath;

    setState(() => _engine.reset());
    await Future.delayed(kDebugMode ? Duration.zero : const Duration(milliseconds: 200));

    for (int i = 0; i < stopCount && i < goldPath.length; i++) {
      if (!mounted) return;
      await _runAction(goldPath[i]);
      await Future.delayed(const Duration(milliseconds: 300));
    }
  }

  // ---------------------------------------------------------------------------
  // AI play
  // ---------------------------------------------------------------------------

  /// Base max-tokens for the chosen inference mode (without thinking budget).
  int get _baseModeTokens {
    switch (s.inferenceMode) {
      case 'fixed-n':
        return (512 * s.stepSizeN).clamp(1024, 8192);
      case 'flex-n':
      case 'full':
        return 4096;
      default: // single
        return 1024;
    }
  }

  Future<GridPonderAgent> _buildAgent() async {
    final inferenceMode = s.inferenceMode;
    final stepSizeN = s.stepSizeN;
    final maxN = s.maxN == 0 ? null : s.maxN;

    if (s.agentType == 'llm') {
      final key = s.apiKey;
      if (key == null || key.isEmpty) {
        throw Exception('No API key set. Add it in Settings.');
      }
      final useThinking =
          s.thinkingEnabled && AnthropicModel.supportsThinking(s.llmModel);
      final baseTokens = _baseModeTokens;
      var builder = ai()
          .anthropic()
          .apiKey(key)
          .model(s.llmModel)
          .maxTokens(baseTokens + (useThinking ? 8000 : 0));
      if (useThinking) {
        builder = builder.reasoning(true).thinkingBudgetTokens(8000);
      }
      final provider = await builder.build();
      final thinkLabel = useThinking ? ' + thinking' : '';
      return LlmAgent(
        provider: provider,
        displayName: '${AnthropicModel.displayName(s.llmModel)}$thinkLabel',
        initialMemory: _agentMemory[_currentEntry.ref] ?? '',
        inferenceMode: inferenceMode,
        stepSize: stepSizeN,
        maxN: maxN,
        anonymize: s.anonymize,
      );
    }
    if (s.agentType == 'openai') {
      final key = s.openAiApiKey;
      if (key == null || key.isEmpty) {
        throw Exception('No OpenAI API key set. Add it in Settings.');
      }
      final provider = await ai()
          .openai()
          .apiKey(key)
          .model(s.openAiModel)
          .maxTokens(_baseModeTokens)
          .build();
      return LlmAgent(
        provider: provider,
        displayName: OpenAIModel.displayName(s.openAiModel),
        initialMemory: _agentMemory[_currentEntry.ref] ?? '',
        inferenceMode: inferenceMode,
        stepSize: stepSizeN,
        maxN: maxN,
        anonymize: s.anonymize,
      );
    }
    if (s.agentType == 'google') {
      final key = s.googleApiKey;
      if (key == null || key.isEmpty) {
        throw Exception('No Google API key set. Add it in Settings.');
      }
      final useThinking = s.googleThinkingEnabled &&
          GoogleModel.supportsThinking(s.googleModel);
      final baseTokens = _baseModeTokens;
      var builder = ai()
          .google()
          .apiKey(key)
          .model(s.googleModel)
          .maxTokens(baseTokens + (useThinking ? 8000 : 0));
      if (useThinking) {
        builder = builder.reasoning(true).thinkingBudgetTokens(8000);
      }
      final provider = await builder.build();
      final thinkLabel = useThinking ? ' + thinking' : '';
      return LlmAgent(
        provider: provider,
        displayName: '${GoogleModel.displayName(s.googleModel)}$thinkLabel',
        initialMemory: _agentMemory[_currentEntry.ref] ?? '',
        inferenceMode: inferenceMode,
        stepSize: stepSizeN,
        maxN: maxN,
        anonymize: s.anonymize,
      );
    }
    if (s.agentType == 'ollama') {
      final useThink =
          s.ollamaThinkEnabled && OllamaModel.supportsThinking(s.ollamaModel);
      final provider = await ai()
          .ollama(OllamaModel.supportsThinking(s.ollamaModel)
              ? (o) => o.reasoning(useThink)
              : null)
          .baseUrl(s.ollamaBaseUrl)
          .model(s.ollamaModel)
          .maxTokens(useThink ? 32768 : _baseModeTokens)
          .build();
      final thinkLabel = useThink ? ' + think' : '';
      return LlmAgent(
        provider: provider,
        displayName: '${OllamaModel.displayName(s.ollamaModel)}$thinkLabel',
        initialMemory: _agentMemory[_currentEntry.ref] ?? '',
        inferenceMode: inferenceMode,
        stepSize: stepSizeN,
        maxN: maxN,
        anonymize: s.anonymize,
      );
    }
    return RandomAgent();
  }

  void _startAgent() async {
    GridPonderAgent agent;
    try {
      agent = await _buildAgent();
    } catch (e) {
      if (!mounted) return;
      _showTextDialog('Agent Error', e.toString());
      return;
    }

    _engine.reset();
    setState(() {
      _aiRunning = true;
      _lastThinking = null;
      _lastResponse = null;
      _agentAttempt = 1;
      _currentAgent = agent;
    });

    final runner = AgentRunner();
    final levelId = _currentEntry.ref!;
    final stream = runner.run(
      _engine,
      agent,
      stepDelay: Duration(milliseconds: s.stepDelayMs),
      autoResetMultiplier: s.autoResetMultiplier,
      anonymize: s.anonymize,
    );

    _agentSub = stream.listen(
      (event) {
        if (!mounted) return;
        if (event is AgentStepThinking) {
          setState(() => _lastThinking = (_lastThinking ?? '') + event.delta);
        } else if (event is AgentStepActed) {
          setState(() {
            _lastThinking = event.result.thinking;
            _lastResponse = event.result.responseText;
          });
          if (s.playbackMode == 'step' && event.isBatchEnd) _agentSub?.pause();
        } else if (event is AgentStepMemoryUpdated) {
          _agentMemory[levelId] = event.memory;
        } else if (event is AgentStepReset) {
          setState(() {
            _agentAttempt = event.attempt;
            _lastThinking = null;
            _lastResponse = null;
          });
        } else if (event is AgentRunFinished) {
          setState(() => _aiRunning = false);
        }
      },
      onError: (e) {
        if (!mounted) return;
        setState(() => _aiRunning = false);
        _showTextDialog('Agent Error', e.toString());
      },
      onDone: () {
        if (mounted) setState(() => _aiRunning = false);
      },
    );
  }

  void _stopAgent() {
    _agentSub?.cancel();
    _agentSub = null;
    if (mounted) setState(() => _aiRunning = false);
  }

  void _showTextDialog(String title, String? content) {
    final text = content?.isNotEmpty == true ? content! : '(empty)';
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Row(
          children: [
            Expanded(
              child: Text(title,
                  style: const TextStyle(
                      fontSize: 16, fontWeight: FontWeight.w600)),
            ),
            IconButton(
              icon: const Icon(Icons.copy, size: 18),
              tooltip: 'Copy',
              onPressed: () {
                Clipboard.setData(ClipboardData(text: text));
                ScaffoldMessenger.of(ctx).showSnackBar(
                  const SnackBar(
                      content: Text('Copied'),
                      duration: Duration(seconds: 1)),
                );
              },
            ),
          ],
        ),
        content: SizedBox(
          width: double.maxFinite,
          child: SingleChildScrollView(
            child: SelectableText(
              text,
              style: const TextStyle(
                  fontSize: 12, height: 1.5, fontFamily: 'monospace'),
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }

  void _showPrompt() {
    final agent = _currentAgent;
    String? prompt;
    if (agent is LlmAgent) {
      prompt = agent.lastPrompt;
    }
    _showTextDialog('Last Prompt', prompt ?? '(no prompt sent yet)');
  }

  void _showMemory() {
    final levelId = _currentEntry.ref;
    final agent = _currentAgent;
    // Live memory from the running agent takes priority (may differ from saved map).
    String? memory;
    if (agent is LlmAgent) {
      memory = agent.memory.isNotEmpty ? agent.memory : null;
    }
    memory ??= levelId != null ? _agentMemory[levelId] : null;
    _showTextDialog('Agent Memory', memory);
  }

  void _stepAgent() {
    if (_agentSub != null && _agentSub!.isPaused) {
      setState(() {
        _lastThinking = null;
        _lastResponse = null;
      });
      _agentSub!.resume();
    }
  }

  static LogicalKeyboardKey? _keyForChar(String char) {
    const map = {
      'a': LogicalKeyboardKey.keyA, 'b': LogicalKeyboardKey.keyB,
      'c': LogicalKeyboardKey.keyC, 'd': LogicalKeyboardKey.keyD,
      'e': LogicalKeyboardKey.keyE, 'f': LogicalKeyboardKey.keyF,
      'g': LogicalKeyboardKey.keyG, 'h': LogicalKeyboardKey.keyH,
      'i': LogicalKeyboardKey.keyI, 'j': LogicalKeyboardKey.keyJ,
      'k': LogicalKeyboardKey.keyK, 'l': LogicalKeyboardKey.keyL,
      'm': LogicalKeyboardKey.keyM, 'n': LogicalKeyboardKey.keyN,
      'o': LogicalKeyboardKey.keyO, 'p': LogicalKeyboardKey.keyP,
      'q': LogicalKeyboardKey.keyQ, 'r': LogicalKeyboardKey.keyR,
      's': LogicalKeyboardKey.keyS, 't': LogicalKeyboardKey.keyT,
      'u': LogicalKeyboardKey.keyU, 'v': LogicalKeyboardKey.keyV,
      'w': LogicalKeyboardKey.keyW, 'x': LogicalKeyboardKey.keyX,
      'y': LogicalKeyboardKey.keyY, 'z': LogicalKeyboardKey.keyZ,
    };
    return map[char.toLowerCase()];
  }

  // ---------------------------------------------------------------------------
  // Build
  // ---------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    if (_isShowingStory) return _buildStoryScaffold(_currentEntry);

    final state = _preAnimState ?? _engine.state;
    final levelId = _currentEntry.ref!;

    // Record win the first time it is detected (post-frame to avoid
    // calling async work inside a synchronous build call).
    if (state.isWon && !_wonHandled && widget.progress != null) {
      _wonHandled = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) widget.progress!.markCompleted(levelId);
      });
    }
    final hintStatuses = _hintService.statuses;
    final hintAvailable = _hintService.hasAnyAvailable && !_aiRunning;

    return Scaffold(
      backgroundColor: const Color(0xFFF5F0E8),
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Flexible(
              child: Text(
                _levelDef.title ?? levelId,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w600,
                    color: Colors.black87),
              ),
            ),
            const SizedBox(width: 4),
            IconButton(
              icon: const Icon(Icons.info_outline,
                  color: Colors.black45, size: 20),
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
              tooltip: 'How to play',
              onPressed: _showGameInfo,
            ),
          ],
        ),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios, color: Colors.black54),
          onPressed: _onExit,
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.navigate_before, color: Colors.black54),
            onPressed: _prevLevel,
          ),
          IconButton(
            icon: Icon(
              _nextIsLocked ? Icons.lock_outline : Icons.navigate_next,
              color: _nextIsLocked
                  ? Colors.black26
                  : Colors.black54,
            ),
            onPressed: _advance,
          ),
        ],
      ),
      body: Focus(
        autofocus: true,
        onKeyEvent: (_, event) {
          if (_aiRunning) return KeyEventResult.ignored;
          if (event is! KeyDownEvent) return KeyEventResult.ignored;
          if (event.logicalKey == LogicalKeyboardKey.keyZ ||
              event.logicalKey == LogicalKeyboardKey.keyU) {
            _onUndo();
            return KeyEventResult.handled;
          }
          final gestureMap =
              widget.packService.theme?.controls?.gestureMap ?? const [];
          for (final binding in gestureMap) {
            if (binding.gesture != 'key_press') continue;
            final mappedKey = _keyForChar(binding.key ?? '');
            if (mappedKey == null || event.logicalKey != mappedKey) continue;
            _onAction(GameAction(binding.action, binding.params ?? {}));
            return KeyEventResult.handled;
          }
          final String? dir = switch (event.logicalKey) {
            LogicalKeyboardKey.arrowUp => 'up',
            LogicalKeyboardKey.arrowDown => 'down',
            LogicalKeyboardKey.arrowLeft => 'left',
            LogicalKeyboardKey.arrowRight => 'right',
            _ => null,
          };
          if (dir == null || !_hasMoveAction) return KeyEventResult.ignored;
          _onAction(GameAction('move', {'direction': dir}));
          return KeyEventResult.handled;
        },
        child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onPanStart: _aiRunning ? null : _onPanStart,
        onPanUpdate: _aiRunning ? null : _onPanUpdate,
        onPanEnd: _aiRunning ? null : _onPanEnd,
        onPanCancel: _aiRunning ? null : _onPanCancel,
        child: SafeArea(
        child: Column(
          children: [
            _buildStatusBar(state),
            if (widget.packService.game.ui.showGoal ||
                widget.packService.game.ui.showGuide)
              _buildGoalGuidePanel(state),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Center(
                  child: BoardRenderer(
                    state: state,
                    game: widget.packService.game,
                    packService: widget.packService,
                    animationOverlays: _animOverlays,
                    onCellTap: _hasCellTapGesture ? _onCellTap : null,
                    floodedColorOverride: _lastFloodColor,
                    avatarPositionOverride: _avatarSlidePos,
                  ),
                ),
              ),
            ),
            if (state.isWon) _buildWinBanner(),
            if (state.isLost) _buildLossBanner(),
            if (s.aiPlayEnabled && !state.isWon && !state.isLost && _aiRunning) _buildAiPanel(),
            if (s.aiPlayEnabled && !state.isWon && !state.isLost && !_aiRunning) _buildAiStartButton(),
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: ControlsWidget(
                game: widget.packService.game,
                onAction: _onAction,
                onUndo: _onUndo,
                onReset: _onReset,
                onExit: _onExit,
                onHint: hintAvailable ? _onHint : null,
                onSolve: kDebugMode ? _onSolve : null,
                canUndo: _engine.undoDepth > 0 && !_aiRunning,
                hintStatuses: hintStatuses,
                availableActionIds: _availableFloodActions(state),
              ),
            ),
          ],
        ),
      ),
      ),
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // Goal / Guide panel
  // ---------------------------------------------------------------------------

  Widget _buildGoalGuidePanel(LevelState state) {
    final ui = widget.packService.game.ui;
    final showGoal = ui.showGoal && _levelDef.goals.isNotEmpty;
    final showGuide = ui.showGuide && (_levelDef.guide?.isNotEmpty ?? false);

    if (!showGoal && !showGuide) return const SizedBox.shrink();

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 2, 16, 4),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (showGoal) ...[
              Expanded(child: _buildGoalPanel(state)),
              if (showGuide) const SizedBox(width: 10),
            ],
            if (showGuide) Expanded(child: _buildGuidePanel()),
          ],
        ),
      ),
    );
  }

  Widget _buildGoalPanel(LevelState state) {
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: Colors.grey.shade300),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(children: [
            Icon(Icons.flag_outlined, color: Colors.green.shade600, size: 14),
            const SizedBox(width: 4),
            Text('Goal',
                style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    color: Colors.grey.shade700)),
          ]),
          const SizedBox(height: 6),
          _buildGoalContent(state),
        ],
      ),
    );
  }

  Widget _buildGoalContent(LevelState state) {
    // Sum and count constraint goals are rendered together (rows + cols in one view).
    final constraintGoals = _levelDef.goals
        .where((g) => g.type == 'sum_constraint' || g.type == 'count_constraint')
        .toList();
    if (constraintGoals.isNotEmpty) return _buildConstraintGoals(constraintGoals, state);

    for (final goal in _levelDef.goals) {
      if (goal.type == 'sequence_match') {
        final sequence = (goal.config['sequence'] as List?)
            ?.map((e) => e as int)
            .toList();
        if (sequence != null) {
          final matched = state.sequenceIndices[goal.id] ?? 0;
          return _buildSequenceGoal(sequence, matched);
        }
      }
      if (goal.type == 'board_match') {
        final targetLayers = goal.config['targetLayers'] as Map<String, dynamic>?;
        if (targetLayers != null) {
          return Center(
            child: TargetBoardRenderer(
                targetLayers: targetLayers, currentState: state),
          );
        }
      }
    }
    // Fallback: show goal type as text
    final goalType = _levelDef.goals.first.type.replaceAll('_', ' ');
    return Text(goalType, style: const TextStyle(fontSize: 12));
  }

  Widget _buildSequenceGoal(List<int> sequence, int matched) {
    return Wrap(
      alignment: WrapAlignment.center,
      crossAxisAlignment: WrapCrossAlignment.center,
      runSpacing: 4,
      children: [
        for (int i = 0; i < sequence.length; i++) ...[
          _buildGoalCircle(sequence[i], i < matched),
          if (i < sequence.length - 1)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4),
              child: Icon(Icons.arrow_forward,
                  size: 12, color: Colors.grey.shade500),
            ),
        ],
      ],
    );
  }

  Widget _buildGoalCircle(int number, bool achieved) {
    return Container(
      width: 28,
      height: 28,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: achieved ? Colors.amber.shade400 : Colors.white,
        border: Border.all(
          color: achieved ? Colors.amber.shade700 : Colors.grey.shade400,
          width: achieved ? 2.5 : 1.5,
        ),
      ),
      child: Center(
        child: Text(
          '$number',
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.bold,
            color: achieved ? Colors.white : Colors.grey.shade700,
          ),
        ),
      ),
    );
  }

  /// Renders all sum_constraint and count_constraint goals together:
  /// a natural-language header, the current board as a mini-grid, and live
  /// row/column annotations that turn green when the constraint is satisfied.
  Widget _buildConstraintGoals(List<GoalDef> goals, LevelState state) {
    final layer = state.board.layers['objects'];
    final w = state.board.width;
    final h = state.board.height;

    int cellVal(int x, int y) {
      final entity = layer?.getAt(Position(x, y));
      if (entity == null) return 0;
      final kind = entity.kind;
      if (kind.startsWith('num_')) return int.tryParse(kind.substring(4)) ?? 0;
      return 0;
    }

    // Each annotation slot holds: (computeValue, checkSatisfied) per index.
    // We store a list of checkers per row/col so multiple constraints can apply.
    final rowCheckers = <int, List<(String Function(int y), bool Function(int y))>>{};
    final colCheckers = <int, List<(String Function(int x), bool Function(int x))>>{};
    final descriptions = <String>[];

    for (final goal in goals) {
      final scope = (goal.config['scope'] as String?) ?? 'board';
      final target = goal.config['target'] as num;
      final cmp = (goal.config['comparison'] as String?) ?? 'eq';
      final op = switch (cmp) { 'gte' => '≥', 'lte' => '≤', _ => '=' };
      final t = target.toInt();

      if (goal.type == 'sum_constraint') {
        int rowSum(int y) =>
            List.generate(w, (x) => cellVal(x, y)).fold(0, (a, b) => a + b);
        int colSum(int x) =>
            List.generate(h, (y) => cellVal(x, y)).fold(0, (a, b) => a + b);
        bool checkSum(int sum) => switch (cmp) {
              'gte' => sum >= target,
              'lte' => sum <= target,
              _ => sum == target,
            };

        switch (scope) {
          case 'all_rows':
            for (int y = 0; y < h; y++) {
              rowCheckers.putIfAbsent(y, () => []).add((
                (int y) => '${rowSum(y)}',
                (int y) => checkSum(rowSum(y)),
              ));
            }
            descriptions.add('All rows $op $t');
          case 'all_cols':
            for (int x = 0; x < w; x++) {
              colCheckers.putIfAbsent(x, () => []).add((
                (int x) => '${colSum(x)}',
                (int x) => checkSum(colSum(x)),
              ));
            }
            descriptions.add('All columns $op $t');
          case 'row':
            final idx = (goal.config['index'] as int?) ?? 0;
            rowCheckers.putIfAbsent(idx, () => []).add((
              (int y) => '${rowSum(y)}',
              (int y) => checkSum(rowSum(y)),
            ));
            descriptions.add('Row ${idx + 1} $op $t');
          case 'col':
            final idx = (goal.config['index'] as int?) ?? 0;
            colCheckers.putIfAbsent(idx, () => []).add((
              (int x) => '${colSum(x)}',
              (int x) => checkSum(colSum(x)),
            ));
            descriptions.add('Column ${idx + 1} $op $t');
        }
      } else if (goal.type == 'count_constraint') {
        final predicate = (goal.config['predicate'] as String?) ?? 'even';
        final predLabel = switch (predicate) {
          'even' => 'even',
          'odd' => 'odd',
          String p when p.startsWith('gte_') => '≥${p.substring(4)}',
          String p when p.startsWith('lte_') => '≤${p.substring(4)}',
          _ => predicate,
        };

        bool matchesPred(int value) {
          if (predicate == 'even') return value % 2 == 0;
          if (predicate == 'odd') return value % 2 != 0;
          if (predicate.startsWith('gte_')) return value >= int.parse(predicate.substring(4));
          if (predicate.startsWith('lte_')) return value <= int.parse(predicate.substring(4));
          if (predicate.startsWith('eq_')) return value == int.parse(predicate.substring(3));
          return false;
        }

        int rowCount(int y) {
          int c = 0;
          for (int x = 0; x < w; x++) if (matchesPred(cellVal(x, y))) c++;
          return c;
        }
        int colCount(int x) {
          int c = 0;
          for (int y = 0; y < h; y++) if (matchesPred(cellVal(x, y))) c++;
          return c;
        }
        bool checkCount(int count) => switch (cmp) {
              'gte' => count >= target,
              'lte' => count <= target,
              _ => count == target,
            };

        switch (scope) {
          case 'all_rows':
            for (int y = 0; y < h; y++) {
              rowCheckers.putIfAbsent(y, () => []).add((
                (int y) => '${rowCount(y)}$predLabel',
                (int y) => checkCount(rowCount(y)),
              ));
            }
            descriptions.add('Each row: $op $t $predLabel');
          case 'all_cols':
            for (int x = 0; x < w; x++) {
              colCheckers.putIfAbsent(x, () => []).add((
                (int x) => '${colCount(x)}$predLabel',
                (int x) => checkCount(colCount(x)),
              ));
            }
            descriptions.add('Each col: $op $t $predLabel');
          case 'row':
            final idx = (goal.config['index'] as int?) ?? 0;
            rowCheckers.putIfAbsent(idx, () => []).add((
              (int y) => '${rowCount(y)}$predLabel',
              (int y) => checkCount(rowCount(y)),
            ));
            descriptions.add('Row ${idx + 1}: $op $t $predLabel');
          case 'col':
            final idx = (goal.config['index'] as int?) ?? 0;
            colCheckers.putIfAbsent(idx, () => []).add((
              (int x) => '${colCount(x)}$predLabel',
              (int x) => checkCount(colCount(x)),
            ));
            descriptions.add('Col ${idx + 1}: $op $t $predLabel');
        }
      }
    }

    const cellSz = 22.0;
    const annotW = 28.0;

    Widget miniCell(int val) => Container(
          width: cellSz,
          height: cellSz,
          margin: const EdgeInsets.all(1.5),
          decoration: BoxDecoration(
            color: Colors.grey.shade300,
            borderRadius: BorderRadius.circular(3),
          ),
          child: Center(
            child: Text('$val',
                style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    color: Colors.grey.shade800)),
          ),
        );

    Widget annotation(String label, bool? satisfied) {
      final color = satisfied == null
          ? Colors.grey.shade400
          : satisfied
              ? Colors.green.shade700
              : Colors.orange.shade800;
      return SizedBox(
        width: annotW,
        height: cellSz + 3,
        child: Center(
          child: Text(label,
              style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.bold,
                  color: color)),
        ),
      );
    }

    // Build row annotations: combine labels from all checkers.
    String rowLabel(int y) => rowCheckers[y]!.map((c) => c.$1(y)).join(' ');
    bool rowSatisfied(int y) => rowCheckers[y]!.every((c) => c.$2(y));
    String colLabel(int x) => colCheckers[x]!.map((c) => c.$1(x)).join(' ');
    bool colSatisfied(int x) => colCheckers[x]!.every((c) => c.$2(x));

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          descriptions.join(' · '),
          style: TextStyle(
              fontSize: 11,
              color: Colors.grey.shade600,
              fontStyle: FontStyle.italic),
        ),
        const SizedBox(height: 6),
        Row(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (int y = 0; y < h; y++)
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      for (int x = 0; x < w; x++) miniCell(cellVal(x, y)),
                      if (rowCheckers.isNotEmpty) ...[
                        const SizedBox(width: 2),
                        annotation(
                          rowCheckers.containsKey(y) ? rowLabel(y) : '',
                          rowCheckers.containsKey(y) ? rowSatisfied(y) : null,
                        ),
                      ],
                    ],
                  ),
                if (colCheckers.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      for (int x = 0; x < w; x++)
                        SizedBox(
                          width: cellSz + 3,
                          child: Center(
                            child: Text(
                              colCheckers.containsKey(x) ? colLabel(x) : '',
                              style: TextStyle(
                                fontSize: 10,
                                fontWeight: FontWeight.bold,
                                color: colCheckers.containsKey(x)
                                    ? (colSatisfied(x)
                                        ? Colors.green.shade700
                                        : Colors.orange.shade800)
                                    : Colors.grey.shade400,
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                ],
              ],
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildGuidePanel() {
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: Colors.blue.shade50,
        border: Border.all(color: Colors.blue.shade200),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(children: [
            Icon(Icons.info_outline, color: Colors.blue.shade600, size: 14),
            const SizedBox(width: 4),
            Text('Guide',
                style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    color: Colors.blue.shade700)),
          ]),
          const SizedBox(height: 6),
          Text(
            _levelDef.guide!,
            style: TextStyle(
                fontSize: 11, color: Colors.blue.shade900, height: 1.4),
          ),
        ],
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // Story view
  // ---------------------------------------------------------------------------

  Widget _buildStoryScaffold(SequenceEntry entry) {
    final imageProvider = entry.image != null
        ? widget.packService.resolvePackImage(entry.image!)
        : null;

    return Scaffold(
      backgroundColor: const Color(0xFFF5F0E8),
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios, color: Colors.black54),
          onPressed: _onExit,
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.navigate_before, color: Colors.black54),
            onPressed: _prevEntry,
          ),
          IconButton(
            icon: const Icon(Icons.navigate_next, color: Colors.black54),
            onPressed: _advance,
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            if (imageProvider != null)
              Expanded(
                flex: 5,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(24, 8, 24, 0),
                  child: Image(image: imageProvider, fit: BoxFit.contain),
                ),
              ),
            Expanded(
              flex: 4,
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(28, 16, 28, 8),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (entry.title != null) ...[
                      Text(
                        entry.title!,
                        style: const TextStyle(
                          fontSize: 22,
                          fontWeight: FontWeight.bold,
                          color: Colors.black87,
                        ),
                      ),
                      const SizedBox(height: 12),
                    ],
                    if (entry.text != null)
                      Text(
                        entry.text!,
                        style: TextStyle(
                          fontSize: 15,
                          color: Colors.grey.shade800,
                          height: 1.55,
                        ),
                      ),
                  ],
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(28, 4, 28, 20),
              child: SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: _advance,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF4CAF50),
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12)),
                  ),
                  child: const Text("Let's go!",
                      style: TextStyle(
                          fontSize: 16, fontWeight: FontWeight.w600)),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Short notation for a single action: U/D/L/R for moves, C for clone, etc.
  String _actionShorthand(GameAction action) {
    if (action.actionId == 'move') {
      const map = {'up': 'U', 'down': 'D', 'left': 'L', 'right': 'R'};
      return map[action.directionStr] ?? '?';
    }
    if (action.actionId == 'clone') return 'C';
    return action.actionId.substring(0, 1).toUpperCase();
  }

  /// Returns "Moves: 13/25" if there is a max_actions limit, else "Moves: 13".
  String _movesLabel(LevelState state) {
    final limitCond = _levelDef.loseConditions
        .where((c) => c.type == 'max_actions')
        .firstOrNull;
    final limit = limitCond?.config['limit'] as int?;
    final count = state.actionCount;
    return limit != null ? 'Moves: $count/$limit' : 'Moves: $count';
  }

  void _showGameInfo() {
    final info = widget.packService.info;
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Text(info.title),
        content: SingleChildScrollView(
          child: Text(
            info.description,
            style: const TextStyle(fontSize: 14, height: 1.4),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Got it'),
          ),
        ],
      ),
    );
  }

  Widget _buildStatusBar(LevelState state) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      child: Row(
        children: [
          Text('${_levelIndex + 1}/${_levelIds.length}',
              style: TextStyle(color: Colors.grey.shade600, fontSize: 13)),
          const Spacer(),
          if (_aiRunning) ...[
            Text('Attempt: $_agentAttempt',
                style: TextStyle(color: Colors.grey.shade600, fontSize: 13)),
            const SizedBox(width: 12),
          ],
          Text(_movesLabel(state),
              style: TextStyle(
                color: state.isLost ? Colors.red.shade600 : Colors.grey.shade600,
                fontSize: 13,
                fontWeight: state.isLost ? FontWeight.bold : FontWeight.normal,
              )),
          const SizedBox(width: 4),
          GestureDetector(
            onTap: () {
              final boardText = TextRenderer.render(state, widget.packService.game);
              final moves = _engine.actionHistory.map(_actionShorthand).join('');
              final text = moves.isEmpty
                  ? boardText
                  : '$boardText\nMoves: $moves';
              Clipboard.setData(ClipboardData(text: text));
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                    content: Text('Grid + moves copied to clipboard'),
                    duration: Duration(seconds: 1)),
              );
            },
            child: Icon(Icons.content_copy, size: 14, color: Colors.grey.shade400),
          ),
        ],
      ),
    );
  }

  Widget _buildWinBanner() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(vertical: 14),
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      decoration: BoxDecoration(
        color: Colors.green.shade400,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text('Level Complete!',
              style: TextStyle(
                  color: Colors.white,
                  fontSize: 20,
                  fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          ElevatedButton(
            onPressed: _advance,
            style: ElevatedButton.styleFrom(
                backgroundColor: Colors.white,
                foregroundColor: Colors.green.shade700),
            child: const Text('Next Level'),
          ),
        ],
      ),
    );
  }

  Widget _buildLossBanner() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 20),
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      decoration: BoxDecoration(
        color: Colors.red.shade400,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text('Out of Moves!',
              style: TextStyle(
                  color: Colors.white,
                  fontSize: 20,
                  fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          const Text('Plan the order more carefully.',
              style: TextStyle(color: Colors.white70, fontSize: 13)),
          const SizedBox(height: 10),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              ElevatedButton(
                onPressed: _onReset,
                style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.white,
                    foregroundColor: Colors.red.shade700),
                child: const Text('Try Again'),
              ),
              const SizedBox(width: 12),
              TextButton(
                onPressed: _advance,
                style: TextButton.styleFrom(foregroundColor: Colors.white70),
                child: const Text('Skip Level'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildAiStartButton() {
    if (kIsWeb) {
      return Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
        child: Align(
          alignment: Alignment.centerRight,
          child: Tooltip(
            message: 'AI play requires the native app (browser security restricts API calls)',
            child: TextButton.icon(
              icon: const Icon(Icons.smart_toy_outlined, size: 18),
              label: const Text('Start AI'),
              onPressed: null,
            ),
          ),
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
      child: Align(
        alignment: Alignment.centerRight,
        child: TextButton.icon(
          icon: const Icon(Icons.smart_toy_outlined, size: 18),
          label: const Text('Start AI'),
          onPressed: _startAgent,
        ),
      ),
    );
  }

  Widget _buildAiPanel() {
    final isPaused = _agentSub?.isPaused ?? false;
    final isStep = s.playbackMode == 'step';

    return Container(
      color: Colors.white,
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Icon(Icons.smart_toy_outlined,
                  size: 16, color: Colors.indigo.shade400),
              const SizedBox(width: 6),
              Text(
                isStep
                    ? (isPaused ? 'AI ready' : 'AI thinking…')
                    : 'AI playing…',
                style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: Colors.indigo.shade700),
              ),
              const Spacer(),
              if (_currentAgent is LlmAgent) ...[
                _debugButton('P', _showPrompt),
                const SizedBox(width: 4),
                _debugButton('M', _showMemory),
                const SizedBox(width: 4),
              ],
              if (isStep && isPaused) ...[
                TextButton.icon(
                  icon: const Icon(Icons.person_outline, size: 18),
                  label: const Text('Take over'),
                  style: TextButton.styleFrom(foregroundColor: Colors.grey.shade700),
                  onPressed: _stopAgent,
                ),
                TextButton.icon(
                  icon: const Icon(Icons.skip_next, size: 18),
                  label: Text(s.inferenceMode == 'single'
                      ? 'Infer Action'
                      : 'Infer Actions'),
                  onPressed: _stepAgent,
                ),
              ] else ...[
                TextButton.icon(
                  icon: const Icon(Icons.person_outline, size: 18),
                  label: const Text('Take over'),
                  style: TextButton.styleFrom(foregroundColor: Colors.grey.shade700),
                  onPressed: _stopAgent,
                ),
              ],
            ],
          ),
          if (_lastThinking != null && _lastThinking!.isNotEmpty) ...[
            const SizedBox(height: 6),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: Colors.indigo.shade50,
                borderRadius: BorderRadius.circular(8),
              ),
              constraints: const BoxConstraints(maxHeight: 120),
              child: SingleChildScrollView(
                child: _buildThinkingText(_lastThinking!),
              ),
            ),
          ],
          if (_lastResponse != null && _lastResponse!.isNotEmpty) ...[
            const SizedBox(height: 4),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: Colors.teal.shade50,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.teal.shade100),
              ),
              constraints: const BoxConstraints(maxHeight: 80),
              child: SingleChildScrollView(
                child: SelectableText(
                  _lastResponse!,
                  style: TextStyle(
                    fontSize: 12,
                    fontFamily: 'Courier',
                    color: Colors.teal.shade900,
                    height: 1.4,
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildThinkingText(String text) {
    final parts = text.split('```');
    final baseStyle = TextStyle(
        fontSize: 12, color: Colors.indigo.shade800, height: 1.4);
    final monoStyle = baseStyle.copyWith(fontFamily: 'Courier');

    final spans = <TextSpan>[];
    for (int i = 0; i < parts.length; i++) {
      if (parts[i].isEmpty) continue;
      spans.add(TextSpan(text: parts[i], style: i.isOdd ? monoStyle : baseStyle));
    }
    return SelectableText.rich(TextSpan(children: spans));
  }

  Widget _debugButton(String label, VoidCallback onPressed) {
    return InkWell(
      onTap: onPressed,
      borderRadius: BorderRadius.circular(4),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
        decoration: BoxDecoration(
          border: Border.all(color: Colors.grey.shade300),
          borderRadius: BorderRadius.circular(4),
          color: Colors.grey.shade100,
        ),
        child: Text(label,
            style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: Colors.grey.shade600,
                fontFamily: 'monospace')),
      ),
    );
  }
}
