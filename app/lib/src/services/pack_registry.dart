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
  final List<PackEntry> _bundledEntries;

  PackRegistry._(this._storage, this._bundledEntries);

  /// Discovers bundled packs by scanning the asset manifest for
  /// `assets/packs/<id>/manifest.json` and `assets/packs-private/<id>/manifest.json`.
  /// Adding a pack to `pubspec.yaml` is the single source of truth.
  static Future<PackRegistry> create() async {
    final manifest = await AssetManifest.loadFromAssetBundle(rootBundle);
    final allAssets = manifest.listAssets();
    final entries = <PackEntry>[];
    final seen = <String>{};

    for (final root in const ['assets/packs', 'assets/packs-private']) {
      final pattern = RegExp('^$root/([^/]+)/manifest\\.json\$');
      final ids = allAssets
          .map(pattern.firstMatch)
          .where((m) => m != null)
          .map((m) => m!.group(1)!)
          .where(seen.add) // deduplicate across roots
          .toList()
        ..sort();
      for (final id in ids) {
        entries.add(PackEntry(
          id: id,
          isInstalled: false,
          reader: BundledPackFileReader(id, assetRoot: root),
        ));
      }
    }

    return PackRegistry._(createPackStorage(), List.unmodifiable(entries));
  }

  PackStorage get storage => _storage;

  /// IDs of packs compiled into the app binary, in stable (alphabetical)
  /// order per root (public first, then private). Used by the importer to
  /// prevent user-installed packs from shadowing bundled ones.
  List<String> get bundledIds => _bundledEntries.map((e) => e.id).toList();

  /// Returns all packs in display order: bundled first, then installed.
  Future<List<PackEntry>> listAll() async {
    final entries = List<PackEntry>.from(_bundledEntries);

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
