import 'package:flutter/services.dart' show AssetManifest, rootBundle;
import 'pack_file_reader.dart';
import 'pack_storage.dart';

/// A pack entry — knows its ID, whether it was user-installed, and how to
/// read its files.
class PackEntry {
  final String id;
  final bool isInstalled;
  final PackFileReader reader;

  const PackEntry({
    required this.id,
    required this.isInstalled,
    required this.reader,
  });
}

/// Manages all packs: bundled (compiled into the app) and user-installed
/// (imported from zip files and stored on-device).
class PackRegistry {
  final PackStorage _storage;
  // Bundled pack id -> the asset root it was discovered under. Insertion
  // order is sorted-by-id (see resolveBundledRoots).
  final Map<String, String> _bundledRoots;

  PackRegistry._(this._storage, this._bundledRoots);

  /// Asset roots scanned for bundled packs, in shadowing-priority order: a
  /// pack id found under an earlier root wins over the same id found under a
  /// later root. `assets/packs-private` is populated only by
  /// `gridponder-private/dev_setup.sh`, which symlinks a private pack repo in
  /// and patches `pubspec.yaml` for local dev builds; production pubspecs
  /// never reference it, so the AssetManifest has no matching keys and this
  /// root is a no-op in release builds.
  static const bundledAssetRoots = ['assets/packs', 'assets/packs-private'];

  /// Matches AssetManifest keys against `<root>/<id>/manifest.json` for each
  /// of [bundledAssetRoots] — only a depth-1 `<id>/manifest.json` counts,
  /// deeper paths are ignored — and returns a sorted, duplicate-free map of
  /// pack id to the root it was discovered under. A pure function (no asset
  /// bundle access) so discovery is unit-testable in isolation; [create]
  /// calls it with the real AssetManifest keys.
  static Map<String, String> resolveBundledRoots(Iterable<String> assetKeys) {
    final keys = assetKeys.toList();
    final found = <String, String>{};
    for (final root in bundledAssetRoots) {
      final pattern = RegExp(
        '^${RegExp.escape(root)}/([^/]+)/manifest\\.json\$',
      );
      for (final key in keys) {
        final match = pattern.firstMatch(key);
        if (match == null) continue;
        found.putIfAbsent(match.group(1)!, () => root);
      }
    }
    final sortedIds = found.keys.toList()..sort();
    return {for (final id in sortedIds) id: found[id]!};
  }

  /// Discovers bundled pack IDs by scanning the asset manifest for any
  /// `<root>/<id>/manifest.json` under [bundledAssetRoots]. Adding a pack to
  /// `pubspec.yaml` is the single source of truth — no separate ID list to
  /// maintain.
  static Future<PackRegistry> create() async {
    final manifest = await AssetManifest.loadFromAssetBundle(rootBundle);
    final roots = resolveBundledRoots(manifest.listAssets());
    return PackRegistry._(createPackStorage(), roots);
  }

  PackStorage get storage => _storage;

  /// IDs of packs compiled into the app binary, in stable (alphabetical)
  /// order. Used by both the library UI and the importer (to prevent a
  /// user-imported pack from shadowing a bundled one).
  List<String> get bundledIds => List.unmodifiable(_bundledRoots.keys);

  /// Returns all packs in display order: bundled first, then installed.
  Future<List<PackEntry>> listAll() async {
    final entries = <PackEntry>[];

    for (final entry in _bundledRoots.entries) {
      entries.add(
        PackEntry(
          id: entry.key,
          isInstalled: false,
          reader: BundledPackFileReader(entry.key, assetRoot: entry.value),
        ),
      );
    }

    final installedIds = await _storage.listPackIds();
    for (final id in installedIds) {
      final reader = await _storage.readerFor(id);
      if (reader != null) {
        entries.add(PackEntry(id: id, isInstalled: true, reader: reader));
      }
    }

    return entries;
  }

  /// Returns only the IDs of user-installed packs.
  Future<List<String>> listInstalledIds() => _storage.listPackIds();

  /// Removes an installed pack. No-op if [packId] is not installed.
  Future<void> delete(String packId) => _storage.deletePack(packId);
}
