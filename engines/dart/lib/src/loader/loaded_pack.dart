import '../models/manifest.dart';
import '../models/game_definition.dart';
import '../models/level_definition.dart';
import '../models/theme.dart';

/// A fully-loaded and parsed game pack.
class LoadedPack {
  final PackManifest manifest;
  final GameDefinition game;
  final ThemeDef? theme;
  final Map<String, LevelDefinition> levels;

  const LoadedPack({
    required this.manifest,
    required this.game,
    this.theme,
    required this.levels,
  });

  LevelDefinition? getLevel(String id) => levels[id];

  List<LevelDefinition> get orderedLevels {
    return game.levelSequence
        .where((e) => e.type == 'level' && e.ref != null)
        .map((e) => levels[e.ref!])
        .whereType<LevelDefinition>()
        .toList();
  }
}
