import 'pack_file_reader.dart';
import 'pack_storage.dart';

/// The IDs of packs that ship with the app binary.
const kBundledPackIds = [
  'carrot_quest',
  'number_cells',
  'rotate_flip',
  'flood_colors',
  'diagonal_swipes',
  'box_builder',
  'twinseed',
];

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

  PackRegistry._(this._storage);

  static Future<PackRegistry> create() async =>
      PackRegistry._(createPackStorage());

  PackStorage get storage => _storage;

  /// Returns all packs in display order: bundled first, then installed.
  Future<List<PackEntry>> listAll() async {
    final entries = <PackEntry>[];

    for (final id in kBundledPackIds) {
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
