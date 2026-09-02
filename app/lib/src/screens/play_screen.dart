import 'dart:async';
import 'dart:math' show max, min, sin, sqrt, pi;
import 'package:flutter/foundation.dart' show kDebugMode, kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:gridponder_engine/engine.dart';
import 'package:llm_dart/llm_dart.dart';
import '../services/hint_service.dart';
import '../services/pack_service.dart';
import '../services/playtest_tracker.dart';
import '../services/progress_service.dart';
import '../services/settings_service.dart';
import '../widgets/board_renderer.dart'
    show
        BoardRenderer,
        CellEffectPlayback,
        LineOfSightFeedback,
        MovingMultiCellObject,
        MovingSprite,
        TargetBoardRenderer,
        cellNamedColor,
        elasticBlockRect,
        elasticBlockRectTween,
        elasticPushObjectTravel;
import '../widgets/controls_widget.dart';

/// One entity travelling from [from] to [to] during a turn's animation.
typedef _Mover = ({
  Position from,
  Position to,
  EntityInstance entity,
  String layer,
  String? direction,
  double distance,
  bool falling,
});

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

class _PlayScreenState extends State<PlayScreen> with TickerProviderStateMixin {
  late List<SequenceEntry> _sequence;
  late int _seqIndex;
  late List<String> _levelIds;
  late LevelDefinition _levelDef;
  late TurnEngine _engine;
  late HintService _hintService;
  final _tracker = PlaytestTracker();

  /// Dry-run results for the actions available from where the avatar stands,
  /// memoised against the board position they describe. See
  /// [_computeActionPreviews].
  Map<Position, Set<Position>> _actionPreviews = const {};
  String? _actionPreviewKey;

  /// Which preview the pointer is over, when there is a pointer to speak of.
  Position? _hoveredPreviewTarget;

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
  final GlobalKey _boardKey = GlobalKey();
  Offset? _panStart;
  Position? _panStartCell;
  String? _selectedMultiCellObjectId;
  static const double _swipeThreshold = 18.0;
  static const int _elasticCellTravelMs = 57;
  static const int _elasticMinTravelMs = 80;
  static const int _elasticMaxTravelMs = 400;

  // Periodic timer to refresh hint dot availability
  Timer? _hintRefreshTimer;

  // Animation state: non-null while an entity animation is playing.
  LevelState? _preAnimState;
  Map<Position, String>? _animOverlays;
  List<LineOfSightFeedback> _lineOfSightFeedbacks = const [];
  List<CellEffectPlayback> _cellEffects = const [];
  bool _animating = false;

  /// Entities in flight, updated at frame rate while motion plays. Kept off
  /// [setState] so a fall repaints the sprites alone rather than the screen.
  final ValueNotifier<List<MovingSprite>> _movingSprites = ValueNotifier(
    const [],
  );
  final ValueNotifier<List<MovingMultiCellObject>> _movingMultiCellObjects =
      ValueNotifier(const []);
  Map<String, String> _actorFacingByKind = {};
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
        (e) => e.type == 'level' && e.ref == startId,
      );
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
    _movingSprites.dispose();
    _movingMultiCellObjects.dispose();
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
    _actorFacingByKind = {};
    _wonHandled = false;
    _selectedMultiCellObjectId = null;
    _lineOfSightFeedbacks = const [];
    _movingSprites.value = const [];
    _tracker.track('level_start', level: levelId);
    _movingMultiCellObjects.value = const [];
  }

  Future<void> _onAction(GameAction action) async {
    if (_aiRunning || _animating) return;
    await _runAction(action);
  }

  /// Runs [action] through the engine and plays its full animation queue.
  /// Used by user input ([_onAction]) and replay paths ([_onSolve],
  /// [_playHint]) so all entry points show the same animations.
  Future<void> _runAction(GameAction action, {String source = 'user'}) async {
    final preState = _engine.state.copy();
    final result = _engine.executeTurn(action);
    if (!result.accepted) {
      _tracker.track(
        'move',
        level: _levelDef.id,
        action: action.actionId,
        outcome: 'rejected',
        src: source,
      );
      return;
    }
    _tracker.track(
      'move',
      level: _levelDef.id,
      action: action.actionId,
      outcome: 'accepted',
      src: source,
      n: _engine.undoDepth,
      pos: _tracker.enabled ? _trackedPositions() : null,
    );
    _syncSelectedMultiCellObject();

    // Record the chosen colour for any colour-pick action (any action that
    // declares a `color` in game.json). The play screen uses it to tint the
    // most recently flooded region in flood_colors-style packs.
    final actionDef = widget.packService.game.actions.firstWhere(
      (a) => a.id == action.actionId,
      orElse: () => const ActionDef(id: '', params: {}),
    );
    if (actionDef.color != null) {
      _lastFloodColor = cellNamedColor(
        actionDef.color!,
        palette: widget.packService.theme?.palette,
      );
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
        setState(
          () => _avatarSlidePos = Position(toRaw[0] as int, toRaw[1] as int),
        );
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
    final elasticMotionEvent = result.events
        .where(
          (event) =>
              event.type == 'elastic_block_inflated' ||
              event.type == 'elastic_block_collapsed',
        )
        .firstOrNull;
    var elasticMotionPlayed = false;
    if (pushEvents.isNotEmpty) {
      final trackedPushEvents = pushEvents
          .where((event) => event.payload['originPosition'] != null)
          .toList();
      if (trackedPushEvents.isNotEmpty) {
        final inflationEvent = result.events
            .where((event) => event.type == 'elastic_block_inflated')
            .firstOrNull;
        await _playTrackedObjectPushes(
          preState,
          trackedPushEvents,
          inflationEvent: inflationEvent,
        );
        elasticMotionPlayed = inflationEvent != null;
      }

      final pushByKind = <String, List<GameEvent>>{};
      for (final e in pushEvents.where(
        (event) => event.payload['originPosition'] == null,
      )) {
        final k = e.payload['kind'] as String?;
        if (k != null) pushByKind.putIfAbsent(k, () => []).add(e);
      }
      for (final entry in pushByKind.entries) {
        if (hasSlide || entry.value.length > 1) {
          await _playObjectSlide(preState, entry.key, entry.value);
        }
      }
    }
    if (!elasticMotionPlayed && elasticMotionEvent != null) {
      await _playElasticBlockMotion(preState, elasticMotionEvent);
    }

    // Clear slide overrides: _playObjectSlide already cleared _preAnimState and
    // _animOverlays, but _avatarSlidePos needs explicit cleanup here.
    if (hasSlide) {
      if (!mounted) return;
      setState(() {
        _preAnimState = null; // no-op if _playObjectSlide already cleared it
        _avatarSlidePos = null;
      });
    }

    // Stage-aware playback for new motion primitives.
    // Group remaining animations by stage; play each stage to completion
    // before starting the next.
    final remaining =
        result.animations
            .where(
              (s) => s.type == 'entity_move' || s.type == 'entity_animation',
            )
            .toList()
          ..sort((a, b) => a.stage.compareTo(b.stage));

    // Cells this turn removed outright. A collapse animation replays from the
    // pre-turn board, so without this the cut cell would stay on screen while
    // the piece it was holding falls away from it.
    final clearedCells = result.events
        .where((e) => e.type == 'cell_cleared' && e.position != null)
        .map(
          (e) => (
            layer: e.payload['layer'] as String? ?? 'objects',
            position: e.position!,
          ),
        )
        .toList();

    int? currentStage;
    final stageBuf = <AnimationStep>[];
    Future<void> flushStage() async {
      if (stageBuf.isEmpty) return;
      final moves = stageBuf.where((s) => s.type == 'entity_move').toList();
      final anims = stageBuf
          .where((s) => s.type == 'entity_animation')
          .toList();
      if (moves.isNotEmpty) {
        await _playSlideMotion(preState, moves, clearedCells: clearedCells);
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

    await _playLineOfSightFeedback(result.events);
    await _playCellEffects(result.events);

    if (!mounted) return;
    setState(() => _animating = false);
  }

  /// The cells the player's pieces occupy right now, as `x.y` joined by commas
  /// (e.g. `"2.1,6.3"`). Empty when the pack has neither.
  ///
  /// A pack moves either a level `avatar` (keystone, relay_lanterns) or entities
  /// on a system's `actorLayer` (spoil, pincer, three_kingdoms), so both are
  /// collected. `actorLayer` defaults to `"actors"` in the DSL, so a board with an
  /// `actors` layer is used when no system names one explicitly.
  String _trackedPositions() {
    final board = _engine.state.board;
    final cells = <Position>{};

    final avatarPos = _engine.state.avatar.position;
    if (avatarPos != null) cells.add(avatarPos);

    var layerIds = <String>{
      for (final s in widget.packService.game.systems)
        if (s.enabled && s.config['actorLayer'] is String)
          s.config['actorLayer'] as String,
    };
    if (layerIds.isEmpty && board.layers.containsKey('actors')) {
      layerIds = {'actors'};
    }
    for (final id in layerIds) {
      final layer = board.layers[id];
      if (layer == null) continue;
      for (final entry in layer.entries()) {
        cells.add(entry.key);
      }
    }

    final sorted = cells.toList()
      ..sort((a, b) => a.y != b.y ? a.y.compareTo(b.y) : a.x.compareTo(b.x));
    return sorted.map((p) => '${p.x}.${p.y}').join(',');
  }

  /// Plays any theme-declared sprite-strip effects triggered by this turn's
  /// events — e.g. a burst on every `cell_transformed`. Purely presentational:
  /// packs opt in through `theme.json`'s `effects` block, and a pack that
  /// declares none costs nothing here.
  Future<void> _playCellEffects(List<GameEvent> events) async {
    final effects = widget.packService.theme?.effects;
    if (effects == null || effects.isEmpty) return;

    final targets = <CellEffectPlayback>[];
    CellEffectDef? active;
    for (final event in events) {
      final candidates = effects[event.type];
      if (candidates == null) continue;
      // First matching `when` filter wins, so several effects can share one
      // event type — a cut and a backfill are both `cell_transformed`.
      CellEffectDef? def;
      for (final candidate in candidates) {
        if (candidate.matches(event.payload)) {
          def = candidate;
          break;
        }
      }
      if (def == null) continue;
      final pos = event.position;
      if (pos == null) continue;
      active = def;
      targets.add(CellEffectPlayback(position: pos, def: def, frameIndex: 0));
    }
    if (targets.isEmpty || active == null) return;

    final frames = active.frames < 1 ? 1 : active.frames;
    final perFrame = Duration(
      milliseconds: (active.durationMs / frames).round().clamp(16, 1000),
    );
    for (var frame = 0; frame < frames; frame++) {
      if (!mounted) return;
      setState(() {
        _cellEffects = [
          for (final t in targets)
            CellEffectPlayback(
              position: t.position,
              def: t.def,
              frameIndex: frame,
            ),
        ];
      });
      await Future.delayed(perFrame);
    }
    if (!mounted) return;
    setState(() => _cellEffects = const []);
  }

  Future<void> _playLineOfSightFeedback(List<GameEvent> events) async {
    final feedbacks = <LineOfSightFeedback>[];
    for (final event in events) {
      if (event.type != 'line_of_sight_detected') continue;
      final source = _positionFromPayload(event.payload['sourcePosition']);
      final target = event.position;
      final kind = event.payload['kind'] as String?;
      if (source == null || target == null || kind == null) continue;
      feedbacks.add(
        LineOfSightFeedback(source: source, target: target, kind: kind),
      );
    }
    if (feedbacks.isEmpty) return;

    if (!mounted) return;
    setState(() => _lineOfSightFeedbacks = feedbacks);
    await Future.delayed(const Duration(milliseconds: 220));
    if (!mounted) return;
    setState(() => _lineOfSightFeedbacks = const []);
  }

  Position? _positionFromPayload(dynamic raw) {
    if (raw == null) return null;
    if (raw is Position) return raw;
    if (raw is List && raw.length >= 2) {
      final x = raw[0];
      final y = raw[1];
      if (x is int && y is int) return Position(x, y);
    }
    return null;
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

  /// Animates every object pushed by an elastic face as one continuous move.
  /// The engine supplies a stable origin for each object, so adjacent crates
  /// and crates on different rows remain distinct even when they share a kind.
  Future<void> _playTrackedObjectPushes(
    LevelState preState,
    List<GameEvent> pushEvents, {
    GameEvent? inflationEvent,
  }) async {
    final tracks =
        <
          String,
          ({
            Position origin,
            Position to,
            String kind,
            String layer,
            String? direction,
          })
        >{};

    Position positionFrom(dynamic raw) =>
        raw is Position ? raw : Position.fromJson(raw);
    for (final event in pushEvents) {
      final rawOrigin = event.payload['originPosition'];
      final rawTo = event.payload['toPosition'];
      final kind = event.payload['kind'] as String?;
      if (rawOrigin == null || rawTo == null || kind == null) continue;
      final origin = positionFrom(rawOrigin);
      final layer = event.payload['layer'] as String? ?? 'objects';
      final key = '$layer:${origin.x},${origin.y}';
      tracks[key] = (
        origin: origin,
        to: positionFrom(rawTo),
        kind: kind,
        layer: layer,
        direction: event.payload['direction'] as String?,
      );
    }
    if (tracks.isEmpty) return;

    final movers = <_Mover>[];
    for (final track in tracks.values) {
      final entity =
          preState.board.getEntity(track.layer, track.origin) ??
          EntityInstance(track.kind, const {});
      final dx = track.to.x - track.origin.x;
      final dy = track.to.y - track.origin.y;
      movers.add((
        from: track.origin,
        to: track.to,
        entity: entity,
        layer: track.layer,
        direction: track.direction,
        distance: max(dx.abs(), dy.abs()).toDouble(),
        falling: false,
      ));
    }
    final rawDistance = inflationEvent?.payload['distance'];
    final inflationDistance = rawDistance is num ? rawDistance.toDouble() : 0.0;
    final span = max(
      inflationDistance,
      movers.map((mover) => mover.distance).reduce(max),
    );
    if (span <= 0) return;

    final blockId = inflationEvent?.payload['id'] as String?;
    final direction = inflationEvent?.payload['direction'] as String?;
    final block = blockId == null
        ? null
        : preState.board.getMultiCellObject(blockId);
    final canAnimateBlock =
        block != null &&
        direction != null &&
        inflationDistance > 0 &&
        block.cells.isNotEmpty;

    double minX(Iterable<Position> cells) =>
        cells.map((cell) => cell.x).reduce((a, b) => a < b ? a : b).toDouble();
    double maxX(Iterable<Position> cells) =>
        cells.map((cell) => cell.x).reduce((a, b) => a > b ? a : b).toDouble();
    double minY(Iterable<Position> cells) =>
        cells.map((cell) => cell.y).reduce((a, b) => a < b ? a : b).toDouble();
    double maxY(Iterable<Position> cells) =>
        cells.map((cell) => cell.y).reduce((a, b) => a > b ? a : b).toDouble();

    final startLeft = canAnimateBlock ? minX(block.cells) : 0.0;
    final startRight = canAnimateBlock ? maxX(block.cells) + 1 : 0.0;
    final startTop = canAnimateBlock ? minY(block.cells) : 0.0;
    final startBottom = canAnimateBlock ? maxY(block.cells) + 1 : 0.0;

    final animState = preState.copy();
    for (final mover in movers) {
      animState.board.setEntity(mover.layer, mover.from, null);
    }
    if (canAnimateBlock) {
      animState.board.multiCellObjects.removeWhere(
        (object) => object.id == block.id,
      );
    }
    if (!mounted) return;
    setState(() {
      _preAnimState = animState;
      _animOverlays = null;
    });

    final travelMs = (_elasticCellTravelMs * span).round().clamp(
      _elasticMinTravelMs,
      _elasticMaxTravelMs,
    );
    final controller = AnimationController(
      vsync: this,
      duration: Duration(milliseconds: travelMs),
    );
    void emit() {
      final blockTravel = span * controller.value;
      _movingSprites.value = [
        for (final mover in movers)
          _translatedSprite(
            mover,
            elasticPushObjectTravel(
              blockTravel: blockTravel,
              totalBlockDistance: span,
              objectDistance: mover.distance,
            ),
          ),
      ];
      if (canAnimateBlock) {
        final rect = elasticBlockRect(
          Rect.fromLTRB(startLeft, startTop, startRight, startBottom),
          direction,
          blockTravel,
        );
        _movingMultiCellObjects.value = [
          MovingMultiCellObject(
            object: block.copy(),
            left: rect.left,
            top: rect.top,
            width: rect.width,
            height: rect.height,
            selected:
                block.id == _selectedMultiCellObjectId ||
                _selectedMultiCellObjectForRenderer(preState) == block.id,
          ),
        ];
      }
    }

    controller.addListener(emit);
    emit();
    try {
      await controller.forward();
    } finally {
      controller.dispose();
    }
    if (!mounted) {
      _movingSprites.value = const [];
      _movingMultiCellObjects.value = const [];
      return;
    }
    setState(() => _preAnimState = null);
    _movingSprites.value = const [];
    _movingMultiCellObjects.value = const [];
  }

  MovingSprite _translatedSprite(_Mover mover, double travelled) {
    final entity = mover.direction == null
        ? mover.entity
        : EntityInstance(mover.entity.kind, {
            ...mover.entity.params,
            '_motionDirection': mover.direction,
            '_motionFrame': travelled.floor(),
          });
    final ratio = mover.distance == 0 ? 0.0 : travelled / mover.distance;
    return MovingSprite(
      entity: entity,
      x: mover.from.x + (mover.to.x - mover.from.x) * ratio,
      y: mover.from.y + (mover.to.y - mover.from.y) * ratio,
    );
  }

  Future<void> _playElasticBlockMotion(
    LevelState preState,
    GameEvent event,
  ) async {
    List<Position> positionsFrom(dynamic raw) {
      if (raw is! List) return const [];
      return [
        for (final item in raw)
          if (item is Position)
            item
          else if (item is List)
            Position.fromJson(item),
      ];
    }

    Rect bounds(Iterable<Position> cells) {
      final list = cells.toList();
      final left = list.map((cell) => cell.x).reduce(min).toDouble();
      final right = list.map((cell) => cell.x).reduce(max).toDouble() + 1;
      final top = list.map((cell) => cell.y).reduce(min).toDouble();
      final bottom = list.map((cell) => cell.y).reduce(max).toDouble() + 1;
      return Rect.fromLTRB(left, top, right, bottom);
    }

    final fromCells = positionsFrom(event.payload['fromCells']);
    final toCells = positionsFrom(event.payload['toCells']);
    final blockId = event.payload['id'] as String?;
    final block = blockId == null
        ? null
        : preState.board.getMultiCellObject(blockId);
    if (block == null || fromCells.isEmpty || toCells.isEmpty) return;

    final start = bounds(fromCells);
    final end = bounds(toCells);
    final span = [
      (start.left - end.left).abs(),
      (start.top - end.top).abs(),
      (start.right - end.right).abs(),
      (start.bottom - end.bottom).abs(),
    ].reduce(max);
    if (span <= 0) return;

    final animState = preState.copy();
    animState.board.multiCellObjects.removeWhere(
      (object) => object.id == block.id,
    );
    if (!mounted) return;
    setState(() {
      _preAnimState = animState;
      _animOverlays = null;
    });

    final selected =
        block.id == _selectedMultiCellObjectId ||
        _selectedMultiCellObjectForRenderer(preState) == block.id;
    final travelMs = (_elasticCellTravelMs * span).round().clamp(
      _elasticMinTravelMs,
      _elasticMaxTravelMs,
    );
    final controller = AnimationController(
      vsync: this,
      duration: Duration(milliseconds: travelMs),
    );
    void emit() {
      final rect = elasticBlockRectTween(start, end, controller.value);
      _movingMultiCellObjects.value = [
        MovingMultiCellObject(
          object: block.copy(),
          left: rect.left,
          top: rect.top,
          width: rect.width,
          height: rect.height,
          selected: selected,
        ),
      ];
    }

    controller.addListener(emit);
    emit();
    try {
      await controller.forward();
    } finally {
      controller.dispose();
    }
    if (!mounted) {
      _movingMultiCellObjects.value = const [];
      return;
    }
    setState(() => _preAnimState = null);
    _movingMultiCellObjects.value = const [];
  }

  /// Animates `entity_move` steps as real motion: each entity is lifted out of
  /// the board and drawn as a sprite between cells, interpolated every frame,
  /// rather than stamped into one cell after the next.
  ///
  /// Downward moves are read as falls and share one acceleration, scaled so the
  /// longest drop in the group lands exactly as travel ends. That is what makes
  /// a collapse legible: everything leaves together, the short drops land
  /// first, and the piece that travelled furthest arrives fastest. Lateral
  /// travel (an ice slide, a pushed block) keeps its constant per-cell pace.
  ///
  /// [clearedCells] are cells the turn removed outright (`cell_cleared`). They
  /// are gone for the whole animation, so a piece that falls *because* a cell
  /// was cut is not drawn still hanging from it.
  Future<void> _playSlideMotion(
    LevelState preState,
    List<AnimationStep> moves, {
    List<({String layer, Position position})> clearedCells = const [],
  }) async {
    if (moves.isEmpty) return;

    final movers = <_Mover>[];
    for (final step in moves) {
      final fromRaw = step.extra['from'];
      if (fromRaw is! List) continue;
      final from = Position(fromRaw[0] as int, fromRaw[1] as int);
      final to = step.position;
      if (from == to) continue;

      final paramsRaw = step.extra['params'];
      final params = (paramsRaw is Map)
          ? paramsRaw.cast<String, dynamic>()
          : const <String, dynamic>{};
      final dx = to.x - from.x;
      final dy = to.y - from.y;
      movers.add((
        from: from,
        to: to,
        entity: EntityInstance(step.entityKind ?? '', params),
        layer: step.extra['layer'] as String? ?? 'objects',
        direction: _directionBetween(from, to),
        distance: (dx.abs() > dy.abs() ? dx.abs() : dy.abs()).toDouble(),
        // Straight down and nothing else is a fall; anything else is carried.
        falling: dx == 0 && dy > 0,
      ));
    }
    if (movers.isEmpty) return;

    final span = movers.map((m) => m.distance).reduce(max);
    final falls = movers.any((m) => m.falling);
    // Per-cell pacing for carried travel — the engine's `moveDurationMs`
    // convention. A fall instead takes the time gravity would take, which
    // grows with the square root of the drop, not with the drop.
    final perCellMs = moves.first.durationMs > 0
        ? moves.first.durationMs.clamp(40, 400)
        : 130;
    final travelMs = falls
        ? (_fallCellMs * sqrt(span)).round()
        : (perCellMs * span).round();
    final totalMs = travelMs + (falls ? _impactMs : 0);

    // Hold the pre-turn board with the movers lifted out of it: for the length
    // of the animation the only copy of each is the sprite in flight.
    final animState = preState.copy();
    for (final m in movers) {
      animState.board.setEntity(m.layer, m.from, null);
    }
    for (final cleared in clearedCells) {
      animState.board.setEntity(cleared.layer, cleared.position, null);
    }
    if (!mounted) return;
    setState(() {
      _preAnimState = animState;
      _animOverlays = null;
    });

    final controller = AnimationController(
      vsync: this,
      duration: Duration(milliseconds: totalMs),
    );
    void emit() {
      final elapsedMs = controller.value * totalMs;
      _movingSprites.value = [
        for (final m in movers) _spriteInFlight(m, elapsedMs, travelMs, span),
      ];
    }

    controller.addListener(emit);
    emit();
    try {
      await controller.forward();
    } finally {
      controller.dispose();
    }

    // Land the movers into the held board and drop the sprites in the same
    // frame, so nothing blinks between the last frame of flight and rest.
    final postState = animState.copy();
    for (final m in movers) {
      if (postState.board.getEntity(m.layer, m.to) == null) {
        postState.board.setEntity(m.layer, m.to, m.entity);
      }
    }
    if (!mounted) {
      _movingSprites.value = const [];
      return;
    }
    final facingUpdates = <String, String>{
      for (final m in movers)
        if (m.layer == 'actors' && m.direction != null)
          m.entity.kind: m.direction!,
    };
    setState(() {
      _preAnimState = postState;
      if (facingUpdates.isNotEmpty) {
        _actorFacingByKind = {..._actorFacingByKind, ...facingUpdates};
      }
    });
    _movingSprites.value = const [];
  }

  /// A one-cell drop, in milliseconds. Longer drops scale as its square root,
  /// which is how far gravity actually gets in a given time.
  static const _fallCellMs = 190;

  /// How long the squash on landing lasts.
  static const _impactMs = 140;

  /// Where [m] is at [elapsedMs], and how compressed.
  ///
  /// Distance travelled under a shared acceleration `span * t²` (falls) or a
  /// shared speed `span * t` (everything else), clamped at the mover's own
  /// distance — so each one stops on arrival while the rest keep going.
  MovingSprite _spriteInFlight(
    _Mover m,
    double elapsedMs,
    int travelMs,
    double span,
  ) {
    final t = (elapsedMs / travelMs).clamp(0.0, 1.0);
    final reach = m.falling ? span * t * t : span * t;
    final travelled = reach < m.distance ? reach : m.distance;

    // Squash on impact, easing in and back out, so the piece arrives with a
    // weight rather than simply stopping.
    var squash = 1.0;
    if (m.falling) {
      final landedAtMs = travelMs * sqrt(m.distance / span);
      final since = (elapsedMs - landedAtMs) / _impactMs;
      if (since >= 0 && since <= 1) squash = 1 - 0.18 * sin(pi * since);
    }

    final entity = m.direction == null
        ? m.entity
        : EntityInstance(m.entity.kind, {
            ...m.entity.params,
            '_motionDirection': m.direction,
            '_motionFrame': travelled.floor(),
          });
    return MovingSprite(
      entity: entity,
      x: m.from.x + (m.to.x - m.from.x).sign * travelled,
      y: m.from.y + (m.to.y - m.from.y).sign * travelled,
      squash: squash,
    );
  }

  String? _directionBetween(Position from, Position to) {
    final dx = to.x - from.x;
    final dy = to.y - from.y;
    if (dx.abs() > dy.abs()) return dx > 0 ? 'right' : 'left';
    if (dy != 0) return dy > 0 ? 'down' : 'up';
    return null;
  }

  Future<void> _playEntityAnimation(
    LevelState preState,
    AnimationStep step,
  ) async {
    final kindDef = widget.packService.game.entityKinds[step.entityKind];
    final animDef = kindDef?.animations[step.animationName!];
    if (animDef == null || animDef.frames.isEmpty) return;

    // For object-layer entities (wood, rock…), remove them from the board so
    // animation frames render cleanly without the original sprite bleeding through.
    // For ground-layer entities (ice…), keep the original tile visible beneath
    // the overlay frames — clearing ground would show void/black behind the anim.
    final cleanState = preState.copy();
    final layer =
        widget.packService.game.entityKinds[step.entityKind]?.layer ??
        'objects';
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

  /// What each action the player could take right now would set in motion,
  /// keyed by the cell that action targets. An entry with an empty set means
  /// the action is legal but moves nothing — which is the single hardest thing
  /// to read off a static board in a game about load-bearing structure.
  ///
  /// Only cells adjacent to the avatar are probed, which is the reach of a
  /// tap-to-act verb, and only packs that bind `tap_cell` get previews at all.
  /// Packs whose tap does not move anything produce empty sets and render
  /// nothing, so this costs them a handful of dry runs and no pixels.
  Map<Position, Set<Position>> _computeActionPreviews() {
    final gestureMap = widget.packService.theme?.controls?.gestureMap;
    final avatar = _engine.state.avatar;
    final origin = avatar.position;
    if (gestureMap == null ||
        !avatar.enabled ||
        origin == null ||
        _engine.isWon ||
        _engine.isLost) {
      return const {};
    }
    // Named via inference: the engine's binding type shares a name with
    // Flutter's own GestureBinding.
    final tapBindings = gestureMap.where((b) => b.gesture == 'tap_cell');
    if (tapBindings.isEmpty) return const {};
    final binding = tapBindings.first;

    const neighbours = [
      Position(0, -1),
      Position(0, 1),
      Position(-1, 0),
      Position(1, 0),
    ];
    final previews = <Position, Set<Position>>{};
    for (final delta in neighbours) {
      final target = Position(origin.x + delta.x, origin.y + delta.y);
      if (!_engine.state.board.isInBounds(target)) continue;

      final params = <String, dynamic>{};
      binding.paramMapping?.forEach((key, value) {
        params[key] = value == 'tap_position' ? [target.x, target.y] : value;
      });
      if (binding.params != null) params.addAll(binding.params!);

      final result = _engine.previewTurn(GameAction(binding.action, params));
      if (!result.accepted) continue;

      // Report the cells in the places they occupy *now*, so the outline sits
      // on the structure the player is looking at rather than on the floor.
      final moving = <Position>{};
      for (final event in result.events) {
        if (event.type != 'object_settled') continue;
        final from = event.payload['fromPosition'];
        final to = event.position;
        if (from == null || to == null) continue;
        final fromPos = from is Position ? from : Position.fromJson(from);
        if (fromPos != to) moving.add(fromPos);
      }
      previews[target] = moving;
    }
    return previews;
  }

  void _onUndo() {
    if (_aiRunning) return;
    setState(() {
      _engine.undo();
      _lastFloodColor = null;
      _syncSelectedMultiCellObject();
    });
    _tracker.track('undo', level: _levelDef.id);
  }

  void _onReset() {
    _stopAgent();
    setState(() {
      _engine.reset();
      _lastThinking = null;
      _lastResponse = null;
      _lastFloodColor = null;
      _selectedMultiCellObjectId = null;
      _lineOfSightFeedbacks = const [];
      _actorFacingByKind = {};
    });
    _tracker.track('reset', level: _levelDef.id);
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

  SystemDef? get _individualActorSystem {
    final effectiveGame = widget.packService.game.withSystemOverrides(
      _levelDef.systemOverrides,
    );
    for (final system in effectiveGame.systems) {
      if (system.type == 'individual_actors' && system.enabled) return system;
    }
    return null;
  }

  ActionDef? get _primaryMoveAction {
    final effectiveGame = widget.packService.game.withSystemOverrides(
      _levelDef.systemOverrides,
    );
    for (final system in effectiveGame.systems) {
      if (system.type != 'sliding_blocks' || !system.enabled) continue;
      final actionId = system.config['moveAction'] as String? ?? 'move';
      for (final action in effectiveGame.actions) {
        if (action.id == actionId) return action;
      }
    }
    for (final action in effectiveGame.actions) {
      if (action.id == 'move') return action;
    }
    return null;
  }

  bool get _hasMoveAction => _primaryMoveAction != null;
  bool get _moveActionNeedsPosition =>
      _primaryMoveAction?.params.containsKey('position') ?? false;

  String? _selectedMultiCellObjectForRenderer(LevelState state) {
    if (_moveActionNeedsPosition) return _selectedMultiCellObjectId;
    final effectiveGame = widget.packService.game.withSystemOverrides(
      _levelDef.systemOverrides,
    );
    for (final system in effectiveGame.systems) {
      if (system.type != 'elastic_block' || !system.enabled) continue;
      final objectKind =
          system.config['objectKind'] as String? ?? 'elastic_block';
      final controlled = state.board.multiCellObjects
          .where((object) => object.kind == objectKind)
          .toList();
      if (controlled.length == 1) return controlled.single.id;
    }
    return null;
  }

  bool get _hasCellTapGesture =>
      widget.packService.theme?.controls?.gestureMap.any(
        (binding) => binding.gesture == 'tap_cell',
      ) ??
      false;

  /// Action IDs whose colour is currently adjacent to the flood region.
  /// Only computed when the game has colour-pick actions (declared via the
  /// `color` field on an ActionDef).
  Set<String>? _availableFloodActions(LevelState state) {
    final hasFloodActions = widget.packService.game.actions.any(
      (a) => a.color != null,
    );
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
          if (nx < 0 ||
              ny < 0 ||
              nx >= state.board.width ||
              ny >= state.board.height)
            continue;
          final nb = layer.getAt(Position(nx, ny));
          final kind = nb?.kind;
          if (kind != null &&
              kind.startsWith('cell_') &&
              kind != 'cell_flooded' &&
              kind != 'cell_wall') {
            available.add('flood_${kind.substring(5)}');
          }
        }
      }
    }
    return available;
  }

  void _onCellTap(int x, int y) {
    if (_aiRunning || _animating) return;
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
    if (_moveActionNeedsPosition) {
      setState(() {
        _selectedMultiCellObjectId = _multiCellObjectIdAt(Position(x, y));
      });
    }
  }

  void _onPanStart(DragStartDetails d) {
    _panStart = d.globalPosition;
    _panStartCell = _cellAtGlobalPosition(d.globalPosition);
    if (_moveActionNeedsPosition) {
      final selectedId = _panStartCell == null
          ? null
          : _multiCellObjectIdAt(_panStartCell!);
      if (selectedId != _selectedMultiCellObjectId) {
        setState(() => _selectedMultiCellObjectId = selectedId);
      }
    }
  }

  void _onPanCancel() {
    _panStart = null;
    _panStartCell = null;
  }

  void _onPanEnd(DragEndDetails _) {
    _panStart = null;
    _panStartCell = null;
  }

  void _onPanUpdate(DragUpdateDetails details) {
    if (_panStart == null) return;
    final delta = details.globalPosition - _panStart!;
    if (delta.distance < _swipeThreshold) return;

    final action = _detectSwipeAction(delta);
    if (action == null) return;

    _panStart = null;
    _panStartCell = null;
    _onAction(action);
  }

  Position? _cellAtGlobalPosition(Offset globalPosition) {
    final context = _boardKey.currentContext;
    final renderObject = context?.findRenderObject();
    if (renderObject is! RenderBox) return null;
    final local = renderObject.globalToLocal(globalPosition);
    final size = renderObject.size;
    if (local.dx < 0 ||
        local.dy < 0 ||
        local.dx >= size.width ||
        local.dy >= size.height) {
      return null;
    }
    final board = _engine.state.board;
    final x = (local.dx / (size.width / board.width)).floor();
    final y = (local.dy / (size.height / board.height)).floor();
    if (x < 0 || y < 0 || x >= board.width || y >= board.height) return null;
    return Position(x, y);
  }

  String? _multiCellObjectIdAt(Position pos) {
    for (final block in _engine.state.board.multiCellObjects) {
      if (block.cells.contains(pos)) return block.id;
    }
    return null;
  }

  Position? _selectedMovePosition() {
    final id = _selectedMultiCellObjectId;
    if (id == null) return null;
    for (final block in _engine.state.board.multiCellObjects) {
      if (block.id == id && block.cells.isNotEmpty) return block.cells.first;
    }
    return null;
  }

  void _syncSelectedMultiCellObject() {
    if (_selectedMultiCellObjectId == null) return;
    final stillPresent = _engine.state.board.multiCellObjects.any(
      (block) => block.id == _selectedMultiCellObjectId,
    );
    if (!stillPresent) _selectedMultiCellObjectId = null;
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
    if (_moveActionNeedsPosition && _panStartCell == null) return null;
    final String dir;
    if (ax > ay) {
      dir = delta.dx > 0 ? 'right' : 'left';
    } else {
      dir = delta.dy > 0 ? 'down' : 'up';
    }
    return GameAction(_primaryMoveAction!.id, {
      'direction': dir,
      if (_moveActionNeedsPosition)
        'position': [_panStartCell!.x, _panStartCell!.y],
    });
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

    _tracker.track('hint_requested', level: _levelDef.id);
    await _playHint(idx);
  }

  Future<bool> _showHintConfirmation() async {
    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Row(
          children: [
            Icon(
              Icons.lightbulb_outline,
              color: Colors.amber.shade600,
              size: 26,
            ),
            const SizedBox(width: 10),
            const Text(
              'Use Hint',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
            ),
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
                  Icon(Icons.refresh, color: Colors.orange.shade700, size: 18),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: Text(
                      'The level will be reset to its starting state.',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                      ),
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
            child: Text(
              'Cancel',
              style: TextStyle(color: Colors.grey.shade600),
            ),
          ),
          ElevatedButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.amber.shade600,
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(8),
              ),
            ),
            child: const Text(
              'Reset & Play Hint',
              style: TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    );
    return result == true;
  }

  Future<void> _onSolve() async {
    final goldPath = _levelDef.solution.goldPath;
    if (goldPath.isEmpty) return;
    setState(() {
      _engine.reset();
      _selectedMultiCellObjectId = null;
      _lineOfSightFeedbacks = const [];
    });
    await Future.delayed(Duration.zero);
    for (int i = 0; i < goldPath.length; i++) {
      if (!mounted) return;
      await _runAction(goldPath[i], source: 'solve');
      await Future.delayed(const Duration(milliseconds: 300));
    }
  }

  Future<void> _playHint(int hintIndex) async {
    _hintService.markUsed(hintIndex);
    final stopCount = _levelDef.solution.hintStops[hintIndex];
    final goldPath = _levelDef.solution.goldPath;

    setState(() {
      _engine.reset();
      _selectedMultiCellObjectId = null;
      _lineOfSightFeedbacks = const [];
      _actorFacingByKind = {};
    });
    await Future.delayed(
      kDebugMode ? Duration.zero : const Duration(milliseconds: 200),
    );

    for (int i = 0; i < stopCount && i < goldPath.length; i++) {
      if (!mounted) return;
      await _runAction(goldPath[i], source: 'hint');
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
      final useThinking =
          s.googleThinkingEnabled &&
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
          .ollama(
            OllamaModel.supportsThinking(s.ollamaModel)
                ? (o) => o.reasoning(useThink)
                : null,
          )
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
      _selectedMultiCellObjectId = null;
      _lineOfSightFeedbacks = const [];
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
              child: Text(
                title,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            IconButton(
              icon: const Icon(Icons.copy, size: 18),
              tooltip: 'Copy',
              onPressed: () {
                Clipboard.setData(ClipboardData(text: text));
                ScaffoldMessenger.of(ctx).showSnackBar(
                  const SnackBar(
                    content: Text('Copied'),
                    duration: Duration(seconds: 1),
                  ),
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
                fontSize: 12,
                height: 1.5,
                fontFamily: 'monospace',
              ),
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
      'a': LogicalKeyboardKey.keyA,
      'b': LogicalKeyboardKey.keyB,
      'c': LogicalKeyboardKey.keyC,
      'd': LogicalKeyboardKey.keyD,
      'e': LogicalKeyboardKey.keyE,
      'f': LogicalKeyboardKey.keyF,
      'g': LogicalKeyboardKey.keyG,
      'h': LogicalKeyboardKey.keyH,
      'i': LogicalKeyboardKey.keyI,
      'j': LogicalKeyboardKey.keyJ,
      'k': LogicalKeyboardKey.keyK,
      'l': LogicalKeyboardKey.keyL,
      'm': LogicalKeyboardKey.keyM,
      'n': LogicalKeyboardKey.keyN,
      'o': LogicalKeyboardKey.keyO,
      'p': LogicalKeyboardKey.keyP,
      'q': LogicalKeyboardKey.keyQ,
      'r': LogicalKeyboardKey.keyR,
      's': LogicalKeyboardKey.keyS,
      't': LogicalKeyboardKey.keyT,
      'u': LogicalKeyboardKey.keyU,
      'v': LogicalKeyboardKey.keyV,
      'w': LogicalKeyboardKey.keyW,
      'x': LogicalKeyboardKey.keyX,
      'y': LogicalKeyboardKey.keyY,
      'z': LogicalKeyboardKey.keyZ,
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

    // Refresh the previews whenever the board or the avatar has actually
    // moved. Dry runs are cheap, but there is no reason to repeat them for
    // every rebuild, and none of them mean anything mid-animation.
    final showPreviews = _preAnimState == null && !_animating && !_aiRunning;
    if (showPreviews) {
      final avatarPos = _engine.state.avatar.position;
      final key =
          '$levelId:${_engine.state.turnCount}:'
          '${avatarPos?.x},${avatarPos?.y}';
      if (key != _actionPreviewKey) {
        _actionPreviewKey = key;
        _actionPreviews = _computeActionPreviews();
        _hoveredPreviewTarget = null;
      }
    }

    // Record win the first time it is detected (post-frame to avoid
    // calling async work inside a synchronous build call).
    if (state.isWon && !_wonHandled) {
      _wonHandled = true;
      _tracker.track('level_complete', level: levelId);
      if (widget.progress != null) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) widget.progress!.markCompleted(levelId);
        });
      }
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
                  color: Colors.black87,
                ),
              ),
            ),
            const SizedBox(width: 4),
            IconButton(
              icon: const Icon(
                Icons.info_outline,
                color: Colors.black45,
                size: 20,
              ),
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
              color: _nextIsLocked ? Colors.black26 : Colors.black54,
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
            LogicalKeyboardKey.keyW => 'up',
            LogicalKeyboardKey.keyS => 'down',
            LogicalKeyboardKey.keyA => 'left',
            LogicalKeyboardKey.keyD => 'right',
            _ => null,
          };
          if (dir == null || !_hasMoveAction) {
            return KeyEventResult.ignored;
          }
          if (_moveActionNeedsPosition) {
            final selectedPos = _selectedMovePosition();
            if (selectedPos == null) return KeyEventResult.ignored;
            _onAction(
              GameAction(_primaryMoveAction!.id, {
                'direction': dir,
                'position': [selectedPos.x, selectedPos.y],
              }),
            );
          } else {
            _onAction(GameAction(_primaryMoveAction!.id, {'direction': dir}));
          }
          return KeyEventResult.handled;
        },
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onPanStart: (_aiRunning || _animating) ? null : _onPanStart,
          onPanUpdate: (_aiRunning || _animating) ? null : _onPanUpdate,
          onPanEnd: (_aiRunning || _animating) ? null : _onPanEnd,
          onPanCancel: (_aiRunning || _animating) ? null : _onPanCancel,
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
                        key: _boardKey,
                        state: state,
                        game: widget.packService.game,
                        packService: widget.packService,
                        animationOverlays: _animOverlays,
                        actorFacingByKind: _actorFacingByKind,
                        onCellTap:
                            (_hasCellTapGesture || _moveActionNeedsPosition)
                            ? _onCellTap
                            : null,
                        selectedMultiCellObjectId:
                            _selectedMultiCellObjectForRenderer(state),
                        selectedActorPosition: _selectedActorPosition(state),
                        lineOfSightFeedbacks: _lineOfSightFeedbacks,
                        cellEffects: _cellEffects,
                        floodedColorOverride: _lastFloodColor,
                        avatarPositionOverride: _avatarSlidePos,
                        actionPreviews: showPreviews
                            ? _actionPreviews
                            : const {},
                        hoveredPreviewTarget: _hoveredPreviewTarget,
                        movingSprites: _movingSprites,
                        history: _engine.history,
                        movingMultiCellObjects: _movingMultiCellObjects,
                        onCellHover: (x, y) {
                          final pos = x == null || y == null
                              ? null
                              : Position(x, y);
                          if (pos == _hoveredPreviewTarget) return;
                          if (pos != null &&
                              !_actionPreviews.containsKey(pos)) {
                            if (_hoveredPreviewTarget == null) return;
                            setState(() => _hoveredPreviewTarget = null);
                            return;
                          }
                          setState(() => _hoveredPreviewTarget = pos);
                        },
                      ),
                    ),
                  ),
                ),
                if (state.isWon) _buildWinBanner(),
                if (state.isLost) _buildLossBanner(),
                if (s.aiPlayEnabled &&
                    !state.isWon &&
                    !state.isLost &&
                    _aiRunning)
                  _buildAiPanel(),
                if (s.aiPlayEnabled &&
                    !state.isWon &&
                    !state.isLost &&
                    !_aiRunning)
                  _buildAiStartButton(),
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
                    palette: widget.packService.theme?.palette,
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
    final readouts = ui.readouts
        .where((r) => state.variables.containsKey(r.variable))
        .toList();

    if (!showGoal && !showGuide && readouts.isEmpty) {
      return const SizedBox.shrink();
    }

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 2, 16, 4),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (readouts.isNotEmpty) ...[
            _buildReadoutStrip(state, readouts),
            if (showGoal || showGuide) const SizedBox(height: 6),
          ],
          if (showGoal || showGuide)
            IntrinsicHeight(
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
        ],
      ),
    );
  }

  /// A row of live `state.variables` chips declared by `game.json`'s
  /// `ui.readouts`. Pack-agnostic: the app never learns what a given variable
  /// means, only how to draw a labelled number.
  Widget _buildReadoutStrip(LevelState state, List<GameReadout> readouts) {
    return Wrap(
      spacing: 8,
      runSpacing: 6,
      alignment: WrapAlignment.center,
      children: [
        for (final r in readouts)
          _buildReadoutChip(r, state.variables[r.variable]),
      ],
    );
  }

  Widget _buildReadoutChip(GameReadout readout, Object? rawValue) {
    final number = (rawValue is num) ? rawValue.toInt() : null;
    final blank = number == null || number == readout.blankWhen;
    final tint = readout.color == null
        ? Theme.of(context).colorScheme.primary
        : cellNamedColor(
            readout.color!,
            palette: widget.packService.theme?.palette,
          );

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: tint.withValues(alpha: 0.14),
        border: Border.all(color: tint.withValues(alpha: 0.55)),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 10,
            height: 10,
            decoration: BoxDecoration(shape: BoxShape.circle, color: tint),
          ),
          const SizedBox(width: 8),
          Text(
            readout.label,
            style: TextStyle(
              fontSize: 12,
              color: Colors.grey.shade700,
              fontWeight: FontWeight.w500,
            ),
          ),
          const SizedBox(width: 8),
          Text(
            blank ? '—' : '$number',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.bold,
              fontFeatures: const [FontFeature.tabularFigures()],
              color: tint,
            ),
          ),
        ],
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
          Row(
            children: [
              Icon(Icons.flag_outlined, color: Colors.green.shade600, size: 14),
              const SizedBox(width: 4),
              Text(
                'Goal',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                  color: Colors.grey.shade700,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          _buildGoalContent(state),
        ],
      ),
    );
  }

  Widget _buildGoalContent(LevelState state) {
    // Sum and count constraint goals are rendered together (rows + cols in one view).
    final constraintGoals = _levelDef.goals
        .where(
          (g) => g.type == 'sum_constraint' || g.type == 'count_constraint',
        )
        .toList();
    if (constraintGoals.isNotEmpty)
      return _buildConstraintGoals(constraintGoals, state);

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
    }

    // Every goal, not just the first: a level won on two conditions at once
    // reads as the wrong puzzle when only one of them is named.
    final descriptions = widget.packService.game.goalDescriptions;
    final showPreview = widget.packService.game.ui.showGoalPreview;
    Map<String, dynamic>? preview;
    final lines = <String>[];
    for (final goal in _levelDef.goals) {
      final targetLayers = goal.config['targetLayers'] as Map<String, dynamic>?;
      // Only the goal actually drawn is left out of the text; a second
      // `board_match` has nowhere to go, so it is named instead.
      if (goal.type == 'board_match' &&
          showPreview &&
          targetLayers != null &&
          preview == null) {
        preview = targetLayers;
        continue;
      }
      lines.add(descriptions[goal.id] ?? goal.type.replaceAll('_', ' '));
    }

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (preview != null)
          Center(
            child: TargetBoardRenderer(
              targetLayers: preview,
              currentState: state,
              palette: widget.packService.theme?.palette,
            ),
          ),
        if (preview != null && lines.isNotEmpty) const SizedBox(height: 6),
        for (final line in lines)
          Padding(
            padding: const EdgeInsets.only(bottom: 2),
            child: Text(line, style: const TextStyle(fontSize: 12)),
          ),
      ],
    );
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
              child: Icon(
                Icons.arrow_forward,
                size: 12,
                color: Colors.grey.shade500,
              ),
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
    final rowCheckers =
        <int, List<(String Function(int y), bool Function(int y))>>{};
    final colCheckers =
        <int, List<(String Function(int x), bool Function(int x))>>{};
    final descriptions = <String>[];

    for (final goal in goals) {
      final scope = (goal.config['scope'] as String?) ?? 'board';
      final target = goal.config['target'] as num;
      final cmp = (goal.config['comparison'] as String?) ?? 'eq';
      final op = switch (cmp) {
        'gte' => '≥',
        'lte' => '≤',
        _ => '=',
      };
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
          if (predicate.startsWith('gte_'))
            return value >= int.parse(predicate.substring(4));
          if (predicate.startsWith('lte_'))
            return value <= int.parse(predicate.substring(4));
          if (predicate.startsWith('eq_'))
            return value == int.parse(predicate.substring(3));
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
        child: Text(
          '$val',
          style: TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.bold,
            color: Colors.grey.shade800,
          ),
        ),
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
          child: Text(
            label,
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.bold,
              color: color,
            ),
          ),
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
            fontStyle: FontStyle.italic,
          ),
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
          Row(
            children: [
              Icon(Icons.info_outline, color: Colors.blue.shade600, size: 14),
              const SizedBox(width: 4),
              Text(
                'Guide',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                  color: Colors.blue.shade700,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            _levelDef.guide!,
            style: TextStyle(
              fontSize: 11,
              color: Colors.blue.shade900,
              height: 1.4,
            ),
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
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                  child: const Text(
                    "Let's go!",
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                  ),
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

  String? _selectedActorBudgetLabel(LevelState state) {
    final config = _individualActorSystem?.config;
    if (config == null) return null;
    final selectedKey =
        config['selectedVariable'] as String? ?? 'selectedActorKind';
    final budgetKey =
        config['budgetVariable'] as String? ?? 'actorMovesRemaining';
    final selectedKind = state.variables[selectedKey] as String?;
    final remaining = state.variables[budgetKey];
    if (selectedKind == null || remaining is! Map) return null;
    final value = remaining[selectedKind];
    if (value is! num) return null;

    final name =
        widget.packService.game.entityKinds[selectedKind]?.uiName ??
        selectedKind;
    final count = value.toInt();
    return '$name: $count ${count == 1 ? 'move' : 'moves'}';
  }

  bool _selectedActorBudgetExhausted(LevelState state) {
    final config = _individualActorSystem?.config;
    if (config == null) return false;
    final selectedKey =
        config['selectedVariable'] as String? ?? 'selectedActorKind';
    final budgetKey =
        config['budgetVariable'] as String? ?? 'actorMovesRemaining';
    final selectedKind = state.variables[selectedKey] as String?;
    final remaining = state.variables[budgetKey];
    if (selectedKind == null || remaining is! Map) return false;
    final value = remaining[selectedKind];
    return value is num && value <= 0;
  }

  Position? _selectedActorPosition(LevelState state) {
    final config = _individualActorSystem?.config;
    if (config == null) return null;
    final positionKey =
        config['selectedPositionVariable'] as String? ??
        'selectedActorPosition';
    return _positionFromPayload(state.variables[positionKey]);
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
    final selectedBudgetLabel = _selectedActorBudgetLabel(state);
    final selectedBudgetExhausted = _selectedActorBudgetExhausted(state);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      child: Row(
        children: [
          Text(
            '${_levelIndex + 1}/${_levelIds.length}',
            style: TextStyle(color: Colors.grey.shade600, fontSize: 13),
          ),
          const Spacer(),
          if (_aiRunning) ...[
            Text(
              'Attempt: $_agentAttempt',
              style: TextStyle(color: Colors.grey.shade600, fontSize: 13),
            ),
            const SizedBox(width: 12),
          ],
          if (selectedBudgetLabel != null) ...[
            Flexible(
              child: Text(
                selectedBudgetLabel,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: selectedBudgetExhausted
                      ? Colors.red.shade600
                      : Colors.grey.shade600,
                  fontSize: 13,
                  fontWeight: selectedBudgetExhausted
                      ? FontWeight.bold
                      : FontWeight.normal,
                ),
              ),
            ),
            const SizedBox(width: 12),
          ],
          Text(
            _movesLabel(state),
            style: TextStyle(
              color: state.isLost ? Colors.red.shade600 : Colors.grey.shade600,
              fontSize: 13,
              fontWeight: state.isLost ? FontWeight.bold : FontWeight.normal,
            ),
          ),
          const SizedBox(width: 4),
          GestureDetector(
            onTap: () {
              final boardText = TextRenderer.render(
                state,
                widget.packService.game,
              );
              final moves = _engine.actionHistory
                  .map(_actionShorthand)
                  .join('');
              final text = moves.isEmpty
                  ? boardText
                  : '$boardText\nMoves: $moves';
              Clipboard.setData(ClipboardData(text: text));
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('Grid + moves copied to clipboard'),
                  duration: Duration(seconds: 1),
                ),
              );
            },
            child: Icon(
              Icons.content_copy,
              size: 14,
              color: Colors.grey.shade400,
            ),
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
          const Text(
            'Level Complete!',
            style: TextStyle(
              color: Colors.white,
              fontSize: 20,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              ElevatedButton(
                onPressed: _onReset,
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.white,
                  foregroundColor: Colors.green.shade700,
                ),
                child: const Text('Replay'),
              ),
              const SizedBox(width: 12),
              ElevatedButton(
                onPressed: _advance,
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.white,
                  foregroundColor: Colors.green.shade700,
                ),
                child: const Text('Next Level'),
              ),
            ],
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
          const Text(
            'Out of Moves!',
            style: TextStyle(
              color: Colors.white,
              fontSize: 20,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 4),
          const Text(
            'Plan the order more carefully.',
            style: TextStyle(color: Colors.white70, fontSize: 13),
          ),
          const SizedBox(height: 10),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              ElevatedButton(
                onPressed: _onReset,
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.white,
                  foregroundColor: Colors.red.shade700,
                ),
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
            message:
                'AI play requires the native app (browser security restricts API calls)',
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
              Icon(
                Icons.smart_toy_outlined,
                size: 16,
                color: Colors.indigo.shade400,
              ),
              const SizedBox(width: 6),
              Text(
                isStep
                    ? (isPaused ? 'AI ready' : 'AI thinking…')
                    : 'AI playing…',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: Colors.indigo.shade700,
                ),
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
                  style: TextButton.styleFrom(
                    foregroundColor: Colors.grey.shade700,
                  ),
                  onPressed: _stopAgent,
                ),
                TextButton.icon(
                  icon: const Icon(Icons.skip_next, size: 18),
                  label: Text(
                    s.inferenceMode == 'single'
                        ? 'Infer Action'
                        : 'Infer Actions',
                  ),
                  onPressed: _stepAgent,
                ),
              ] else ...[
                TextButton.icon(
                  icon: const Icon(Icons.person_outline, size: 18),
                  label: const Text('Take over'),
                  style: TextButton.styleFrom(
                    foregroundColor: Colors.grey.shade700,
                  ),
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
      fontSize: 12,
      color: Colors.indigo.shade800,
      height: 1.4,
    );
    final monoStyle = baseStyle.copyWith(fontFamily: 'Courier');

    final spans = <TextSpan>[];
    for (int i = 0; i < parts.length; i++) {
      if (parts[i].isEmpty) continue;
      spans.add(
        TextSpan(text: parts[i], style: i.isOdd ? monoStyle : baseStyle),
      );
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
        child: Text(
          label,
          style: TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w600,
            color: Colors.grey.shade600,
            fontFamily: 'monospace',
          ),
        ),
      ),
    );
  }
}
