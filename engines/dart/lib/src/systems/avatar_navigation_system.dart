import '../engine/game_system.dart';
import '../models/event.dart';
import '../models/game_action.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/entity.dart';
import '../models/position.dart';
import 'follower_npcs_system.dart' show facingOf, predictCircuitStep;

// Behavior types whose next step depends only on the NPC's own
// position/facing and the board — never on where the avatar ends up this
// turn. Only these are safe to predict from `executeActionResolution`,
// which runs before the avatar's own move is even decided. `toward_avatar`,
// `toward_tag` and `toward_color` explicitly chase a target, so predicting
// them here would be a real circular dependency (the avatar's move would
// depend on the NPC's move, which depends on the avatar's move) and must
// never be attempted — see `_npcIsVacating` below.
const _predictableBehaviorTypes = {'patrol', 'clockwise'};

class AvatarNavigationSystem extends GameSystem {
  const AvatarNavigationSystem({required super.id})
      : super(type: 'avatar_navigation');

  @override
  List<GameEvent> executeActionResolution(
    GameAction action,
    LevelState state,
    GameDefinition game,
  ) {
    final config = game.systemConfig(id, {});

    final moveAction = config['moveAction'] as String? ?? 'move';
    if (action.actionId != moveAction) return const [];

    final configDirections = config['directions'] as List<dynamic>? ??
        ['up', 'down', 'left', 'right'];
    final allowedDirections =
        configDirections.map((d) => d.toString()).toList();

    final dirStr = action.directionStr;
    if (dirStr == null || !allowedDirections.contains(dirStr)) return const [];

    final direction = action.direction;
    if (direction == null) return const [];

    final avatar = state.avatar;
    if (!avatar.enabled) return const [];

    final pos = avatar.position;
    if (pos == null) return const [];

    final board = state.board;
    final target = pos.moved(direction);

    // Only the moves that never land; a successful step turns further down.
    if (config['faceOnBlockedMove'] == true) {
      state.avatar = state.avatar.copyWith(facing: direction);
    }

    if (!board.isInBounds(target)) return const [];
    if (board.isVoid(target)) return const [];

    final validGroundTags = (config['validGroundTags'] as List? ?? const [])
        .map((value) => value.toString())
        .toList();
    if (validGroundTags.isNotEmpty) {
      final groundLayer = config['groundLayer'] as String? ?? 'ground';
      final walkable = validGroundTags.any(
          (tag) => board.hasTagAt(groundLayer, target, tag, game.entityKinds));
      if (!walkable) return const [];
    }

    final solidHandling = config['solidHandling'] as String? ?? 'block';

    final solidLayers = (config['solidLayers'] as List<dynamic>? ?? ['objects'])
        .map((l) => l.toString())
        .toList();
    // Layers where a block is a genuine non-move, not a wait: the press
    // never had a legal outcome (e.g. the avatar's own trailing body sits
    // wherever it just came from, so pressing straight back into it can
    // never succeed). Distinct from an ordinary solid block, which is still
    // a meaningful spent turn — bumping a wall to wait out a hazard is a
    // real, deliberately-supported move elsewhere on this platform. Empty
    // by default, so this changes nothing for a pack that never sets it.
    final vetoLayers = (config['vetoLayers'] as List<dynamic>? ?? const [])
        .map((l) => l.toString())
        .toSet();
    // Layers where a blocking `patrol`/`clockwise` follower_npcs NPC that is
    // genuinely about to step off this cell this same turn should not cost
    // the player a wasted press. Empty by default, so this changes nothing
    // for a pack that never sets it. See `_npcIsVacating` for the exact
    // rule, its scope (never chasing behaviors), and a note on when its
    // start-of-turn board snapshot can go stale.
    final yieldingLayers = (config['yieldingLayers'] as List<dynamic>? ?? const [])
        .map((l) => l.toString())
        .toSet();
    EntityInstance? entityAtTarget;
    String? entityLayer;
    for (final layerName in solidLayers) {
      final candidate = board.layers[layerName]?.getAt(target);
      if (candidate != null && game.hasTag(candidate.kind, 'solid')) {
        entityAtTarget = candidate;
        entityLayer = layerName;
        break;
      }
    }

    if (entityAtTarget != null) {
      final yielding = entityLayer != null &&
          yieldingLayers.contains(entityLayer) &&
          _npcIsVacating(entityAtTarget, target, state, game);
      if (!yielding) {
        if (entityLayer != null && vetoLayers.contains(entityLayer)) {
          return [GameEvent.actionVetoed()];
        }
        if (solidHandling == 'block') {
          return const [];
        } else if (solidHandling == 'delegate') {
          state.pendingMove = PendingMove(
            from: pos,
            to: target,
            direction: direction,
          );
          return [
            GameEvent.moveBlocked(target, pos, dirStr, entityAtTarget.kind),
          ];
        }
        return const [];
      }
      // else: the NPC is vacating `target` this turn — fall through and let
      // the avatar move in exactly as if the cell were empty.
    }

    // Avatar can move here (entity is null, or non-solid like portals/pickups)
    state.avatar = state.avatar.copyWith(
      position: target,
      facing: direction,
    );

    return [
      GameEvent.avatarExited(pos),
      GameEvent.avatarEntered(target, pos, dirStr),
    ];
  }
}

/// Whether a `patrol`/`clockwise` follower_npcs NPC blocking [npcPos] is
/// genuinely about to step off it this same turn.
///
/// Resolves [npcEntity]'s `behavior` param against every `follower_npcs`
/// system on the level (there can be more than one instance) to find the
/// behavior definition, then — only for `patrol`/`clockwise`, never for a
/// chasing behavior (`toward_avatar`/`toward_tag`/`toward_color`), and never
/// for a shaft (train) member — predicts its next step with
/// [predictCircuitStep], the exact same function `FollowerNpcsSystem` itself
/// uses. Returns true only when that prediction lands somewhere other than
/// [npcPos]. Note the *predicted* landing cell can differ from where the NPC
/// actually lands: this prediction still sees the avatar at its pre-move
/// position (the real move hasn't happened yet), so a candidate step that
/// happens to be the avatar's own starting cell reads as blocked here but
/// may be free by the time `npc_resolution` actually runs, after the avatar
/// has moved off it. That can steer the NPC's real step to a different cell
/// than predicted — but never changes the vacate/stay conclusion this
/// function reports, which is all the caller needs: `blockAvatar` only ever
/// goes from "blocked" (prediction) to "open" (reality) as the avatar
/// vacates its own old cell, never the reverse, so this can only make the
/// prediction more conservative, never less.
///
/// Chasing behaviors are excluded on purpose: their step depends on where
/// the avatar ends up this turn, so predicting them here — before the
/// avatar's own move is even decided — would be a real circular dependency.
/// Shaft members are excluded because they resolve as a unit through
/// `FollowerNpcsSystem._resolveTrain` (cross-member "claimed cell" probing),
/// a different algorithm than the standalone [predictCircuitStep] used here;
/// predicting one member in isolation could disagree with how the train
/// actually moves together.
///
/// Staleness note (read before reusing this elsewhere): this reads board
/// state as it stands at the very start of the turn, before the avatar's own
/// move, `movementResolution`, or `cascadeResolution` have run. That is safe
/// exactly when nothing in those later phases can add or remove a
/// `solid`-tagged entity on the `objects` layer (or, when the behavior sets
/// `movementBlockingLayers`, any of those additional layers — the only layers a
/// patrol/clockwise NPC's `solidBlocking` check reads) at a cell this
/// prediction depends on. It does NOT hold in general: `push_objects`
/// (`movementResolution`) and cascade-phase systems such as `ice_slide` and
/// `portals` all move or remove solid entities on the `objects` layer as a
/// direct consequence of this same turn's action, so a pack that combines
/// `yieldingLayers` with any of those against a patrol/clockwise NPC's path
/// could see this prediction go stale by the time `npcResolution` actually
/// runs. It IS safe for a pack (such as Hitch) whose only interaction here is
/// `follower_npcs` itself with no push/slide/portal mechanic touching the
/// `objects` layer (or a configured `movementBlockingLayers` layer) near the
/// yielding NPC's path.
bool _npcIsVacating(
  EntityInstance npcEntity,
  Position npcPos,
  LevelState state,
  GameDefinition game,
) {
  final behaviorName = npcEntity.param('behavior')?.toString();
  if (behaviorName == null) return false;

  Map<String, dynamic>? behaviorDef;
  List<String> npcTags = const [];
  for (final system in game.systems) {
    if (system.type != 'follower_npcs' || !system.enabled) continue;
    final behaviors =
        system.config['behaviors'] as Map<String, dynamic>? ?? const {};
    final candidate = behaviors[behaviorName];
    if (candidate is Map<String, dynamic>) {
      behaviorDef = candidate;
      final rawTags = system.config['npcTags'] as List<dynamic>? ?? ['npc'];
      npcTags = rawTags.map((t) => t.toString()).toList();
      break;
    }
  }

  if (behaviorDef == null) return false;
  final behaviorType = behaviorDef['type'] as String?;
  if (behaviorType == null || !_predictableBehaviorTypes.contains(behaviorType)) {
    return false;
  }
  if (npcEntity.param('shaft') != null) return false;

  final facing = facingOf(npcEntity);
  final solidBlocking = behaviorDef['solidBlocking'] as bool? ?? true;
  final movementBlockingLayers =
      (behaviorDef['movementBlockingLayers'] as List<dynamic>? ?? const [])
          .map((l) => l.toString())
          .toList();
  final blockAvatar = !(behaviorDef['lethalContact'] as bool? ?? false);

  // Mirrors the initial `occupiedAfterMove` follower_npcs itself seeds at
  // the top of `executeNpcResolution` for this same system instance: every
  // NPC matching its npcTags, at its current (not-yet-moved) position.
  final occupiedAfterMove = <Position>{};
  final actorsLayer = state.board.layers['actors'];
  if (actorsLayer != null) {
    for (final entry in actorsLayer.entries()) {
      if (npcTags.any((tag) => game.hasTag(entry.value.kind, tag))) {
        occupiedAfterMove.add(entry.key);
      }
    }
  }

  final (nextPos, _) = predictCircuitStep(
    behaviorType: behaviorType,
    npcPos: npcPos,
    facing: facing,
    state: state,
    board: state.board,
    game: game,
    solidBlocking: solidBlocking,
    movementBlockingLayers: movementBlockingLayers,
    occupiedAfterMove: occupiedAfterMove,
    blockAvatar: blockAvatar,
  );
  return nextPos != null && nextPos != npcPos;
}
