import '../engine/game_system.dart';
import '../models/board.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// Hunters run down a clear line to prey and capture it.
///
/// After the board has settled, every object whose `role` is in `hunterRoles`
/// looks along each of `directions` for the nearest object whose role is in
/// `preyRoles`. If nothing stands between them — no other multi-cell object, no
/// void, no blocking entity — the hunter travels to the prey's cell and the
/// prey is removed. Distance is unlimited; only an obstruction stops a hunter.
/// Place this system after `gravity` so objects have come to rest first.
class PounceSystem extends GameSystem {
  final Map<String, dynamic>? config;

  const PounceSystem({required super.id, this.config}) : super(type: 'pounce');

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
    return _hunt(state, game, cfg);
  }

  List<GameEvent> _hunt(
      LevelState state, GameDefinition game, Map<String, dynamic> cfg) {
    final hunterRoles = _strings(cfg['hunterRoles']);
    final preyRoles = _strings(cfg['preyRoles']);
    if (hunterRoles.isEmpty || preyRoles.isEmpty) return const [];
    final directions = (cfg['directions'] as List? ?? ['left', 'right'])
        .map((v) => v.toString())
        .toSet();
    final variable = cfg['variable']?.toString();
    final events = <GameEvent>[];

    var captured = true;
    while (captured) {
      captured = false;
      final hunters = state.board.multiCellObjects
          .where((o) => hunterRoles.contains(o.params['role']?.toString()))
          .toList()
        ..sort((a, b) => a.id.compareTo(b.id));
      for (final hunter in hunters) {
        final prey =
            _nearestPrey(hunter, preyRoles, directions, state, game, cfg);
        if (prey == null) continue;
        final from = hunter.cells.toList();
        final target = prey.cells.first;
        final dx = target.x - hunter.cells.first.x;
        final to = [for (final c in from) Position(c.x + dx, c.y)];
        state.board.multiCellObjects.removeWhere((m) => m.id == prey.id);
        hunter.cells
          ..clear()
          ..addAll(to);
        if (hunter.cellSprites.isNotEmpty) {
          final old = Map<Position, String>.from(hunter.cellSprites);
          hunter.cellSprites.clear();
          for (var i = 0; i < from.length; i++) {
            final sprite = old[from[i]];
            if (sprite != null) hunter.cellSprites[to[i]] = sprite;
          }
        }
        events.add(GameEvent('multi_cell_object_moved', {
          'id': hunter.id,
          'kind': hunter.kind,
          'fromCells': from,
          'toCells': to,
          'direction': dx < 0 ? 'left' : 'right',
        }));
        events.add(GameEvent('multi_cell_object_captured', {
          'id': prey.id,
          'kind': prey.kind,
          'hunterId': hunter.id,
          'position': target,
        }));
        if (variable != null) {
          final oldValue = (state.variables[variable] as num?) ?? 0;
          state.variables[variable] = oldValue + 1;
          events
              .add(GameEvent.variableChanged(variable, oldValue, oldValue + 1));
        }
        captured = true;
        break; // board changed: re-scan from scratch
      }
    }
    return events;
  }

  MultiCellObjectInstance? _nearestPrey(
    MultiCellObjectInstance hunter,
    Set<String> preyRoles,
    Set<String> directions,
    LevelState state,
    GameDefinition game,
    Map<String, dynamic> cfg,
  ) {
    final origin = hunter.cells.first;
    MultiCellObjectInstance? best;
    var bestDistance = 1 << 30;
    for (final dir in const [('left', -1), ('right', 1)]) {
      if (!directions.contains(dir.$1)) continue;
      var x = origin.x + dir.$2;
      while (state.board.isInBounds(Position(x, origin.y))) {
        final pos = Position(x, origin.y);
        if (state.board.isVoid(pos)) break;
        final here = state.board.multiCellObjects
            .where((o) => o.id != hunter.id && o.cells.contains(pos))
            .toList();
        if (here.isNotEmpty) {
          final o = here.first;
          final distance = (x - origin.x).abs();
          if (preyRoles.contains(o.params['role']?.toString()) &&
              distance < bestDistance) {
            best = o;
            bestDistance = distance;
          }
          break; // any object ends the line of sight
        }
        if (_blockedByEntity(pos, state, game, cfg)) break;
        x += dir.$2;
      }
    }
    return best;
  }

  bool _blockedByEntity(Position pos, LevelState state, GameDefinition game,
      Map<String, dynamic> cfg) {
    final layers = (cfg['blockingLayers'] as List? ?? ['objects'])
        .map((v) => v.toString());
    final tags = (cfg['blockingTags'] as List? ?? ['solid'])
        .map((v) => v.toString())
        .toList();
    for (final layerId in layers) {
      final entity = state.board.getEntity(layerId, pos);
      if (entity == null) continue;
      if (tags.isEmpty || tags.any((t) => game.hasTag(entity.kind, t))) {
        return true;
      }
    }
    return false;
  }

  Set<String> _strings(dynamic raw) =>
      (raw as List? ?? const []).map((v) => v.toString()).toSet();
}
