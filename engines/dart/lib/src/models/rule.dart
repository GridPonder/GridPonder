import 'condition.dart';
import 'effect.dart';

/// A declarative event → condition → effect rule.
class RuleDef {
  final String id;
  final String on; // event type
  final Condition? where; // spatial/event filter
  final Condition? ifCond; // state condition
  final List<Effect> then;
  final int priority;
  final bool once;

  const RuleDef({
    required this.id,
    required this.on,
    this.where,
    this.ifCond,
    required this.then,
    this.priority = 0,
    this.once = false,
  });

  factory RuleDef.fromJson(Map<String, dynamic> j) => RuleDef(
        id: j['id'] as String,
        on: j['on'] as String,
        where: j['where'] != null
            ? Condition.fromJson(j['where'] as Map<String, dynamic>)
            : null,
        ifCond: j['if'] != null
            ? Condition.fromJson(j['if'] as Map<String, dynamic>)
            : null,
        then: (j['then'] as List)
            .map((e) => Effect.fromJson(e as Map<String, dynamic>))
            .toList(),
        priority: (j['priority'] as int?) ?? 0,
        once: (j['once'] as bool?) ?? false,
      );
}
