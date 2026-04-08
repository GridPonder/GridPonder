import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:gridponder_engine/engine.dart';

/// Metadata for a pack shown in the library screen.
class PackInfo {
  final String id;
  final String title;
  final String description;
  final int color; // ARGB — primaryColor from theme.json
  final String? coverImageAsset; // resolved Flutter asset path, from manifest
  const PackInfo({
    required this.id,
    required this.title,
    required this.description,
    required this.color,
    this.coverImageAsset,
  });
}

/// IDs of packs bundled in the app. All other metadata (title, description,
/// cover image, primary color) is loaded from the pack's manifest/theme files.
const kAvailablePacks = [
  'flag_adventure',
  'number_cells',
  'rotate_flip',
  'flood_colors',
  'diagonal_swipes',
];

/// Loads a game pack from the Flutter asset bundle and provides
/// sprite path resolution.
class PackService {
  final LoadedPack pack;
  final PackInfo info;

  PackService._(this.pack, this.info);

  ThemeDef? get theme => pack.theme;

  /// Reads only manifest.json + theme.json for a pack — fast, used by the
  /// library screen to populate cards without loading the full game.
  static Future<PackInfo> loadInfo(String packId) async {
    final base = 'assets/packs/$packId';
    final manifestStr = await rootBundle.loadString('$base/manifest.json');
    final manifest = jsonDecode(manifestStr) as Map<String, dynamic>;

    String? themeStr;
    try {
      themeStr = await rootBundle.loadString('$base/theme.json');
    } catch (_) {
      // theme.json is optional
    }
    final theme =
        themeStr != null ? jsonDecode(themeStr) as Map<String, dynamic> : null;

    return _infoFromManifestAndTheme(packId, manifest, theme);
  }

  /// Loads the full pack (manifest + theme + game + levels) for gameplay.
  static Future<PackService> load(String packId) async {
    final base = 'assets/packs/$packId';

    final manifestStr = await rootBundle.loadString('$base/manifest.json');
    final gameStr = await rootBundle.loadString('$base/game.json');

    final manifest = jsonDecode(manifestStr) as Map<String, dynamic>;
    final game = jsonDecode(gameStr) as Map<String, dynamic>;

    String? themeStr;
    try {
      themeStr = await rootBundle.loadString('$base/theme.json');
    } catch (_) {}
    final theme =
        themeStr != null ? jsonDecode(themeStr) as Map<String, dynamic> : null;

    final levelJsons = <String, Map<String, dynamic>>{};
    final sequence = game['levelSequence'] as List<dynamic>? ?? [];
    for (final entry in sequence) {
      final map = entry as Map<String, dynamic>;
      if (map['type'] != 'level') continue;
      final ref = map['ref'] as String;
      final levelStr = await rootBundle.loadString('$base/levels/$ref.json');
      levelJsons[ref] = jsonDecode(levelStr) as Map<String, dynamic>;
    }

    final loadedPack = PackLoader.load(
      manifestJson: manifest,
      gameJson: game,
      themeJson: theme,
      levelJsons: levelJsons,
    );

    return PackService._(
        loadedPack, _infoFromManifestAndTheme(packId, manifest, theme));
  }

  static PackInfo _infoFromManifestAndTheme(
    String packId,
    Map<String, dynamic> manifest,
    Map<String, dynamic>? theme,
  ) {
    final base = 'assets/packs/$packId';
    final coverImageDsl = manifest['coverImage'] as String?;

    // primaryColor from theme.json, with a neutral fallback.
    final colorHex = theme?['primaryColor'] as String?;
    final color = _parseColor(colorHex) ?? 0xFF607D8B;

    return PackInfo(
      id: packId,
      title: manifest['title'] as String? ?? packId,
      description: manifest['description'] as String? ?? '',
      color: color,
      coverImageAsset:
          coverImageDsl != null ? '$base/$coverImageDsl' : null,
    );
  }

  /// Parses a CSS hex color string ("#RRGGBB" or "#AARRGGBB") to ARGB int.
  static int? _parseColor(String? hex) {
    if (hex == null) return null;
    final s = hex.startsWith('#') ? hex.substring(1) : hex;
    if (s.length == 6) return int.tryParse('FF$s', radix: 16);
    if (s.length == 8) return int.tryParse(s, radix: 16);
    return null;
  }

  List<String> get levelIds => pack.orderedLevels.map((l) => l.id).toList();
  List<SequenceEntry> get sequence => pack.game.levelSequence;
  LevelDefinition level(String id) => pack.levels[id]!;
  GameDefinition get game => pack.game;

  /// Resolve a pack-relative asset path (e.g. from a story entry's image field)
  /// to a Flutter asset path.
  String resolvePackAsset(String packRelativePath) =>
      'assets/packs/${info.id}/$packRelativePath';

  String resolveSprite(String dslPath) {
    final filename = dslPath.split('/').last;
    return 'assets/packs/gridponder-base/sprites/tiles/$filename';
  }

  String resolveAvatarSprite(String filename) =>
      'assets/packs/rabbit-character/sprites/avatar/$filename';
}
