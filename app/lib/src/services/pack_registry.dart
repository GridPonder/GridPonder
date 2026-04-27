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
  final List<String> _bundledIds;

  PackRegistry._(this._storage, this._bundledIds);

  /// Discovers bundled pack IDs by scanning the asset manifest for any
  /// `assets/packs/<id>/manifest.json`. Adding a pack to `pubspec.yaml` is
  /// the single source of truth — no separate ID list to maintain.
  static Future<PackRegistry> create() async {
    final manifest = await AssetManifest.loadFromAssetBundle(rootBundle);
    final pattern = RegExp(r'^assets/packs/([^/]+)/manifest\.json$');
    final ids = manifest
        .listAssets()
        .map(pattern.firstMatch)
        .where((m) => m != null)
        .map((m) => m!.group(1)!)
        .toSet()
        .toList()
      ..sort();
    return PackRegistry._(createPackStorage(), List.unmodifiable(ids));
  }

  PackStorage get storage => _storage;

  /// IDs of packs compiled into the app binary, in stable (alphabetical)
  /// order. Used by both the library UI and the importer (to prevent a
  /// user-imported pack from shadowing a bundled one).
  List<String> get bundledIds => _bundledIds;

  /// Returns all packs in display order: bundled first, then installed.
  Future<List<PackEntry>> listAll() async {
    final entries = <PackEntry>[];

    for (final id in _bundledIds) {
      entries.add(PackEntry(
        id: id,
        isInstalled: false,
        reader: BundledPackFileReader(id),
      ));
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
