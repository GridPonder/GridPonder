import '../engine/game_system.dart';
import '../models/game_definition.dart';
import 'anchor_point_system.dart';
import 'avatar_navigation_system.dart';
import 'coupled_actors_system.dart';
import 'flank_capture_system.dart';
import 'flood_fill_system.dart';
import 'ice_slide_system.dart';
import 'individual_actors_system.dart';
import 'follower_npcs_system.dart';
import 'line_of_sight_system.dart';
import 'overlay_cursor_system.dart';
import 'portals_system.dart';
import 'push_objects_system.dart';
import 'queued_emitters_system.dart';
import 'region_transform_system.dart';
import 'sided_box_system.dart';
import 'sliding_blocks_system.dart';
import 'slide_merge_system.dart';
import 'support_collapse_system.dart';
import 'terrain_edit_system.dart';
import 'tile_teleport_system.dart';

/// Creates a GameSystem instance from a SystemDef.
typedef SystemFactory = GameSystem Function(
    String id, Map<String, dynamic> config);

class SystemRegistry {
  static final Map<String, SystemFactory> _factories = {
    'anchor_point': (id, _) => AnchorPointSystem(id: id),
    'avatar_navigation': (id, _) => AvatarNavigationSystem(id: id),
    'coupled_actors': (id, _) => CoupledActorsSystem(id: id),
    'individual_actors': (id, _) => IndividualActorsSystem(id: id),
    'push_objects': (id, _) => PushObjectsSystem(id: id),
    'portals': (id, _) => PortalsSystem(id: id),
    'follower_npcs': (id, _) => FollowerNpcsSystem(id: id),
    'slide_merge': (id, _) => SlideMergeSystem(id: id),
    'queued_emitters': (id, _) => QueuedEmittersSystem(id: id),
    'overlay_cursor': (id, _) => OverlayCursorSystem(id: id),
    'region_transform': (id, _) => RegionTransformSystem(id: id),
    'sided_box': (id, _) => SidedBoxSystem(id: id),
    'sliding_blocks': (id, config) =>
        SlidingBlocksSystem(id: id, config: config),
    'line_of_sight': (id, config) => LineOfSightSystem(id: id, config: config),
    'flank_capture': (id, config) => FlankCaptureSystem(id: id, config: config),
    'support_collapse': (id, config) =>
        SupportCollapseSystem(id: id, config: config),
    'flood_fill': (id, _) => FloodFillSystem(id: id),
    'tile_teleport': (id, _) => TileTeleportSystem(id: id),
    'ice_slide': (id, _) => IceSlideSystem(id: id),
    'terrain_edit': (id, _) => TerrainEditSystem(id: id),
  };

  /// Instantiate all enabled systems from a GameDefinition,
  /// merging per-level overrides into their config.
  static List<GameSystem> instantiate(
    GameDefinition game,
    Map<String, Map<String, dynamic>>? levelOverrides,
  ) {
    final effectiveGame = game.withSystemOverrides(levelOverrides);
    final systems = <GameSystem>[];
    for (final def in effectiveGame.systems) {
      if (!def.enabled) continue;
      final factory = _factories[def.type];
      if (factory == null) continue; // unknown system type, skip
      final config = game.systemConfig(def.id, levelOverrides);
      systems.add(factory(def.id, config));
    }
    return systems;
  }
}
