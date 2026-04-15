import 'entity.dart';
import 'position.dart';

/// Layer definition from game.json.
class LayerDef {
  final String id;
  final String occupancy; // "exactly_one" | "zero_or_one"
  final String? defaultKind;

  const LayerDef({
    required this.id,
    required this.occupancy,
    this.defaultKind,
  });

  factory LayerDef.fromJson(Map<String, dynamic> j) => LayerDef(
        id: j['id'] as String,
        occupancy: j['occupancy'] as String,
        defaultKind: j['default'] as String?,
      );

  bool get isExactlyOne => occupancy == 'exactly_one';
}

/// Runtime board layer — a dense 2D grid of entity instances.
/// Internal storage: [y][x], row-major.
class BoardLayer {
  final int width;
  final int height;
  final List<List<EntityInstance?>> _cells;

  BoardLayer(this.width, this.height, this._cells);

  factory BoardLayer.empty(int width, int height, [String? defaultKind]) {
    final cells = List.generate(
      height,
      (_) => List<EntityInstance?>.generate(
        width,
        (_) => defaultKind != null ? EntityInstance(defaultKind) : null,
      ),
    );
    return BoardLayer(width, height, cells);
  }

  /// Parse from JSON value: either a 2D dense array or sparse object.
  factory BoardLayer.fromJson(dynamic json, int width, int height,
      {String? defaultKind}) {
    final layer = BoardLayer.empty(width, height, defaultKind);

    if (json == null) return layer;

    if (json is List) {
      // Dense format: json[y][x]
      for (int y = 0; y < height && y < json.length; y++) {
        final row = json[y] as List?;
        if (row == null) continue;
        for (int x = 0; x < width && x < row.length; x++) {
          if (row[x] == null) {
            layer._cells[y][x] = null;
          } else {
            layer._cells[y][x] = EntityInstance.fromJson(row[x]);
          }
        }
      }
      return layer;
    }

    if (json is Map<String, dynamic> && json['format'] == 'sparse') {
      // Sparse format
      final entries = json['entries'] as List? ?? [];
      for (final entry in entries) {
        final e = entry as Map<String, dynamic>;
        final pos = Position.fromJson(e['position']);
        if (!pos.isValid(width, height)) continue;
        final params = Map<String, dynamic>.from(e)..remove('position');
        final kind = params.remove('kind') as String?;
        if (kind != null) {
          layer._cells[pos.y][pos.x] = EntityInstance(kind, params);
        }
      }
      return layer;
    }

    throw FormatException('Unknown layer format: $json');
  }

  EntityInstance? getAt(Position pos) {
    if (!pos.isValid(width, height)) return null;
    return _cells[pos.y][pos.x];
  }

  void setAt(Position pos, EntityInstance? entity) {
    if (!pos.isValid(width, height)) return;
    _cells[pos.y][pos.x] = entity;
  }

  bool isEmpty(Position pos) => getAt(pos) == null;

  /// Deep copy.
  BoardLayer copy() {
    final copied = List.generate(
      height,
      (y) => List<EntityInstance?>.from(_cells[y]),
    );
    return BoardLayer(width, height, copied);
  }

  /// Iterate all non-null entities with their positions.
  Iterable<MapEntry<Position, EntityInstance>> entries() sync* {
    for (int y = 0; y < height; y++) {
      for (int x = 0; x < width; x++) {
        final e = _cells[y][x];
        if (e != null) yield MapEntry(Position(x, y), e);
      }
    }
  }
}
