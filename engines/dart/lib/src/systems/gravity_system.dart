import '../engine/game_system.dart';
import '../models/board.dart';
import '../models/direction.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// Rigid multi-cell objects with a configured role fall until they rest.
///
/// Objects whose `params.role` is in `fallRoles` translate one cell at a time
/// in `direction` until a cell of the object would leave the board, enter void
/// or invalid ground, overlap another multi-cell object, or hit a blocking
/// entity. Objects fall front-most first, so a stack settles bottom-up.
///
/// `groundTagVariables` additionally publishes, once per turn, how many
/// objects of a role currently stand on tagged ground — a derived readout for
/// "the object reached the target zone" goals and "the object reached the
/// danger zone" lose conditions.
class GravitySystem extends GameSystem {
  final Map<String, dynamic>? config;

  const GravitySystem({required super.id, this.config})
      : super(type: 'gravity');

  @override
  List<GameEvent> executeCascadeResolution(
    List<GameEvent> triggerEvents,
    LevelState state,
    GameDefinition game,
  ) {
    final cfg = config ?? game.systemConfig(id, {});
    final triggers =
        (cfg['triggerEvents'] as List? ?? ['multi_cell_object_moved'])
            .map((v) => v.toString())
            .toSet();
    if (!triggerEvents.any((e) => triggers.contains(e.type))) return const [];
    return _settle(state, game, cfg, full: false);
  }

  @override
  List<GameEvent> executeLoadSettle(LevelState state, GameDefinition game) {
    final cfg = config ?? game.systemConfig(id, {});
    return _settle(state, game, cfg, full: true);
  }

  @override
  void executeDeriveState(LevelState state, GameDefinition game) {
    final cfg = config ?? game.systemConfig(id, {});
    final specs = cfg['groundTagVariables'] as List? ?? const [];
    final groundLayer = cfg['groundLayer'] as String? ?? 'ground';
    for (final raw in specs) {
      final spec = (raw as Map).cast<String, dynamic>();
      final role = spec['role']?.toString();
      final tag = spec['groundTag']?.toString();
      final variable = spec['variable']?.toString();
      if (role == null || tag == null || variable == null) continue;
      var count = 0;
      for (final obj in state.board.multiCellObjects) {
        if (obj.params['role']?.toString() != role) continue;
        final standing = obj.cells.any((cell) {
          final ground = state.board.getEntity(groundLayer, cell);
          return ground != null && game.hasTag(ground.kind, tag);
        });
        if (standing) count++;
      }
      state.variables[variable] = count;
    }
  }

  /// With `stepsPerPass` set (and [full] false) objects fall that many cells
  /// per cascade pass instead of all the way, so other systems — `pounce` —
  /// get to look at every intermediate board. Objects that moved this pass are
  /// not yet at rest, so `absorb` skips them; they are absorbed on the pass
  /// after their last step. Level load always settles fully.
  List<GameEvent> _settle(
      LevelState state, GameDefinition game, Map<String, dynamic> cfg,
      {required bool full}) {
    final fallRoles = (cfg['fallRoles'] as List? ?? const [])
        .map((v) => v.toString())
        .toSet();
    if (fallRoles.isEmpty) return const [];
    final stepLimit = full ? 0 : (cfg['stepsPerPass'] as num?)?.toInt() ?? 0;
    final movedIds = <String>{};
    final events = _fall(state, game, cfg, fallRoles, stepLimit, movedIds);
    events
        .addAll(_absorb(state, game, cfg, stepLimit > 0 ? movedIds : const {}));
    return events;
  }

  List<GameEvent> _fall(
      LevelState state,
      GameDefinition game,
      Map<String, dynamic> cfg,
      Set<String> fallRoles,
      int stepLimit,
      Set<String> movedIds) {
    final directionName = cfg['direction'] as String? ?? 'down';
    final direction = Direction.fromJson(directionName);
    final offset = direction.offset;

    final fallers = state.board.multiCellObjects
        .where((o) => fallRoles.contains(o.params['role']?.toString()))
        .toList();
    if (fallers.isEmpty) return <GameEvent>[];

    // Front-most (furthest along the fall direction) first, id as tiebreak.
    int lead(MultiCellObjectInstance o) => o.cells
        .map((p) => p.x * offset.x + p.y * offset.y)
        .reduce((a, b) => a > b ? a : b);
    fallers.sort((a, b) {
      final byLead = lead(b).compareTo(lead(a));
      return byLead != 0 ? byLead : a.id.compareTo(b.id);
    });

    final origin = {for (final o in fallers) o.id: o.cells.toList()};
    var moved = true;
    var steps = 0;
    while (moved && (stepLimit == 0 || steps < stepLimit)) {
      moved = false;
      steps++;
      for (final obj in fallers) {
        final next = obj.cells.map((p) => p + offset).toList();
        if (next.every((p) => _canOccupy(p, obj, state, game, cfg))) {
          _translate(obj, next);
          movedIds.add(obj.id);
          moved = true;
        }
      }
    }

    final events = <GameEvent>[];
    for (final obj in fallers) {
      final from = origin[obj.id]!;
      if (_sameCells(from, obj.cells)) continue;
      events.add(GameEvent('multi_cell_object_moved', {
        'id': obj.id,
        'kind': obj.kind,
        'fromCells': from,
        'toCells': obj.cells.toList(),
        'direction': directionName,
      }));
    }
    return events;
  }

  /// Objects resting on `absorb` ground are consumed by it: the object is
  /// removed, the ground cell may change kind (optionally playing one of the
  /// old ground kind's animations) and a counter variable goes up.
  List<GameEvent> _absorb(LevelState state, GameDefinition game,
      Map<String, dynamic> cfg, Set<String> stillMoving) {
    final specs = cfg['absorb'] as List? ?? const [];
    final groundLayer = cfg['groundLayer'] as String? ?? 'ground';
    final events = <GameEvent>[];
    for (final raw in specs) {
      final spec = (raw as Map).cast<String, dynamic>();
      final role = spec['role']?.toString();
      final tag = spec['groundTag']?.toString();
      if (role == null || tag == null) continue;
      final toKind = spec['toGroundKind']?.toString();
      final animation = spec['animation']?.toString();
      final variable = spec['variable']?.toString();
      for (final obj in state.board.multiCellObjects.toList()) {
        if (obj.params['role']?.toString() != role) continue;
        if (stillMoving.contains(obj.id)) continue;
        Position? at;
        for (final cell in obj.cells) {
          final ground = state.board.getEntity(groundLayer, cell);
          if (ground != null && game.hasTag(ground.kind, tag)) {
            at = cell;
            break;
          }
        }
        if (at == null) continue;
        state.board.multiCellObjects.removeWhere((m) => m.id == obj.id);
        final oldKind = state.board.getEntity(groundLayer, at)!.kind;
        events.add(GameEvent('multi_cell_object_absorbed', {
          'id': obj.id,
          'kind': obj.kind,
          'position': at,
        }));
        if (toKind != null && toKind != oldKind) {
          state.board.setEntity(groundLayer, at, EntityInstance(toKind));
          events
              .add(GameEvent.cellTransformed(at, oldKind, toKind, groundLayer));
        }
        if (animation != null) {
          events.add(GameEvent.objectRemovedAnimated(at, oldKind, animation));
        }
        if (variable != null) {
          final oldValue = (state.variables[variable] as num?) ?? 0;
          state.variables[variable] = oldValue + 1;
          events
              .add(GameEvent.variableChanged(variable, oldValue, oldValue + 1));
        }
      }
    }
    return events;
  }

  bool _canOccupy(Position pos, MultiCellObjectInstance obj, LevelState state,
      GameDefinition game, Map<String, dynamic> cfg) {
    if (!state.board.isInBounds(pos) || state.board.isVoid(pos)) return false;

    final groundLayer = cfg['groundLayer'] as String? ?? 'ground';
    final ground = state.board.getEntity(groundLayer, pos);
    final validGroundTags = (cfg['validGroundTags'] as List? ?? ['walkable'])
        .map((v) => v.toString())
        .toList();
    if (ground == null ||
        !validGroundTags.any((tag) => game.hasTag(ground.kind, tag))) {
      return false;
    }

    for (final other in state.board.multiCellObjects) {
      if (other.id == obj.id) continue;
      if (other.cells.contains(pos)) return false;
    }

    final blockingLayers = (cfg['blockingLayers'] as List? ?? ['objects'])
        .map((v) => v.toString());
    final blockingTags = (cfg['blockingTags'] as List? ?? ['solid'])
        .map((v) => v.toString())
        .toList();
    for (final layerId in blockingLayers) {
      final entity = state.board.getEntity(layerId, pos);
      if (entity == null) continue;
      if (obj.cells.contains(pos)) continue;
      if (blockingTags.isEmpty ||
          blockingTags.any((tag) => game.hasTag(entity.kind, tag))) {
        return false;
      }
    }
    return true;
  }

  void _translate(MultiCellObjectInstance obj, List<Position> next) {
    final oldCells = obj.cells.toList();
    obj.cells
      ..clear()
      ..addAll(next);
    if (obj.cellSprites.isEmpty) return;
    final oldSprites = Map<Position, String>.from(obj.cellSprites);
    obj.cellSprites.clear();
    for (var i = 0; i < oldCells.length; i++) {
      final sprite = oldSprites[oldCells[i]];
      if (sprite != null) obj.cellSprites[next[i]] = sprite;
    }
  }

  bool _sameCells(List<Position> a, List<Position> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }
}
