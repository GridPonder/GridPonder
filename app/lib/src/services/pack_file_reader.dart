import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/services.dart';

/// Abstracts reading pack files regardless of storage location.
abstract class PackFileReader {
  Future<String> readString(String relativePath);
  Future<Uint8List?> readBytes(String relativePath);

  /// Returns all non-JSON asset files as a map of relative path → bytes.
  /// Used to pre-load image assets for installed packs. Default returns empty.
  Future<Map<String, Uint8List>> preloadAssets() async => {};
}

/// Reads pack files from the Flutter asset bundle (for built-in packs).
class BundledPackFileReader implements PackFileReader {
  final String packId;
  const BundledPackFileReader(this.packId);

  @override
  Future<String> readString(String relativePath) =>
      rootBundle.loadString('assets/packs/$packId/$relativePath');

  @override
  Future<Uint8List?> readBytes(String relativePath) async {
    try {
      final data = await rootBundle.load('assets/packs/$packId/$relativePath');
      return data.buffer.asUint8List();
    } catch (_) {
      return null;
    }
  }

  // Bundled assets are resolved via AssetImage — no preloading needed.
  @override
  Future<Map<String, Uint8List>> preloadAssets() async => {};
}

/// Reads pack files from an in-memory map (used for installed packs on web,
/// and as the cache backing for filesystem-installed packs).
class InMemoryPackFileReader implements PackFileReader {
  final Map<String, Uint8List> _files; // relative path → bytes

  const InMemoryPackFileReader(this._files);

  @override
  Future<String> readString(String relativePath) async {
    final bytes = _files[relativePath];
    if (bytes == null) throw Exception('File not found in pack: $relativePath');
    return utf8.decode(bytes);
  }

  @override
  Future<Uint8List?> readBytes(String relativePath) async =>
      _files[relativePath];

  @override
  Future<Map<String, Uint8List>> preloadAssets() async => Map.fromEntries(
        _files.entries.where((e) => !e.key.endsWith('.json')),
      );
}
