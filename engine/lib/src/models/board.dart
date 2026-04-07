import 'entity.dart';
import 'layer.dart';
import 'position.dart';

/// A multi-cell object instance (e.g. pipe).
class MultiCellObjectInstance {
  final String id;
  final String kind;
  final List<Position> cells;
  Map<String, dynamic> params; // mutable (queue state, etc.)

  /// Optional per-cell sprite paths (pack-relative, e.g. "assets/pipe_straight_h.png").
  /// Absent when the level JSON uses bare [x,y] arrays for cells.
  final Map<Position, String> cellSprites;

  MultiCellObjectInstance({
    required this.id,
    required this.kind,
    required this.cells,
    Map<String, dynamic>? params,
    Map<Position, String>? cellSprites,
  })  : params = params ?? {},
        cellSprites = cellSprites ?? {};

  factory MultiCellObjectInstance.fromJson(Map<String, dynamic> j) {
    final cellsList = <Position>[];
    final sprites = <Position, String>{};
    for (final c in j['cells'] as List) {
      if (c is List) {
        // Legacy format: [x, y]
        cellsList.add(Position.fromJson(c));
      } else if (c is Map) {
        // Extended format: {"position": [x,y], "sprite": "assets/pipe_straight_h.png"}
        final pos = Position.fromJson(c['position'] as List);
        cellsList.add(pos);
        final sprite = c['sprite'] as String?;
        if (sprite != null) sprites[pos] = sprite;
      }
    }
    return MultiCellObjectInstance(
      id: j['id'] as String,
      kind: j['kind'] as String,
      cells: cellsList,
      params: Map<String, dynamic>.from(j['params'] as Map? ?? {}),
      cellSprites: sprites,
    );
  }

  MultiCellObjectInstance copy() => MultiCellObjectInstance(
        id: id,
        kind: kind,
        cells: List.from(cells),
        params: Map<String, dynamic>.from(params),
        cellSprites: Map.from(cellSprites),
      );

  dynamic param(String key) => params[key];
}

/// The full game board: all layers + multi-cell objects.
class Board {
  final int width;
  final int height;
  final Map<String, BoardLayer> layers;
  final List<MultiCellObjectInstance> multiCellObjects;

  Board({
    required this.width,
    required this.height,
    required this.layers,
    required this.multiCellObjects,
  });

  factory Board.fromJson(
    Map<String, dynamic> j,
    List<LayerDef> layerDefs,
  ) {
    final size = j['size'] as List;
    final w = size[0] as int;
    final h = size[1] as int;
    final rawLayers = j['layers'] as Map<String, dynamic>? ?? {};

    final layers = <String, BoardLayer>{};
    for (final def in layerDefs) {
      final raw = rawLayers[def.id];
      layers[def.id] = BoardLayer.fromJson(
        raw,
        w,
        h,
        defaultKind: def.isExactlyOne ? (def.defaultKind ?? 'empty') : null,
      );
    }

    final mcos = (j['multiCellObjects'] as List? ?? [])
        .map((e) => MultiCellObjectInstance.fromJson(e as Map<String, dynamic>))
        .toList();

    return Board(
      width: w,
      height: h,
      layers: layers,
      multiCellObjects: mcos,
    );
  }

  // --- Accessors ---

  EntityInstance? getEntity(String layerId, Position pos) =>
      layers[layerId]?.getAt(pos);

  void setEntity(String layerId, Position pos, EntityInstance? entity) =>
      layers[layerId]?.setAt(pos, entity);

  bool hasTagAt(
      String layerId, Position pos, String tag, Map<String, EntityKindDef> kinds) {
    final entity = getEntity(layerId, pos);
    if (entity == null) return false;
    final def = kinds[entity.kind];
    return def?.hasTag(tag) ?? false;
  }

  bool isVoid(Position pos) {
    final ground = getEntity('ground', pos);
    return ground?.kind == 'void';
  }

  bool isInBounds(Position pos) => pos.isValid(width, height);

  MultiCellObjectInstance? getMultiCellObject(String id) {
    for (final mco in multiCellObjects) {
      if (mco.id == id) return mco;
    }
    return null;
  }

  /// Deep copy.
  Board copy() {
    final copiedLayers = layers.map((k, v) => MapEntry(k, v.copy()));
    final copiedMcos = multiCellObjects.map((m) => m.copy()).toList();
    return Board(
      width: width,
      height: height,
      layers: copiedLayers,
      multiCellObjects: copiedMcos,
    );
  }
}
