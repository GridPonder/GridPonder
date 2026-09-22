/// Non-normative theme and controls configuration.

class GestureBinding {
  final String
      gesture; // swipe_cardinal, swipe_diagonal, tap_cell, button, key_press
  final String action;
  final String? buttonId;
  final String? key; // for key_press: single character (e.g. "c") or "up"/"down"/"left"/"right"
  final Map<String, String>? paramMapping;
  final Map<String, dynamic>? params;
  final bool showSelection;

  const GestureBinding({
    required this.gesture,
    required this.action,
    this.buttonId,
    this.key,
    this.paramMapping,
    this.params,
    this.showSelection = false,
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
        showSelection: (j['showSelection'] as bool?) ?? false,
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

  /// How the avatar's own sprite is fit into its cell. Every other board
  /// sprite (tail segments, containers, ground tiles, ...) renders with
  /// `BoxFit.cover`; the avatar has historically used `BoxFit.contain`
  /// instead, which matters once a pack's avatar art is meant to butt
  /// flush against edge-connector art on adjacent-cell sprites (e.g. a
  /// vehicle head that must align pixel-for-pixel with a trailing body
  /// segment) — `contain` can letterbox the avatar inside its cell in a
  /// way `cover` does not, breaking that alignment even when the source
  /// images themselves line up. Null keeps the existing `contain` default
  /// so no pack's rendering changes unless it opts in.
  final String? fit;

  const AvatarThemeDef({
    this.visible = true,
    this.sprite,
    this.sprites = const {},
    this.fit,
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
      fit: j['fit'] as String?,
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
/// not implement effects simply ignores it. The frames come from either a
/// single sprite strip ([sheet], sliced into [frames] equal-width pieces —
/// the original convention) or a list of standalone images ([framePaths],
/// one full image per frame, no slicing) — whichever a pack's assets are
/// shaped as. Exactly one of the two is expected to be set.
class CellEffectDef {
  /// Path to the horizontal sprite strip, relative to the pack. Null when
  /// [framePaths] is used instead.
  final String? sheet;

  /// Number of equal-width frames in [sheet]. Ignored when [framePaths] is
  /// set, where the frame count is simply that list's length.
  final int frames;

  /// Standalone per-frame image paths, played in order, relative to the
  /// pack. An alternative to [sheet] for a pack whose frames were authored
  /// as separate files rather than a single strip.
  final List<String>? framePaths;

  /// Total play time for one pass through the frames, in milliseconds.
  final int durationMs;

  /// Draw scale relative to one board cell (1.0 = exactly one cell).
  final double scale;

  /// A static image, relative to the pack, kept on screen at this effect's
  /// cell after its frames finish — but only when the turn that triggered
  /// it also ended the level in a loss. Masks a lethal collision with a
  /// wreck/aftermath image instead of reverting to the raw board (which
  /// would otherwise show both parties still visually overlapping at the
  /// point of contact) for as long as the level stays lost. An effect
  /// without this set clears normally regardless of loss.
  final String? lossImage;

  /// Optional payload filter. When present the effect only plays for events
  /// whose payload matches every key here (compared as strings), which is how
  /// two effects can share one event type — e.g. `cell_transformed` with
  /// `{"toKind": "floor"}` for a cut and `{"toKind": "rubble"}` for a
  /// backfill. Absent means "any event of this type".
  final Map<String, String>? when;

  const CellEffectDef({
    this.sheet,
    this.frames = 1,
    this.framePaths,
    this.durationMs = 300,
    this.scale = 1.0,
    this.lossImage,
    this.when,
  });

  factory CellEffectDef.fromJson(Map<String, dynamic> j) {
    final framePaths = (j['framePaths'] as List?)
        ?.map((e) => e as String)
        .toList();
    return CellEffectDef(
      sheet: j['sheet'] as String?,
      frames:
          (j['frames'] as num?)?.toInt() ?? framePaths?.length ?? 1,
      framePaths: framePaths,
      durationMs: (j['durationMs'] as num?)?.toInt() ?? 300,
      scale: (j['scale'] as num?)?.toDouble() ?? 1.0,
      lossImage: j['lossImage'] as String?,
      when: (j['when'] as Map?)
          ?.map((k, v) => MapEntry(k.toString(), v.toString())),
    );
  }

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

  /// Presentation-only opt-in: when a turn moves both the avatar and an
  /// `actors`-layer NPC at once (e.g. a hazard the avatar steps behind via
  /// `avatar_navigation`'s `yieldingLayers`), play that NPC's own movement
  /// animation to completion before starting the avatar's step animation,
  /// instead of the default order (avatar walks first, NPCs animate after).
  /// False/absent preserves the existing default order for every pack that
  /// doesn't set this — it changes rendering timing only, never engine logic.
  final bool npcsAnimateBeforeAvatar;

  const ThemeDef({
    this.controls,
    this.coverImage,
    this.primaryColor,
    this.backgroundColor,
    this.boardStyle,
    this.avatar,
    this.palette = const {},
    this.effects = const {},
    this.npcsAnimateBeforeAvatar = false,
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
        npcsAnimateBeforeAvatar:
            (j['npcsAnimateBeforeAvatar'] as bool?) ?? false,
      );
}
