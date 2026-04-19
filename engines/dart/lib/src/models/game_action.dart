import 'direction.dart';

/// An abstract player intent with parameters.
class GameAction {
  final String actionId;
  final Map<String, dynamic> params;

  const GameAction(this.actionId, [this.params = const {}]);

  /// Parse from gold path format: {"action":"move","direction":"right"}
  factory GameAction.fromJson(Map<String, dynamic> j) {
    final id = j['action'] as String? ?? j['type'] as String? ?? '';
    final params = Map<String, dynamic>.from(j)
      ..remove('action')
      ..remove('type');
    return GameAction(id, params);
  }

  /// Parse from shorthand string: cardinal directions expand to move+direction,
  /// any other string becomes a param-less action (e.g. "clone", "rotate").
  factory GameAction.fromShorthand(String s) {
    const cardinals = {'up', 'down', 'left', 'right'};
    if (cardinals.contains(s)) return GameAction('move', {'direction': s});
    return GameAction(s);
  }

  Direction? get direction {
    final d = params['direction'];
    if (d == null) return null;
    return Direction.fromJson(d as String);
  }

  String? get directionStr => params['direction'] as String?;

  Map<String, dynamic> toJson() => {'action': actionId, ...params};

  @override
  String toString() {
    if (params.isEmpty) return actionId;
    return '$actionId(${params.entries.map((e) => '${e.key}:${e.value}').join(',')})';
  }
}
