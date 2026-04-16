/// A named animation sequence on an entity kind.
class AnimationDef {
  final List<String> frames;
  final int durationMs;
  final String mode; // "once" | "loop"

  const AnimationDef({
    required this.frames,
    required this.durationMs,
    this.mode = 'once',
  });

  factory AnimationDef.fromJson(Map<String, dynamic> j) => AnimationDef(
        frames: List<String>.from(j['frames'] as List),
        durationMs: j['duration'] as int,
        mode: (j['mode'] as String?) ?? 'once',
      );
}

/// Parameter definition on an entity kind.
class ParamDef {
  final String type;
  final bool required;

  const ParamDef({required this.type, this.required = false});

  factory ParamDef.fromJson(Map<String, dynamic> j) => ParamDef(
        type: j['type'] as String,
        required: (j['required'] as bool?) ?? false,
      );
}

/// Reusable entity type definition from game.json `entityKinds`.
class EntityKindDef {
  final String id;
  final String layer;
  final List<String> tags;
  final String? sprite;
  final Map<String, ParamDef> params;
  final Map<String, AnimationDef> animations;
  final String? uiName;
  final String? description;

  /// Single Unicode character (display width 1) used in text grid representations.
  /// Must be unique within a game and must not be '@' (reserved for avatar).
  /// Narrow Unicode characters (box-drawing, math symbols, etc.) are allowed;
  /// wide characters (emoji, CJK) must not be used as they break grid alignment.
  final String symbol;

  /// If set, the text symbol is taken from this instance parameter at render
  /// time instead of [symbol]. Used for entities whose symbol varies by value
  /// (e.g. number tiles show their numeric value). [symbol] still acts as the
  /// legend label and the fallback when the param is absent.
  final String? symbolParam;

  /// If set, the `{paramName}` placeholder in [sprite] is substituted with
  /// the value of this instance parameter at render time. Used for entities
  /// whose sprite varies by a param (e.g. box fragments select a PNG tile by
  /// their sides bitmask). [sprite] must contain `{paramName}`.
  final String? spriteParam;

  const EntityKindDef({
    required this.id,
    required this.layer,
    required this.tags,
    required this.symbol,
    this.sprite,
    this.params = const {},
    this.animations = const {},
    this.uiName,
    this.description,
    this.symbolParam,
    this.spriteParam,
  });

  factory EntityKindDef.fromJson(String id, Map<String, dynamic> j) {
    final symbol = j['symbol'] as String?;
    if (symbol == null || symbol.isEmpty) {
      throw FormatException(
          'Entity kind "$id" is missing required "symbol" field in game.json');
    }
    if (symbol == '@') {
      throw FormatException(
          'Entity kind "$id": symbol "@" is reserved for the avatar');
    }
    final rawParams = j['params'] as Map<String, dynamic>? ?? {};
    final rawAnims = j['animations'] as Map<String, dynamic>? ?? {};
    return EntityKindDef(
      id: id,
      layer: j['layer'] as String,
      tags: List<String>.from(j['tags'] as List? ?? []),
      sprite: j['sprite'] as String?,
      params: rawParams.map((k, v) =>
          MapEntry(k, ParamDef.fromJson(v as Map<String, dynamic>))),
      animations: rawAnims.map((k, v) =>
          MapEntry(k, AnimationDef.fromJson(v as Map<String, dynamic>))),
      uiName: j['uiName'] as String?,
      description: j['description'] as String?,
      symbol: symbol,
      symbolParam: j['symbolParam'] as String?,
      spriteParam: j['spriteParam'] as String?,
    );
  }

  bool hasTag(String tag) => tags.contains(tag);
}

/// An entity instance placed on the board. Immutable value.
class EntityInstance {
  final String kind;
  final Map<String, dynamic> params;

  const EntityInstance(this.kind, [this.params = const {}]);

  /// Handles both `"rock"` (string) and `{"kind":"portal","channel":"blue"}` (map).
  factory EntityInstance.fromJson(dynamic json) {
    if (json is String) return EntityInstance(json);
    if (json is Map<String, dynamic>) {
      final kind = json['kind'] as String;
      final params = Map<String, dynamic>.from(json)..remove('kind');
      return EntityInstance(kind, params);
    }
    throw FormatException('Expected string or map for entity, got $json');
  }

  Map<String, dynamic> toJson() {
    if (params.isEmpty) return {'kind': kind};
    return {'kind': kind, ...params};
  }

  dynamic param(String key) => params[key];

  EntityInstance copyWith({String? kind, Map<String, dynamic>? params}) =>
      EntityInstance(kind ?? this.kind, params ?? Map.from(this.params));

  @override
  bool operator ==(Object other) =>
      other is EntityInstance &&
      other.kind == kind &&
      _mapsEqual(other.params, params);

  bool _mapsEqual(Map a, Map b) {
    if (a.length != b.length) return false;
    for (final k in a.keys) {
      if (a[k] != b[k]) return false;
    }
    return true;
  }

  @override
  int get hashCode => Object.hash(kind, params.toString());

  @override
  String toString() =>
      params.isEmpty ? kind : '$kind(${params.entries.map((e) => '${e.key}:${e.value}').join(',')})';
}
