/// Non-normative theme and controls configuration.

class GestureBinding {
  final String gesture; // swipe_cardinal, swipe_diagonal, tap_cell, button
  final String action;
  final String? buttonId;
  final Map<String, String>? paramMapping;
  final Map<String, dynamic>? params;

  const GestureBinding({
    required this.gesture,
    required this.action,
    this.buttonId,
    this.paramMapping,
    this.params,
  });

  factory GestureBinding.fromJson(Map<String, dynamic> j) => GestureBinding(
        gesture: j['gesture'] as String,
        action: j['action'] as String,
        buttonId: j['buttonId'] as String?,
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
  final Map<String, Map<String, AvatarSpriteEntry>> sprites; // state → dir → entry

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

/// Full theme definition.
class ThemeDef {
  final ControlsDef? controls;
  final String? coverImage;
  final String? primaryColor;
  final String? backgroundColor;
  final BoardStyleDef? boardStyle;
  final AvatarThemeDef? avatar;

  const ThemeDef({
    this.controls,
    this.coverImage,
    this.primaryColor,
    this.backgroundColor,
    this.boardStyle,
    this.avatar,
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
      );
}
