/// Non-normative theme and controls configuration.

class GestureBinding {
  final String
      gesture; // swipe_cardinal, swipe_diagonal, tap_cell, button, key_press
  final String action;
  final String? buttonId;
  final String? key; // for key_press: single character, e.g. "c"
  final Map<String, String>? paramMapping;
  final Map<String, dynamic>? params;

  const GestureBinding({
    required this.gesture,
    required this.action,
    this.buttonId,
    this.key,
    this.paramMapping,
    this.params,
  });

  factory GestureBinding.fromJson(Map<String, dynamic> j) => GestureBinding(
        gesture: j['gesture'] as String,
        action: j['action'] as String,
        buttonId: j['buttonId'] as String?,
        key: j['key'] as String?,
        paramMapping: j['paramMapping'] != null
            ? Map<String, String>.from(j['paramMapping'] as Map)
            : null,
        params: j['params'] as Map<String, dynamic>?,
      );
}

class ControlsDef {
  final List<GestureBinding> gestureMap;
  const ControlsDef({required this.gestureMap});

  factory ControlsDef.fromJson(Map<String, dynamic> j) => ControlsDef(
        gestureMap: (j['gestureMap'] as List? ?? [])
            .map((e) => GestureBinding.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

class BoardStyleDef {
  final int cellSize;
  final int cellSpacing;
  final int borderRadius;
  final String gridLineColor;
  final bool showGridLines;

  const BoardStyleDef({
    this.cellSize = 64,
    this.cellSpacing = 2,
    this.borderRadius = 4,
    this.gridLineColor = '#333333',
    this.showGridLines = true,
  });

  factory BoardStyleDef.fromJson(Map<String, dynamic> j) => BoardStyleDef(
        cellSize: (j['cellSize'] as int?) ?? 64,
        cellSpacing: (j['cellSpacing'] as int?) ?? 2,
        borderRadius: (j['borderRadius'] as int?) ?? 4,
        gridLineColor: (j['gridLineColor'] as String?) ?? '#333333',
        showGridLines: (j['showGridLines'] as bool?) ?? true,
      );
}

/// Avatar sprite definition: either a string path, an animation def,
/// or a {mirror: "direction"} reference.
class AvatarSpriteEntry {
  final String? staticPath;
  final List<String>? frames;
  final int? durationMs;
  final String? mode;
  final String? mirror;

  const AvatarSpriteEntry({
    this.staticPath,
    this.frames,
    this.durationMs,
    this.mode,
    this.mirror,
  });

  factory AvatarSpriteEntry.fromJson(dynamic j) {
    if (j is String) return AvatarSpriteEntry(staticPath: j);
    if (j is Map<String, dynamic>) {
      if (j.containsKey('mirror')) {
        return AvatarSpriteEntry(mirror: j['mirror'] as String);
      }
      return AvatarSpriteEntry(
        frames: List<String>.from(j['frames'] as List),
        durationMs: j['duration'] as int?,
        mode: j['mode'] as String?,
      );
    }
    throw FormatException('Unknown avatar sprite entry: $j');
  }

  bool get isStatic => staticPath != null;
  bool get isAnimated => frames != null;
  bool get isMirror => mirror != null;
}

class AvatarThemeDef {
  final bool visible;
  final String? sprite; // fallback
  final Map<String, Map<String, AvatarSpriteEntry>>
      sprites; // state → dir → entry

  const AvatarThemeDef({
    this.visible = true,
    this.sprite,
    this.sprites = const {},
  });

  factory AvatarThemeDef.fromJson(Map<String, dynamic> j) {
    final rawSprites = j['sprites'] as Map<String, dynamic>? ?? {};
    final sprites = <String, Map<String, AvatarSpriteEntry>>{};
    for (final state in rawSprites.entries) {
      final dirs = state.value as Map<String, dynamic>;
      sprites[state.key] =
          dirs.map((k, v) => MapEntry(k, AvatarSpriteEntry.fromJson(v)));
    }
    return AvatarThemeDef(
      visible: (j['visible'] as bool?) ?? true,
      sprite: j['sprite'] as String?,
      sprites: sprites,
    );
  }

  /// Resolve sprite for (state, direction). Falls back to idle, then static sprite.
  AvatarSpriteEntry? resolve(String state, String direction) {
    return sprites[state]?[direction] ??
        sprites['idle']?[direction] ??
        (sprite != null ? AvatarSpriteEntry(staticPath: sprite) : null);
  }
}

/// A sprite-strip animation played at a cell in response to an engine event.
///
/// Purely presentational: the engine never reads this, and a client that does
/// not implement effects simply ignores it. The strip is a single image of
/// [frames] equal-width frames laid out left to right.
class CellEffectDef {
  /// Path to the horizontal sprite strip, relative to the pack.
  final String sheet;

  /// Number of equal-width frames in the strip.
  final int frames;

  /// Total play time for one pass through the strip, in milliseconds.
  final int durationMs;

  /// Draw scale relative to one board cell (1.0 = exactly one cell).
  final double scale;

  /// Optional payload filter. When present the effect only plays for events
  /// whose payload matches every key here (compared as strings), which is how
  /// two effects can share one event type — e.g. `cell_transformed` with
  /// `{"toKind": "floor"}` for a cut and `{"toKind": "rubble"}` for a
  /// backfill. Absent means "any event of this type".
  final Map<String, String>? when;

  const CellEffectDef({
    required this.sheet,
    this.frames = 1,
    this.durationMs = 300,
    this.scale = 1.0,
    this.when,
  });

  factory CellEffectDef.fromJson(Map<String, dynamic> j) => CellEffectDef(
        sheet: j['sheet'] as String,
        frames: (j['frames'] as num?)?.toInt() ?? 1,
        durationMs: (j['durationMs'] as num?)?.toInt() ?? 300,
        scale: (j['scale'] as num?)?.toDouble() ?? 1.0,
        when: (j['when'] as Map?)
            ?.map((k, v) => MapEntry(k.toString(), v.toString())),
      );

  /// Whether this effect should play for [payload].
  bool matches(Map<String, dynamic> payload) {
    final filter = when;
    if (filter == null) return true;
    for (final entry in filter.entries) {
      if (payload[entry.key]?.toString() != entry.value) return false;
    }
    return true;
  }
}

/// Full theme definition.
class ThemeDef {
  final ControlsDef? controls;
  final String? coverImage;
  final String? primaryColor;
  final String? backgroundColor;
  final BoardStyleDef? boardStyle;
  final AvatarThemeDef? avatar;

  /// Optional event-driven cell effects: engine event type → the sprite-strip
  /// animations played at that event's position. E.g. `cell_transformed` to
  /// flash a burst wherever a capture flipped a cell.
  ///
  /// A type may map to a single object or to a list; both parse to a list, so
  /// several effects can share one event type and discriminate with their
  /// `when` filter. The first matching entry wins.
  final Map<String, List<CellEffectDef>> effects;

  /// Optional named-colour palette: maps colour names (e.g. "red", "teal")
  /// to CSS hex strings. Used by the renderer when an entity or action
  /// references a colour by name. Names not declared here fall back to the
  /// renderer's built-in defaults — packs only need to declare the names
  /// they want to override or add.
  final Map<String, String> palette;

  const ThemeDef({
    this.controls,
    this.coverImage,
    this.primaryColor,
    this.backgroundColor,
    this.boardStyle,
    this.avatar,
    this.palette = const {},
    this.effects = const {},
  });

  factory ThemeDef.fromJson(Map<String, dynamic> j) => ThemeDef(
        controls: j['controls'] != null
            ? ControlsDef.fromJson(j['controls'] as Map<String, dynamic>)
            : null,
        coverImage: j['coverImage'] as String?,
        primaryColor: j['primaryColor'] as String?,
        backgroundColor: j['backgroundColor'] as String?,
        boardStyle: j['boardStyle'] != null
            ? BoardStyleDef.fromJson(j['boardStyle'] as Map<String, dynamic>)
            : null,
        avatar: j['avatar'] != null
            ? AvatarThemeDef.fromJson(j['avatar'] as Map<String, dynamic>)
            : null,
        palette: ((j['palette'] as Map?) ?? const {})
            .map((k, v) => MapEntry(k.toString(), v.toString())),
        // Accepts either a single object or a list per event type, so packs
        // written before multiple effects per type keep parsing unchanged.
        effects: ((j['effects'] as Map?) ?? const {}).map(
          (k, v) => MapEntry(
            k.toString(),
            v is List
                ? [
                    for (final e in v)
                      if (e is Map<String, dynamic>) CellEffectDef.fromJson(e),
                  ]
                : [CellEffectDef.fromJson(v as Map<String, dynamic>)],
          ),
        ),
      );
}
