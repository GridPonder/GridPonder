import '../engine/game_system.dart';
import '../models/game_definition.dart';
import 'avatar_navigation_system.dart';
import 'flood_fill_system.dart';
import 'follower_npcs_system.dart';
import 'overlay_cursor_system.dart';
import 'portals_system.dart';
import 'push_objects_system.dart';
import 'queued_emitters_system.dart';
import 'region_transform_system.dart';
import 'sided_box_system.dart';
import 'slide_merge_system.dart';

/// Creates a GameSystem instance from a SystemDef.
typedef SystemFactory = GameSystem Function(String id, Map<String, dynamic> config);

class SystemRegistry {
  static final Map<String, SystemFactory> _factories = {
    'avatar_navigation': (id, _) => AvatarNavigationSystem(id: id),
    'push_objects': (id, _) => PushObjectsSystem(id: id),
    'portals': (id, _) => PortalsSystem(id: id),
    'follower_npcs': (id, _) => FollowerNpcsSystem(id: id),
    'slide_merge': (id, _) => SlideMergeSystem(id: id),
    'queued_emitters': (id, _) => QueuedEmittersSystem(id: id),
    'overlay_cursor': (id, _) => OverlayCursorSystem(id: id),
    'region_transform': (id, _) => RegionTransformSystem(id: id),
    'sided_box': (id, _) => SidedBoxSystem(id: id),
    'flood_fill': (id, _) => FloodFillSystem(id: id),
  };

  /// Instantiate all enabled systems from a GameDefinition,
  /// merging per-level overrides into their config.
  static List<GameSystem> instantiate(
    GameDefinition game,
    Map<String, Map<String, dynamic>>? levelOverrides,
  ) {
    final systems = <GameSystem>[];
    for (final def in game.systems) {
      if (!def.enabled) continue;
      final factory = _factories[def.type];
      if (factory == null) continue; // unknown system type, skip
      final config = game.systemConfig(def.id, levelOverrides);
      systems.add(factory(def.id, config));
    }
    return systems;
  }
}
