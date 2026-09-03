import '../engine/game_system.dart';
import '../models/board.dart';
import '../models/entity.dart';
import '../models/direction.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// When an actor steps onto a cell tagged [terrainTag], it is immediately
/// transported to the first non-terrain cell beyond the far edge of that
/// contiguous terrain region in the direction of travel.
///
/// If the exit cell is blocked (rock, OOB, occupied), the actor is bounced
/// back to the cell it entered from (fromPosition in the event) — no trail
/// or budget changes apply in either case.
class TerrainSkipSystem extends GameSystem {
  const TerrainSkipSystem({required super.id}) : super(type: 'terrain_skip');

  @override
  List<GameEvent> executeCascadeResolution(
    List<GameEvent> triggerEvents,
    LevelState state,
    GameDefinition game,
  ) {
    final cfg = _config(game);
    final actorLayerId = cfg.actorLayer;
    if (actorLayerId == null) return const [];

    final actorLayer = state.board.layers[actorLayerId];
    if (actorLayer == null) return const [];

    for (final e in triggerEvents) {
      if (e.type != 'actor_entered') continue;

      final enteredRaw = e.payload['position'];
      if (enteredRaw == null) continue;
      final enteredPos = enteredRaw is Position
          ? enteredRaw
          : Position.fromJson(enteredRaw);

      // Actor must still be at the entered position (not moved by an earlier system).
      final actor = state.board.getEntity(actorLayerId, enteredPos);
      if (actor == null) continue;

      // Skip terrain transport for excluded actor kinds.
      final actorKindEarly = e.payload['kind'] as String? ?? actor.kind;
      if (cfg.excludeActorKinds.contains(actorKindEarly)) continue;

      // Entry cell must carry the terrain tag.
      final ground = state.board.getEntity(cfg.groundLayer, enteredPos);
      if (ground == null || !game.hasTag(ground.kind, cfg.terrainTag)) continue;

      // Direction the actor was travelling when it entered the terrain.
      final dirStr = e.payload['direction'] as String?;
      if (dirStr == null) continue;
      final direction = Direction.fromJson(dirStr);

      // Walk forward through contiguous terrain to find the far edge.
      var scan = enteredPos;
      while (true) {
        final next = scan.moved(direction);
        if (!state.board.isInBounds(next)) break;
        final nextGround = state.board.getEntity(cfg.groundLayer, next);
        if (nextGround == null || !game.hasTag(nextGround.kind, cfg.terrainTag)) break;
        scan = next;
      }

      // Exit = one step beyond the last terrain cell.
      final exitPos = scan.moved(direction);

      bool exitValid = _validateLanding(
          state, game, exitPos, cfg.groundLayer, actorLayerId, cfg.exitBlockLayers);

      // If the water-crossing exit lands directly on a portal, chain through
      // to its paired exit. A silent relocation like this never emits an
      // actor_entered event, so the portals system — which only reacts to
      // that event — can never see the landing and would otherwise leave the
      // actor stranded on the portal tile. Landing on the *near* side of a
      // portal via a normal move already works today because that step is a
      // real actor_entered event.
      //
      // The chained destination gets exactly the same validation as the
      // direct exit: it's reached by a jump nothing else has checked, so an
      // occupied/blocked/out-of-bounds paired exit must bounce the actor
      // back too, not silently overwrite whatever is already there.
      var finalPos = exitPos;
      if (exitValid) {
        final chained = _chainedPortalExit(state.board, exitPos, cfg.exitPortal, game);
        if (chained != null) {
          if (_validateLanding(
              state, game, chained, cfg.groundLayer, actorLayerId, cfg.exitBlockLayers)) {
            finalPos = chained;
          } else {
            exitValid = false;
          }
        }
      }

      if (!exitValid) {
        // Bounce back: return actor to the cell it came from.
        final fromRaw = e.payload['fromPosition'];
        if (fromRaw != null) {
          final fromPos = fromRaw is Position
              ? fromRaw
              : Position.fromJson(fromRaw);
          state.board.setEntity(actorLayerId, enteredPos, null);
          state.board.setEntity(actorLayerId, fromPos, actor);
          final posVar = cfg.actorPositionVariable;
          if (posVar != null) {
            state.variables[posVar] = [fromPos.x, fromPos.y];
          }
        }
        break;
      }

      // Clear actor trail and accumulate freed cells into budget.
      final actorKind = e.payload['kind'] as String? ?? actor.kind;
      _clearActorTrail(state, cfg, actorKind);

      // Relocate actor silently — no new events, so leave_trail / budget rules
      // do not fire a second time.
      state.board.setEntity(actorLayerId, enteredPos, null);
      state.board.setEntity(actorLayerId, finalPos, actor);
      final posVar = cfg.actorPositionVariable;
      if (posVar != null) {
        state.variables[posVar] = [finalPos.x, finalPos.y];
      }

      // Check exit cell for hazards and set kill variables directly.
      // No actor_entered event is emitted for the transit, so rules cannot
      // detect landing on a hazard — we handle it inline here.
      for (final hazardCheck in cfg.exitHazardLayers) {
        final layerId = hazardCheck['layer'] as String?;
        final hazardTags = (hazardCheck['hazardTags'] as List<dynamic>?)
                ?.map((t) => t.toString())
                .toList() ??
            <String>[];
        final varName = hazardCheck['variable'] as String?;
        final varValue = hazardCheck['value'];
        if (layerId != null && varName != null && hazardTags.isNotEmpty) {
          final exitEntity = state.board.getEntity(layerId, finalPos);
          if (exitEntity != null) {
            final kindDef = game.getKind(exitEntity.kind);
            final entityTags = kindDef?.tags ?? <String>[];
            if (hazardTags.any((t) => entityTags.contains(t))) {
              state.variables[varName] = varValue;
              break;
            }
          }
        }
      }

      // Check exit cell for food and award it directly, same reasoning as
      // the hazard check above: no actor_entered event fires for the
      // transit, so eat_food_* rules never see the landing cell and the
      // actor silently overlaps food without collecting it. A food kind is
      // identified by a tag "<amountTagPrefix><N>" (e.g. "food_v7"),
      // awarded to "<budgetVariablePrefix><color>" where color is the last
      // "_"-separated segment of the actor's kind (snake_red -> red),
      // matching the eat_food_N_<color> rule naming convention.
      for (final foodCheck in cfg.exitFoodLayers) {
        final layerId = foodCheck['layer'] as String?;
        final foodTag = foodCheck['foodTag'] as String? ?? 'food';
        final amountPrefix = foodCheck['amountTagPrefix'] as String? ?? 'food_v';
        final budgetPrefix = foodCheck['budgetVariablePrefix'] as String? ?? 'moveBudget_';
        if (layerId == null) continue;
        final exitEntity = state.board.getEntity(layerId, finalPos);
        if (exitEntity == null) continue;
        final kindDef = game.getKind(exitEntity.kind);
        final entityTags = kindDef?.tags ?? <String>[];
        if (!entityTags.contains(foodTag)) continue;
        int? amount;
        for (final t in entityTags) {
          if (t.startsWith(amountPrefix)) {
            final suffix = t.substring(amountPrefix.length);
            final parsed = int.tryParse(suffix);
            if (parsed != null) {
              amount = parsed;
              break;
            }
          }
        }
        if (amount == null) continue;
        final segments = actorKind.split('_');
        final color = segments.isNotEmpty ? segments.last : actorKind;
        final budgetVar = '$budgetPrefix$color';
        final current = state.variables[budgetVar];
        state.variables[budgetVar] = (current is int ? current : 0) + amount;
        state.board.setEntity(layerId, finalPos, null);
        break;
      }

      break; // one transport per cascade pass
    }

    return const [];
  }

  /// If [pos] carries a portal-tagged entity (per [cfg]), returns the paired
  /// portal's position (same kind, same [_ExitPortalConfig.matchKey] value,
  /// any other position) — or null if [cfg] is unset, [pos] isn't a portal,
  /// or no pair exists. Mirrors `PortalsSystem._portalAt`/`_findExitPortal`;
  /// duplicated rather than shared because a silent terrain_skip relocation
  /// never emits the actor_entered event the portals system reacts to, so it
  /// cannot see this landing on its own.
  Position? _chainedPortalExit(
      Board board, Position pos, _ExitPortalConfig? cfg, GameDefinition game) {
    if (cfg == null) return null;
    for (final layerEntry in board.layers.entries) {
      final entity = layerEntry.value.getAt(pos);
      if (entity == null) continue;
      if (!cfg.tags.any((t) => game.hasTag(entity.kind, t))) continue;
      final channelValue = entity.param(cfg.matchKey);
      if (channelValue == null) return null;
      for (final otherLayer in board.layers.entries) {
        for (final entry in otherLayer.value.entries()) {
          if (entry.key == pos) continue;
          final candidate = entry.value;
          if (candidate.kind != entity.kind) continue;
          final ch = candidate.param(cfg.matchKey);
          if (ch?.toString() == channelValue.toString()) {
            return entry.key;
          }
        }
      }
      return null;
    }
    return null;
  }

  /// Bounds, void, walkability, blocking-layer, and actor-occupancy checks
  /// for a candidate landing cell. Used for both the direct terrain exit and,
  /// if it chains through a portal, the portal's paired exit — the latter
  /// needs exactly the same scrutiny, since nothing else in the engine
  /// validates it (see the caller for why).
  bool _validateLanding(
    LevelState state,
    GameDefinition game,
    Position pos,
    String groundLayerId,
    String actorLayerId,
    List<Map<String, dynamic>> exitBlockLayers,
  ) {
    if (!state.board.isInBounds(pos) || state.board.isVoid(pos)) return false;
    final groundEnt = state.board.getEntity(groundLayerId, pos);
    if (groundEnt != null && !game.hasTag(groundEnt.kind, 'walkable')) return false;
    if (state.board.getEntity(actorLayerId, pos) != null) return false;
    for (final layerCheck in exitBlockLayers) {
      final layerId = layerCheck['layer'] as String?;
      final blockTags = (layerCheck['blockTags'] as List<dynamic>?)
              ?.map((t) => t.toString())
              .toList() ??
          <String>[];
      if (layerId != null && blockTags.isNotEmpty) {
        final exitEntity = state.board.getEntity(layerId, pos);
        if (exitEntity != null) {
          final kindDef = game.getKind(exitEntity.kind);
          final entityTags = kindDef?.tags ?? <String>[];
          if (blockTags.any((t) => entityTags.contains(t))) return false;
        }
      }
    }
    return true;
  }

  void _clearActorTrail(LevelState state, _TerrainSkipConfig cfg, String actorKind) {
    for (final tc in cfg.trailClearing) {
      if (tc.actorKind != actorKind) continue;
      final layer = state.board.layers[tc.trailLayer];
      if (layer == null) break;
      final toRestore = <Position>[];
      for (final entry in layer.entries()) {
        if (entry.value.kind == tc.trailKind) toRestore.add(entry.key);
      }
      for (final pos in toRestore) {
        layer.setAt(pos, tc.restoreKind != null ? EntityInstance(tc.restoreKind!) : null);
      }
      if (toRestore.isNotEmpty && tc.budgetVariable != null) {
        final current = state.variables[tc.budgetVariable!];
        state.variables[tc.budgetVariable!] = (current is int ? current : 0) + toRestore.length;
      }
      break;
    }
  }

  _TerrainSkipConfig _config(GameDefinition game) {
    final config = game.systemConfig(id, {});
    final trailClearingRaw = config['trailClearing'] as List? ?? const [];
    final excludeRaw = config['excludeActorKinds'] as List? ?? const [];
    final exitBlockRaw = config['exitBlockLayers'] as List? ?? const [];
    final exitHazardRaw = config['exitHazardLayers'] as List? ?? const [];
    final exitFoodRaw = config['exitFoodLayers'] as List? ?? const [];
    final exitPortalRaw = config['exitPortal'] as Map<String, dynamic>?;
    return _TerrainSkipConfig(
      terrainTag: config['terrainTag'] as String? ?? 'water',
      groundLayer: config['groundLayer'] as String? ?? 'ground',
      actorLayer: config['actorLayer'] as String?,
      actorPositionVariable: config['actorPositionVariable'] as String?,
      exitPortal: exitPortalRaw == null
          ? null
          : _ExitPortalConfig(
              tags: ((exitPortalRaw['tags'] as List<dynamic>?)
                          ?.map((t) => t.toString())
                          .toList()) ??
                  const ['teleport'],
              matchKey: exitPortalRaw['matchKey'] as String? ?? 'channel',
            ),
      trailClearing: trailClearingRaw
          .cast<Map>()
          .map((m) => _TrailClearConfig(
                actorKind: m['actorKind'] as String,
                trailLayer: m['trailLayer'] as String,
                trailKind: m['trailKind'] as String,
                restoreKind: m['restoreKind'] as String?,
                budgetVariable: m['budgetVariable'] as String?,
              ))
          .toList(),
      excludeActorKinds: excludeRaw.map((e) => e.toString()).toList(),
      exitBlockLayers: exitBlockRaw.cast<Map<String, dynamic>>().toList(),
      exitHazardLayers: exitHazardRaw.cast<Map<String, dynamic>>().toList(),
      exitFoodLayers: exitFoodRaw.cast<Map<String, dynamic>>().toList(),
    );
  }
}

class _TerrainSkipConfig {
  final String terrainTag;
  final String groundLayer;
  final String? actorLayer;
  final String? actorPositionVariable;
  final List<_TrailClearConfig> trailClearing;
  final List<String> excludeActorKinds;
  final List<Map<String, dynamic>> exitBlockLayers;
  final List<Map<String, dynamic>> exitHazardLayers;
  final List<Map<String, dynamic>> exitFoodLayers;
  final _ExitPortalConfig? exitPortal;
  const _TerrainSkipConfig({
    required this.terrainTag,
    required this.groundLayer,
    this.actorLayer,
    this.actorPositionVariable,
    this.trailClearing = const [],
    this.excludeActorKinds = const [],
    this.exitBlockLayers = const [],
    this.exitHazardLayers = const [],
    this.exitFoodLayers = const [],
    this.exitPortal,
  });
}

class _ExitPortalConfig {
  final List<String> tags;
  final String matchKey;
  const _ExitPortalConfig({required this.tags, required this.matchKey});
}

class _TrailClearConfig {
  final String actorKind;
  final String trailLayer;
  final String trailKind;
  final String? restoreKind;
  final String? budgetVariable;
  const _TrailClearConfig({
    required this.actorKind,
    required this.trailLayer,
    required this.trailKind,
    this.restoreKind,
    this.budgetVariable,
  });
}