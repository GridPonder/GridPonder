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

  /// Optional player-facing sentence saying why the level was lost when this
  /// condition fires. Presentation only — never read to decide a loss.
  final String? description;

  const LoseConditionDef(
      {required this.type, required this.config, this.description});

  factory LoseConditionDef.fromJson(Map<String, dynamic> j) =>
      LoseConditionDef(
        type: j['type'] as String,
        config: Map<String, dynamic>.from(j['config'] as Map? ?? {}),
        description: j['description'] is String ? j['description'] as String : null,
      );
}
