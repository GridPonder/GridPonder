import 'dart:io';
import 'dart:typed_data';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'pack_file_reader.dart';
import 'pack_storage_impl.dart';

// Re-export abstract class so that importers of pack_storage.dart get it.
export 'pack_storage_impl.dart' show PackStorage;

/// A [PackFileReader] that reads files lazily from the local filesystem.
class _FilesystemReader implements PackFileReader {
  final String _basePath;
  _FilesystemReader(this._basePath);

  @override
  Future<String> readString(String relativePath) =>
      File('$_basePath/$relativePath').readAsString();

  @override
  Future<Uint8List?> readBytes(String relativePath) async {
    final f = File('$_basePath/$relativePath');
    return await f.exists() ? await f.readAsBytes() : null;
  }

  @override
  Future<Map<String, Uint8List>> preloadAssets() async {
    final dir = Directory(_basePath);
    final result = <String, Uint8List>{};
    await for (final entity in dir.list(recursive: true)) {
      if (entity is File && !entity.path.endsWith('.json')) {
        final rel = entity.path.substring(_basePath.length + 1);
        result[rel] = await entity.readAsBytes();
      }
    }
    return result;
  }
}

/// Filesystem-backed storage for user-installed packs.
/// Packs live at <documents>/gridponder/packs/<packId>/.
class FilesystemPackStorage implements PackStorage {
  static const _prefsKey = 'gridponder_installed_pack_ids';

  Future<String> _basePathFor(String packId) async {
    final docs = await getApplicationDocumentsDirectory();
    return '${docs.path}/gridponder/packs/$packId';
  }

  @override
  Future<List<String>> listPackIds() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getStringList(_prefsKey) ?? [];
  }

  @override
  Future<void> savePack(String packId, Map<String, Uint8List> files) async {
    final base = await _basePathFor(packId);
    await Directory(base).create(recursive: true);
    for (final entry in files.entries) {
      final file = File('$base/${entry.key}');
      await file.parent.create(recursive: true);
      await file.writeAsBytes(entry.value);
    }
    final prefs = await SharedPreferences.getInstance();
    final ids = (prefs.getStringList(_prefsKey) ?? []).toList();
    if (!ids.contains(packId)) {
      ids.add(packId);
      await prefs.setStringList(_prefsKey, ids);
    }
  }

  @override
  Future<PackFileReader?> readerFor(String packId) async {
    final ids = await listPackIds();
    if (!ids.contains(packId)) return null;
    final base = await _basePathFor(packId);
    if (!await Directory(base).exists()) return null;
    return _FilesystemReader(base);
  }

  @override
  Future<void> deletePack(String packId) async {
    final base = await _basePathFor(packId);
    final dir = Directory(base);
    if (await dir.exists()) await dir.delete(recursive: true);
    final prefs = await SharedPreferences.getInstance();
    final ids = (prefs.getStringList(_prefsKey) ?? []).toList()
      ..remove(packId);
    await prefs.setStringList(_prefsKey, ids);
  }
}

/// Overrides the stub factory from pack_storage_impl.dart.
PackStorage createPackStorage() => FilesystemPackStorage();
