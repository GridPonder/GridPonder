/// Effect definitions — state mutations applied when a rule fires.
/// Fields may be literal values or "$ref" strings resolved at execution time.
/// The executor resolves any String starting with "$" before applying.

class Effect {
  final String type;
  final Map<String, dynamic> data;

  const Effect(this.type, this.data);

  factory Effect.fromJson(Map<String, dynamic> j) {
    if (j.containsKey('spawn')) return Effect('spawn', j['spawn'] as Map<String, dynamic>);
    if (j.containsKey('destroy')) return Effect('destroy', j['destroy'] as Map<String, dynamic>);
    if (j.containsKey('transform')) return Effect('transform', j['transform'] as Map<String, dynamic>);
    if (j.containsKey('move_entity')) return Effect('move_entity', j['move_entity'] as Map<String, dynamic>);
    if (j.containsKey('set_cell')) return Effect('set_cell', j['set_cell'] as Map<String, dynamic>);
    if (j.containsKey('release_from_emitter')) return Effect('release_from_emitter', j['release_from_emitter'] as Map<String, dynamic>);
    if (j.containsKey('apply_gravity')) return Effect('apply_gravity', j['apply_gravity'] as Map<String, dynamic>);
    if (j.containsKey('set_variable')) return Effect('set_variable', j['set_variable'] as Map<String, dynamic>);
    if (j.containsKey('increment_variable')) return Effect('increment_variable', j['increment_variable'] as Map<String, dynamic>);
    if (j.containsKey('set_inventory')) return Effect('set_inventory', j['set_inventory'] as Map<String, dynamic>);
    if (j.containsKey('clear_inventory')) return Effect('clear_inventory', j['clear_inventory'] as Map<String, dynamic>? ?? {});
    if (j.containsKey('resolve_move')) return Effect('resolve_move', j['resolve_move'] as Map<String, dynamic>? ?? {});
    throw FormatException('Unknown effect: ${j.keys.first}');
  }

  @override
  String toString() => '$type($data)';
}
