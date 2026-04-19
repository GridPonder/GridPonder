import 'dart:convert';
import 'dart:typed_data';
import 'package:archive/archive.dart';
import 'pack_storage.dart';

/// Thrown by [PackImporter.importZip] on any import failure.
class PackImportError implements Exception {
  final String message;
  PackImportError(this.message);
  @override
  String toString() => message;
}

/// Thrown when a pack with the same ID is already installed.
/// The UI catches this specifically to offer a "replace?" confirmation.
class PackConflictError extends PackImportError {
  final String packId;
  final String existingTitle;
  PackConflictError(this.packId, this.existingTitle)
      : super('"$existingTitle" is already installed.');
}

/// IDs of packs compiled into the app binary — these can never be replaced.
const _kBundledPackIds = [
  'carrot_quest',
  'number_cells',
  'rotate_flip',
  'flood_colors',
  'diagonal_swipes',
  'box_builder',
];

/// Handles importing a zip file as a new pack.
class PackImporter {
  final PackStorage _storage;
  PackImporter(this._storage);

  /// Imports [zipBytes] as a pack into [_storage].
  ///
  /// Returns the imported pack's title on success.
  ///
  /// Throws [PackConflictError] if the pack ID already exists and
  /// [replace] is false.
  /// Throws [PackImportError] for any other validation or I/O failure.
  Future<String> importZip(Uint8List zipBytes, {bool replace = false}) async {
    // 1. Decode zip
    Archive archive;
    try {
      archive = ZipDecoder().decodeBytes(zipBytes);
    } catch (e) {
      throw PackImportError('Not a valid zip file: $e');
    }

    // 2. Extract files, stripping a top-level folder if present
    final files = _extractFiles(archive);
    if (files.isEmpty) {
      throw PackImportError('The zip file is empty.');
    }

    // 3. Find and parse manifest.json
    final manifestBytes = files['manifest.json'];
    if (manifestBytes == null) {
      throw PackImportError(
        'No manifest.json found. Is this a valid GridPonder pack?\n'
        'Expected manifest.json at the zip root (or inside a single folder).',
      );
    }

    Map<String, dynamic> manifest;
    try {
      manifest = jsonDecode(utf8.decode(manifestBytes)) as Map<String, dynamic>;
    } catch (e) {
      throw PackImportError('manifest.json contains invalid JSON: $e');
    }

    // 4. Validate required fields
    final packId = manifest['id'] as String?;
    if (packId == null || packId.trim().isEmpty) {
      throw PackImportError('manifest.json is missing the required "id" field.');
    }

    final dslVersion = manifest['dslVersion'] as String? ?? '';
    if (!dslVersion.startsWith('0.')) {
      throw PackImportError(
        'DSL version "$dslVersion" is not supported by this app. '
        'Only DSL v0.x packs can be imported.',
      );
    }

    if (!files.containsKey('game.json')) {
      throw PackImportError('The pack is missing game.json.');
    }

    // 5. Block built-in packs
    if (_kBundledPackIds.contains(packId)) {
      throw PackImportError(
        '"$packId" is a built-in pack and cannot be replaced via import.',
      );
    }

    // 6. Check conflict with existing installed packs
    if (!replace) {
      final existing = await _storage.listPackIds();
      if (existing.contains(packId)) {
        final existingTitle = manifest['title'] as String? ?? packId;
        throw PackConflictError(packId, existingTitle);
      }
    }

    // 7. Persist
    await _storage.savePack(packId, files);

    return manifest['title'] as String? ?? packId;
  }

  /// Extracts archive files into a flat map of relative-path → bytes.
  /// If all files share a single top-level directory prefix, it is stripped.
  Map<String, Uint8List> _extractFiles(Archive archive) {
    final raw = <String, Uint8List>{};
    for (final file in archive.files) {
      if (!file.isFile) continue;
      final content = file.content;
      Uint8List bytes;
      if (content is Uint8List) {
        bytes = content;
      } else if (content is List<int>) {
        bytes = Uint8List.fromList(content);
      } else {
        continue;
      }
      raw[file.name] = bytes;
    }

    if (raw.isEmpty) return raw;

    // Detect one-folder-deep structure: every path starts with the same prefix.
    final paths = raw.keys.toList();
    final firstSlash = paths.first.indexOf('/');
    if (firstSlash > 0) {
      final prefix = '${paths.first.substring(0, firstSlash)}/';
      if (paths.every((p) => p.startsWith(prefix))) {
        return {
          for (final e in raw.entries)
            e.key.substring(prefix.length): e.value,
        };
      }
    }

    return raw;
  }
}
