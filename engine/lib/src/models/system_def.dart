/// A system instance declared in game.json.
class SystemDef {
  final String id;
  final String type;
  final Map<String, dynamic> config;
  final bool enabled;

  const SystemDef({
    required this.id,
    required this.type,
    required this.config,
    this.enabled = true,
  });

  factory SystemDef.fromJson(Map<String, dynamic> j) => SystemDef(
        id: j['id'] as String,
        type: j['type'] as String,
        config: Map<String, dynamic>.from(j['config'] as Map? ?? {}),
        enabled: (j['enabled'] as bool?) ?? true,
      );
}
