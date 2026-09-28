/// Goal definition (win condition).
class GoalDef {
  final String id;
  final String type;
  final Map<String, dynamic> config;
  final Map<String, dynamic>? display;

  const GoalDef({
    required this.id,
    required this.type,
    required this.config,
    this.display,
  });

  factory GoalDef.fromJson(Map<String, dynamic> j) => GoalDef(
        id: j['id'] as String,
        type: j['type'] as String,
        config: Map<String, dynamic>.from(j['config'] as Map? ?? {}),
        display: j['display'] as Map<String, dynamic>?,
      );
}

/// Lose condition definition.
class LoseConditionDef {
  final String type;
  final Map<String, dynamic> config;

  /// When true, this condition beats a goal reached on the same turn (e.g. a
  /// crash on the winning move is a loss). Otherwise it is only checked on a
  /// turn that did not win.
  final bool overridesWin;

  const LoseConditionDef({
    required this.type,
    required this.config,
    this.overridesWin = false,
  });

  factory LoseConditionDef.fromJson(Map<String, dynamic> j) =>
      LoseConditionDef(
        type: j['type'] as String,
        config: Map<String, dynamic>.from(j['config'] as Map? ?? {}),
        overridesWin: j['overridesWin'] as bool? ?? false,
      );
}
