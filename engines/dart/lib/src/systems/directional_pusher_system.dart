import '../engine/game_system.dart';
import '../models/condition.dart';
import '../models/direction.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';
import '../rules/condition_evaluator.dart';
import 'avatar_navigation_system.dart' show predictNpcStep;

/// Shoves the avatar along a pusher's fixed direction. See
/// docs/dsl/04_systems.md §2.27.
///
/// A pusher is a board entity with a baked-in direction. When the avatar
/// arrives, this turn, on the single cell the pusher points at (the first cell
/// in its direction, never any other), the avatar is shoved on in that
/// direction until the next cell is blocked, stopping one cell short of the
/// blocker.
///
/// Runs in movement resolution, after the avatar's own step, and fires at most
/// once per turn — the slide never re-triggers another pusher, since this
/// phase does not re-run on the events the slide itself emits.
class DirectionalPusherSystem extends GameSystem {
  const DirectionalPusherSystem({required super.id})
      : super(type: 'directional_pusher');

  // Fixed probe order, so a cell targeted by several pushers resolves the same
  // way in both engines.
  static const _probeOrder = ['up', 'down', 'left', 'right'];

  @override
  List<GameEvent> executeMovementResolution(
      LevelState state, GameDefinition game) {
    final avatar = state.avatar;
    final pos = avatar.position;
    final start = state.avatarPositionAtTurnStart;
    if (!avatar.enabled || pos == null || start == null || pos == start) {
      return const [];
    }

    final config = game.systemConfig(id, null);
    final pusherLayer = config['pusherLayer'] as String? ?? 'objects';
    final pusherTag = config['pusherTag'] as String? ?? 'pusher';
    final directionParam = config['directionParam'] as String? ?? 'direction';

    final found = _findPusher(
        state, game, pos, pusherLayer, pusherTag, directionParam);
    if (found == null) return const [];
    final (pusherPos, dirStr) = found;

    // The condition sees the step that landed on the trigger cell, so it can
    // use the same grammar (and event fields) as a rule's `if`.
    final conditionJson = config['condition'];
    if (conditionJson is Map) {
      final condition =
          Condition.fromJson(Map<String, dynamic>.from(conditionJson));
      final stepEvent = GameEvent.avatarEntered(pos, start, dirStr);
      if (!ConditionEvaluator().evaluate(condition, stepEvent, state, game)) {
        return const [];
      }
    }

    final stopLayers = (config['stopLayers'] as List? ?? const ['objects'])
        .map((l) => l.toString())
        .toList();
    final crashLayers = (config['crashLayers'] as List? ?? const [])
        .map((l) => l.toString())
        .toList();
    final crashVariable = config['crashVariable'] as String? ?? 'caught';
    final groundLayer = config['groundLayer'] as String? ?? 'ground';
    final validGroundTags =
        (config['validGroundTags'] as List? ?? const ['walkable'])
            .map((t) => t.toString())
            .toList();

    final direction = Direction.fromJson(dirStr);
    final board = state.board;
    final hazards = _hazards(state, game, crashLayers);
    final events = <GameEvent>[];
    GameEvent? crashEvent;
    var current = pos;
    while (true) {
      final next = current.moved(direction);
      if (!board.isInBounds(next) || board.isVoid(next)) break;
      if (validGroundTags.isNotEmpty) {
        final ground = board.getEntity(groundLayer, next);
        if (ground == null ||
            !validGroundTags.any((t) => game.hasTag(ground.kind, t))) {
          break;
        }
      }
      if (stopLayers.any((l) => board.getEntity(l, next) != null)) break;
      // One enter/exit pair per cell crossed, like ice_slide, so the renderer
      // can walk the slide cell by cell.
      events.add(GameEvent.avatarExited(current));
      events.add(GameEvent.avatarEntered(next, current, dirStr));
      final prev = current;
      current = next;

      // Hazards move in the same turn as the slide, so they are met where
      // they will be, not where they were: a hazard leaving this cell lets
      // the slide through; one arriving at, staying on, or crossing head-on
      // through it ends the slide here in a crash.
      final hit = hazards
          .where((h) => h.next == next || (h.pos == next && h.next == prev))
          .firstOrNull;
      if (hit != null) {
        // A hazard stepping onto the avatar's final cell is already reported
        // by its own system's contact check; only the cases it can't see
        // (standing still, or crossing through) are recorded here, so a
        // crash is never counted twice.
        if (hit.next == hit.pos || hit.next == prev) {
          final previous = state.variables[crashVariable];
          state.variables[crashVariable] =
              (previous is num ? previous.toInt() : 0) + 1;
          crashEvent = GameEvent('avatar_caught', {
            'position': next,
            'npcKind': hit.entity.kind,
            'npcId': hit.entity.param('id'),
          });
        }
        break;
      }
    }

    if (current == pos) return const [];

    state.avatar = avatar.copyWith(position: current, facing: direction);
    events.add(GameEvent('avatar_pushed', {
      'position': current,
      'fromPosition': pos,
      'pusherPosition': pusherPos,
      'direction': dirStr,
      'distance': (current.x - pos.x).abs() + (current.y - pos.y).abs(),
    }));
    if (crashEvent != null) events.add(crashEvent);
    return events;
  }

  /// Every crash-layer entity with its position now and where it will be
  /// after this turn's NPC resolution. An entity whose step can't be
  /// predicted is assumed to stay put.
  static List<({Position pos, EntityInstance entity, Position next})> _hazards(
      LevelState state, GameDefinition game, List<String> crashLayers) {
    final out = <({Position pos, EntityInstance entity, Position next})>[];
    for (final layerId in crashLayers) {
      final layer = state.board.layers[layerId];
      if (layer == null) continue;
      for (final entry in layer.entries()) {
        final next = predictNpcStep(entry.value, entry.key, state, game);
        out.add((pos: entry.key, entity: entry.value, next: next ?? entry.key));
      }
    }
    return out;
  }

  /// The pusher whose front cell is [pos], if any: a pusher facing `d` must
  /// sit exactly one cell behind [pos] (at pos - d).
  static (Position, String)? _findPusher(
    LevelState state,
    GameDefinition game,
    Position pos,
    String pusherLayer,
    String pusherTag,
    String directionParam,
  ) {
    for (final dirStr in _probeOrder) {
      final offset = Direction.fromJson(dirStr).offset;
      final behind = Position(pos.x - offset.x, pos.y - offset.y);
      if (!state.board.isInBounds(behind)) continue;
      final entity = state.board.getEntity(pusherLayer, behind);
      if (entity == null || !game.hasTag(entity.kind, pusherTag)) continue;
      if (entity.param(directionParam) == dirStr) return (behind, dirStr);
    }
    return null;
  }
}
