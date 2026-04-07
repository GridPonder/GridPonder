import 'dart:convert';

import '../models/game_definition.dart';
import '../models/level_definition.dart';
import '../models/manifest.dart';
import '../models/theme.dart';
import 'loaded_pack.dart';

/// Loads a game pack from pre-parsed JSON maps.
/// The platform app is responsible for reading asset files and passing them here.
class PackLoader {
  /// Load from explicit JSON maps (asset-bundle or test usage).
  static LoadedPack load({
    required Map<String, dynamic> manifestJson,
    required Map<String, dynamic> gameJson,
    Map<String, dynamic>? themeJson,
    required Map<String, Map<String, dynamic>> levelJsons,
  }) {
    final manifest = PackManifest.fromJson(manifestJson);
    final game = GameDefinition.fromJson(gameJson,
        id: manifest.gameId,
        title: manifest.title,
        description: manifest.description ?? '');
    final theme = themeJson != null ? ThemeDef.fromJson(themeJson) : null;

    final levels = <String, LevelDefinition>{};
    for (final entry in levelJsons.entries) {
      final levelDef = LevelDefinition.fromJson(entry.value, game.layers);
      levels[levelDef.id] = levelDef;
    }

    return LoadedPack(
      manifest: manifest,
      game: game,
      theme: theme,
      levels: levels,
    );
  }

  /// Load from JSON strings (for CLI tooling).
  static LoadedPack loadFromStrings({
    required String manifestStr,
    required String gameStr,
    String? themeStr,
    required Map<String, String> levelStrs,
  }) {
    return load(
      manifestJson: jsonDecode(manifestStr) as Map<String, dynamic>,
      gameJson: jsonDecode(gameStr) as Map<String, dynamic>,
      themeJson: themeStr != null
          ? jsonDecode(themeStr) as Map<String, dynamic>
          : null,
      levelJsons: levelStrs.map(
          (k, v) => MapEntry(k, jsonDecode(v) as Map<String, dynamic>)),
    );
  }
}
