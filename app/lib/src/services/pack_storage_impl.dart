import 'dart:typed_data';
import 'pack_file_reader.dart';

/// Abstract storage backend for user-installed packs.
abstract class PackStorage {
  /// Returns IDs of all user-installed packs.
  Future<List<String>> listPackIds();

  /// Stores all pack files. [files] maps relative paths → bytes.
  Future<void> savePack(String packId, Map<String, Uint8List> files);

  /// Returns a reader for an installed pack, or null if not found.
  Future<PackFileReader?> readerFor(String packId);

  /// Permanently removes an installed pack.
  Future<void> deletePack(String packId);
}

/// In-memory storage — session-scoped. Used on web (no filesystem) and as
/// the fallback stub.
class InMemoryPackStorage implements PackStorage {
  final Map<String, Map<String, Uint8List>> _store = {};

  @override
  Future<List<String>> listPackIds() async =>
      List<String>.unmodifiable(_store.keys);

  @override
  Future<void> savePack(String packId, Map<String, Uint8List> files) async {
    _store[packId] = Map<String, Uint8List>.from(files);
  }

  @override
  Future<PackFileReader?> readerFor(String packId) async {
    final files = _store[packId];
    return files != null ? InMemoryPackFileReader(files) : null;
  }

  @override
  Future<void> deletePack(String packId) async => _store.remove(packId);
}

/// Factory — overridden on native platforms by pack_storage_impl_native.dart.
PackStorage createPackStorage() => InMemoryPackStorage();
