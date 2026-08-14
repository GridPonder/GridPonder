import 'entity.dart';
import 'layer.dart';
import 'game_action.dart';
import 'rule.dart';
import 'system_def.dart';

/// An action parameter definition.
class ActionParamDef {
  final String type;
  final List<String>? values;
  const ActionParamDef({required this.type, this.values});
  factory ActionParamDef.fromJson(Map<String, dynamic> j) => ActionParamDef(
      type: j['type'] as String,
      values:
          j['values'] != null ? List<String>.from(j['values'] as List) : null);
}

/// A declared action type in game.json.
class ActionDef {
  final String id;
  final Map<String, ActionParamDef> params;

  /// If set, this action is only offered when this entity kind is present on
  /// the current board. Used to suppress inapplicable actions in the LLM
  /// prompt (e.g. flood_purple when no purple cells are on the board).
  final String? entityKind;

  /// Optional render hint: a colour name (resolved via the renderer's named
  /// palette) that the controls UI uses to draw a swatch button instead of
  /// the default action button. Lets a pack expose colour-pick actions
  /// (e.g. the flood_<colour> actions in flood_colors) without the renderer
  /// having to know the action's id-prefix convention.
  final String? color;

  const ActionDef({
    required this.id,
    required this.params,
    this.entityKind,
    this.color,
  });
  factory ActionDef.fromJson(Map<String, dynamic> j) {
    final rawParams = j['params'] as Map<String, dynamic>? ?? {};
    return ActionDef(
      id: j['id'] as String,
      params: rawParams.map((k, v) =>
          MapEntry(k, ActionParamDef.fromJson(v as Map<String, dynamic>))),
      entityKind: j['entityKind'] as String?,
      color: j['color'] as String?,
    );
  }
}

/// A level sequence entry (type: "level" or "story").
class SequenceEntry {
  final String type;
  final String? ref; // for level entries
  final String? title;
  final String? text;
  final String? image;

  const SequenceEntry(
      {required this.type, this.ref, this.title, this.text, this.image});

  factory SequenceEntry.fromJson(Map<String, dynamic> j) => SequenceEntry(
        type: j['type'] as String,
        ref: j['ref'] as String?,
        title: j['title'] as String?,
        text: j['text'] as String?,
        image: j['image'] as String?,
      );
}

/// One live value from `state.variables` surfaced to the player as a chip.
///
/// Generic on purpose: any pack with a runtime counter worth showing (an edit
/// budget, a score, a `sonar` distance reading) can declare one without the
/// app having to learn that pack's vocabulary.
class GameReadout {
  /// Name of the variable in `state.variables` to display.
  final String variable;

  /// Short label shown beside the value.
  final String label;

  /// Optional palette key used to tint the chip, so a reading can be
  /// colour-matched to the entity it describes.
  final String? color;

  /// Optional sentinel: when the variable equals this, the chip shows a dash
  /// instead of the raw number — e.g. `sonar`'s `-1` for "no target".
  final int? blankWhen;

  const GameReadout({
    required this.variable,
    required this.label,
    this.color,
    this.blankWhen,
  });

  factory GameReadout.fromJson(Map<String, dynamic> j) => GameReadout(
        variable: j['variable'] as String? ?? '',
        label: j['label'] as String? ?? '',
        color: j['color'] as String?,
        blankWhen: (j['blankWhen'] as num?)?.toInt(),
      );
}

/// UI display configuration for a game.
class GameUiConfig {
  /// Whether to show the goal panel during play.
  final bool showGoal;

  /// Whether to show the guide panel during play.
  final bool showGuide;

  /// Live variable chips shown during play, in declaration order.
  final List<GameReadout> readouts;

  const GameUiConfig({
    this.showGoal = false,
    this.showGuide = false,
    this.readouts = const [],
  });

  factory GameUiConfig.fromJson(Map<String, dynamic>? j) {
    if (j == null) return const GameUiConfig();
    final raw = j['readouts'];
    return GameUiConfig(
      showGoal: (j['showGoal'] as bool?) ?? false,
      showGuide: (j['showGuide'] as bool?) ?? false,
      readouts: raw is! List
          ? const []
          : [
              for (final r in raw)
                if (r is Map<String, dynamic>) GameReadout.fromJson(r),
            ].where((r) => r.variable.isNotEmpty).toList(),
    );
  }
}

/// Default values applied to levels.
class GameDefaults {
  final bool avatarEnabled;
  final String avatarFacing;
  final int maxCascadeDepth;

  const GameDefaults({
    this.avatarEnabled = true,
    this.avatarFacing = 'right',
    this.maxCascadeDepth = 3,
  });

  factory GameDefaults.fromJson(Map<String, dynamic>? j) {
    if (j == null) return const GameDefaults();
    final avatar = j['avatar'] as Map<String, dynamic>?;
    return GameDefaults(
      avatarEnabled: (avatar?['enabled'] as bool?) ?? true,
      avatarFacing: (avatar?['facing'] as String?) ?? 'right',
      maxCascadeDepth: (j['maxCascadeDepth'] as int?) ?? 3,
    );
  }
}

/// Parsed game.json — the shared game definition.
/// [id], [title] and [description] are injected from manifest.json by [PackLoader],
/// not read from game.json.
class GameDefinition {
  final String id;
  final String title;
  final String description;
  final List<LayerDef> layers;
  final List<ActionDef> actions;
  final Map<String, EntityKindDef> entityKinds;
  final List<SystemDef> systems;
  final List<RuleDef> rules;
  final List<SequenceEntry> levelSequence;
  final GameDefaults defaults;
  final GameUiConfig ui;

  /// Per-game goal-text overrides keyed by goal id. See goal_descriptions
  /// in the Python engine for parity. Lets a pack supply a precise
  /// mechanical description in place of the renderer's generic auto-generated text.
  final Map<String, String> goalDescriptions;

  const GameDefinition({
    required this.id,
    required this.title,
    this.description = '',
    required this.layers,
    required this.actions,
    required this.entityKinds,
    required this.systems,
    required this.rules,
    required this.levelSequence,
    required this.defaults,
    this.ui = const GameUiConfig(),
    this.goalDescriptions = const {},
  });

  factory GameDefinition.fromJson(
    Map<String, dynamic> j, {
    String id = '',
    String title = '',
    String description = '',
  }) {
    final rawKinds = j['entityKinds'] as Map<String, dynamic>? ?? {};
    final entityKinds = rawKinds.map((k, v) =>
        MapEntry(k, EntityKindDef.fromJson(k, v as Map<String, dynamic>)));

    // Validate text symbols are unique within this game.
    final seen = <String, String>{}; // symbol -> kindId
    for (final kind in entityKinds.values) {
      final sym = kind.symbol;
      if (seen.containsKey(sym)) {
        throw FormatException('Duplicate symbol "$sym" on entity kinds '
            '"${seen[sym]}" and "${kind.id}" in game "$id"');
      }
      seen[sym] = kind.id;
    }

    return GameDefinition(
      id: id,
      title: title,
      description: description,
      layers: (j['layers'] as List? ?? [])
          .map((e) => LayerDef.fromJson(e as Map<String, dynamic>))
          .toList(),
      actions: (j['actions'] as List? ?? [])
          .map((e) => ActionDef.fromJson(e as Map<String, dynamic>))
          .toList(),
      entityKinds: entityKinds,
      systems: (j['systems'] as List? ?? [])
          .map((e) => SystemDef.fromJson(e as Map<String, dynamic>))
          .toList(),
      rules: (j['rules'] as List? ?? [])
          .map((e) => RuleDef.fromJson(e as Map<String, dynamic>))
          .toList(),
      levelSequence: (j['levelSequence'] as List? ?? [])
          .map((e) => SequenceEntry.fromJson(e as Map<String, dynamic>))
          .toList(),
      defaults: GameDefaults.fromJson(j['defaults'] as Map<String, dynamic>?),
      ui: GameUiConfig.fromJson(j['ui'] as Map<String, dynamic>?),
      goalDescriptions: ((j['goalDescriptions'] as Map?) ?? const {})
          .map((k, v) => MapEntry(k as String, v as String)),
    );
  }

  EntityKindDef? getKind(String name) => entityKinds[name];

  bool hasTag(String kindName, String tag) =>
      entityKinds[kindName]?.hasTag(tag) ?? false;

  SystemDef? getSystem(String id) {
    for (final s in systems) {
      if (s.id == id) return s;
    }
    return null;
  }

  /// Returns config for system with given id, with optional per-level overrides merged in.
  Map<String, dynamic> systemConfig(
      String id, Map<String, Map<String, dynamic>>? overrides) {
    final base = getSystem(id)?.config ?? {};
    final override = overrides?[id];
    if (override == null) return base;
    return {...base, ...override};
  }

  GameDefinition withSystemOverrides(
      Map<String, Map<String, dynamic>>? overrides) {
    if (overrides == null || overrides.isEmpty) return this;

    return GameDefinition(
      id: id,
      title: title,
      description: description,
      layers: layers,
      actions: actions,
      entityKinds: entityKinds,
      systems: [
        for (final system in systems)
          () {
            final override = overrides[system.id];
            if (override == null) return system;
            final configOverride = Map<String, dynamic>.from(override)
              ..remove('enabled');
            return SystemDef(
              id: system.id,
              type: system.type,
              config: {...system.config, ...configOverride},
              enabled: override['enabled'] as bool? ?? system.enabled,
            );
          }(),
      ],
      rules: rules,
      levelSequence: levelSequence,
      defaults: defaults,
      ui: ui,
      goalDescriptions: goalDescriptions,
    );
  }

  bool isValidAction(GameAction action) =>
      actions.any((a) => a.id == action.actionId);
}
