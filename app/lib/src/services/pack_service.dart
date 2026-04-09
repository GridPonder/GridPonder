import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/painting.dart';
import 'package:flutter/services.dart';
import 'package:gridponder_engine/engine.dart';
import 'pack_file_reader.dart';
import 'pack_registry.dart';

/// Metadata for a pack shown in the library screen.
class PackInfo {
  final String id;
  final String title;
  final String description;
  final int color; // ARGB — primaryColor from theme.json
  final ImageProvider? coverImage; // AssetImage (bundled) or MemoryImage (installed)
  final bool isInstalled;
  /// Ordered IDs of all playable levels in this pack (from game.json levelSequence).
  /// Used for progress tracking without loading individual level files.
  final List<String> levelIds;

  const PackInfo({
    required this.id,
    required this.title,
    required this.description,
    required this.color,
    this.coverImage,
    this.isInstalled = false,
    this.levelIds = const [],
  });
}

/// Loads a game pack and provides asset resolution for both bundled and
/// user-installed packs.
class PackService {
  final LoadedPack pack;
  final PackInfo info;
  final PackFileReader _reader;
  // Pre-loaded image bytes for installed packs (pack-relative path → bytes).
  final Map<String, Uint8List> _assetCache;

  PackService._(this.pack, this.info, this._reader, this._assetCache);

  ThemeDef? get theme => pack.theme;
  List<String> get levelIds => pack.orderedLevels.map((l) => l.id).toList();
  List<SequenceEntry> get sequence => pack.game.levelSequence;
  LevelDefinition level(String id) => pack.levels[id]!;
  GameDefinition get game => pack.game;

  // ---------------------------------------------------------------------------
  // Loading
  // ---------------------------------------------------------------------------

  /// Loads metadata only (fast — for library cards). Uses the bundled reader.
  static Future<PackInfo> loadInfo(String packId) =>
      _loadInfoFromReader(packId, BundledPackFileReader(packId));

  /// Loads metadata for any pack entry (bundled or installed).
  static Future<PackInfo> loadInfoFromEntry(PackEntry entry) =>
      _loadInfoFromReader(entry.id, entry.reader,
          isInstalled: entry.isInstalled);

  /// Loads the full pack for gameplay. Uses the bundled reader.
  static Future<PackService> load(String packId) =>
      _loadFromReader(packId, BundledPackFileReader(packId));

  /// Loads the full pack for any pack entry (bundled or installed).
  static Future<PackService> loadFromEntry(PackEntry entry) =>
      _loadFromReader(entry.id, entry.reader, isInstalled: entry.isInstalled);

  // ---------------------------------------------------------------------------
  // Private loading helpers
  // ---------------------------------------------------------------------------

  static Future<PackInfo> _loadInfoFromReader(
    String packId,
    PackFileReader reader, {
    bool isInstalled = false,
  }) async {
    final manifestStr = await reader.readString('manifest.json');
    final manifest = jsonDecode(manifestStr) as Map<String, dynamic>;

    String? themeStr;
    try {
      themeStr = await reader.readString('theme.json');
    } catch (_) {}
    final theme =
        themeStr != null ? jsonDecode(themeStr) as Map<String, dynamic> : null;

    // Read game.json to extract the ordered level ID list for progress tracking.
    List<String> levelIds = const [];
    try {
      final gameStr = await reader.readString('game.json');
      final game = jsonDecode(gameStr) as Map<String, dynamic>;
      final sequence = game['levelSequence'] as List<dynamic>? ?? [];
      levelIds = sequence
          .whereType<Map<String, dynamic>>()
          .where((e) => e['type'] == 'level' && e['ref'] != null)
          .map((e) => e['ref'] as String)
          .toList();
    } catch (_) {}

    return _buildInfo(packId, manifest, theme, reader,
        isInstalled: isInstalled, levelIds: levelIds);
  }

  static Future<PackService> _loadFromReader(
    String packId,
    PackFileReader reader, {
    bool isInstalled = false,
  }) async {
    final manifestStr = await reader.readString('manifest.json');
    final gameStr = await reader.readString('game.json');
    final manifest = jsonDecode(manifestStr) as Map<String, dynamic>;
    final game = jsonDecode(gameStr) as Map<String, dynamic>;

    String? themeStr;
    try {
      themeStr = await reader.readString('theme.json');
    } catch (_) {}
    final theme =
        themeStr != null ? jsonDecode(themeStr) as Map<String, dynamic> : null;

    final levelJsons = <String, Map<String, dynamic>>{};
    final sequence = game['levelSequence'] as List<dynamic>? ?? [];
    for (final entry in sequence) {
      final map = entry as Map<String, dynamic>;
      if (map['type'] != 'level') continue;
      final ref = map['ref'] as String;
      final levelStr = await reader.readString('levels/$ref.json');
      levelJsons[ref] = jsonDecode(levelStr) as Map<String, dynamic>;
    }

    final loadedPack = PackLoader.load(
      manifestJson: manifest,
      gameJson: game,
      themeJson: theme,
      levelJsons: levelJsons,
    );

    final info = await _buildInfo(packId, manifest, theme, reader,
        isInstalled: isInstalled);

    // Pre-load all image assets for installed packs so resolvePackImage()
    // can be called synchronously inside widget build methods.
    final assetCache = isInstalled
        ? await reader.preloadAssets()
        : <String, Uint8List>{};

    return PackService._(loadedPack, info, reader, assetCache);
  }

  static Future<PackInfo> _buildInfo(
    String packId,
    Map<String, dynamic> manifest,
    Map<String, dynamic>? theme,
    PackFileReader reader, {
    bool isInstalled = false,
    List<String> levelIds = const [],
  }) async {
    final coverImagePath = manifest['coverImage'] as String?;

    ImageProvider? coverImage;
    if (coverImagePath != null) {
      if (!isInstalled) {
        coverImage = AssetImage('assets/packs/$packId/$coverImagePath');
      } else {
        final bytes = await reader.readBytes(coverImagePath);
        if (bytes != null) coverImage = MemoryImage(bytes);
      }
    }

    final colorHex = theme?['primaryColor'] as String?;
    final color = _parseColor(colorHex) ?? 0xFF607D8B;

    return PackInfo(
      id: packId,
      title: manifest['title'] as String? ?? packId,
      description: manifest['description'] as String? ?? '',
      color: color,
      coverImage: coverImage,
      isInstalled: isInstalled,
      levelIds: levelIds,
    );
  }

  // ---------------------------------------------------------------------------
  // Asset resolution
  // ---------------------------------------------------------------------------

  /// Returns an [ImageProvider] for a pack-relative asset path.
  /// Synchronous — safe to call inside widget build methods.
  /// Bundled packs → [AssetImage]. Installed packs → [MemoryImage] from cache.
  ImageProvider resolvePackImage(String packRelativePath) {
    if (!info.isInstalled) {
      return AssetImage('assets/packs/${info.id}/$packRelativePath');
    }
    final bytes = _assetCache[packRelativePath];
    if (bytes != null) return MemoryImage(bytes);
    // Asset not in cache — return transparent 1×1 pixel placeholder.
    return MemoryImage(Uint8List.fromList(_kTransparentPixelPng));
  }

  /// Legacy path-based resolver — still used by the shared sprite systems
  /// (gridponder-base and rabbit-character) which are always bundled.
  String resolvePackAsset(String packRelativePath) =>
      'assets/packs/${info.id}/$packRelativePath';

  String resolveSprite(String dslPath) {
    final filename = dslPath.split('/').last;
    return 'assets/packs/gridponder-base/sprites/tiles/$filename';
  }

  String resolveAvatarSprite(String filename) =>
      'assets/packs/rabbit-character/sprites/avatar/$filename';

  // ---------------------------------------------------------------------------

  static int? _parseColor(String? hex) {
    if (hex == null) return null;
    final s = hex.startsWith('#') ? hex.substring(1) : hex;
    if (s.length == 6) return int.tryParse('FF$s', radix: 16);
    if (s.length == 8) return int.tryParse(s, radix: 16);
    return null;
  }
}

/// A 1×1 transparent PNG — fallback for missing installed-pack assets.
const _kTransparentPixelPng = <int>[
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d,
  0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
  0x08, 0x06, 0x00, 0x00, 0x00, 0x1f, 0x15, 0xc4, 0x89, 0x00, 0x00, 0x00,
  0x0b, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x62, 0x00, 0x01, 0x00, 0x00,
  0x05, 0x00, 0x01, 0x0d, 0x0a, 0x2d, 0xb4, 0x00, 0x00, 0x00, 0x00, 0x49,
  0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
];
