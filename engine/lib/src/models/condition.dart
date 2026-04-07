import 'position.dart';

// Forward declarations to avoid circular imports — EvalContext is in rules/
// We use duck-typing via abstract interface instead.

/// Evaluation context passed to condition.evaluate().
abstract class ConditionContext {
  Map<String, dynamic> get eventPayload;
  String get eventType;

  // Board state accessors
  String? entityKindAt(String layerId, Position pos);
  bool hasTagAt(String layerId, Position pos, String tag);
  bool isCellEmpty(String layerId, Position pos);

  // Avatar state
  bool get avatarEnabled;
  Position? get avatarPosition;
  String? get avatarItem;

  // Variables
  dynamic variable(String name);

  // Emitters
  bool emitterHasNext(String emitterId);

  // Count entities on board
  int countEntities({String? kind, String? tag, String? layerId});
}

/// Base condition type.
abstract class Condition {
  bool evaluate(ConditionContext ctx);

  factory Condition.fromJson(Map<String, dynamic> j) {
    if (j.containsKey('position')) return PositionCondition.fromJson(j);
    if (j.containsKey('position_has_tag')) return PositionHasTagCondition.fromJson(j);
    if (j.containsKey('event')) return EventCondition.fromJson(j);
    if (j.containsKey('cell')) return CellCondition.fromJson(j);
    if (j.containsKey('avatar')) return AvatarCondition.fromJson(j);
    if (j.containsKey('variable')) return VariableCondition.fromJson(j);
    if (j.containsKey('emitter_has_next')) return EmitterHasNextCondition.fromJson(j);
    if (j.containsKey('board_count')) return BoardCountCondition.fromJson(j);
    if (j.containsKey('all_of')) return AllOfCondition.fromJson(j);
    if (j.containsKey('any_of')) return AnyOfCondition.fromJson(j);
    if (j.containsKey('not')) return NotCondition.fromJson(j);
    throw FormatException('Unknown condition: $j');
  }
}

/// Match against event's primary position (used in `where`).
class PositionCondition implements Condition {
  final Position position;
  PositionCondition(this.position);
  factory PositionCondition.fromJson(Map<String, dynamic> j) =>
      PositionCondition(Position.fromJson(j['position']));

  @override
  bool evaluate(ConditionContext ctx) {
    final ep = ctx.eventPayload['position'];
    if (ep == null) return false;
    final evtPos = ep is Position ? ep : Position.fromJson(ep);
    return evtPos == position;
  }
}

/// The event position's cell has a specific tag on a layer (used in `where`).
class PositionHasTagCondition implements Condition {
  final String layer;
  final String tag;
  PositionHasTagCondition(this.layer, this.tag);
  factory PositionHasTagCondition.fromJson(Map<String, dynamic> j) {
    final c = j['position_has_tag'] as Map<String, dynamic>;
    return PositionHasTagCondition(c['layer'] as String, c['tag'] as String);
  }

  @override
  bool evaluate(ConditionContext ctx) {
    final ep = ctx.eventPayload['position'];
    if (ep == null) return false;
    final pos = ep is Position ? ep : Position.fromJson(ep);
    return ctx.hasTagAt(layer, pos, tag);
  }
}

/// Match fields from the event payload (used in `where`).
class EventCondition implements Condition {
  final String? kind;
  final String? param;
  final dynamic equals;
  EventCondition({this.kind, this.param, this.equals});
  factory EventCondition.fromJson(Map<String, dynamic> j) {
    final c = j['event'] as Map<String, dynamic>;
    return EventCondition(
      kind: c['kind'] as String?,
      param: c['param'] as String?,
      equals: c['equals'],
    );
  }

  @override
  bool evaluate(ConditionContext ctx) {
    if (kind != null && ctx.eventPayload['kind'] != kind) return false;
    if (param != null && equals != null) {
      if (ctx.eventPayload[param!] != equals) return false;
    }
    return true;
  }
}

/// Check a cell's content on a specific layer (used in `if`).
class CellCondition implements Condition {
  final Position position;
  final String layer;
  final String? kind;
  final bool? isEmpty;
  final String? hasTag;

  CellCondition({
    required this.position,
    required this.layer,
    this.kind,
    this.isEmpty,
    this.hasTag,
  });

  factory CellCondition.fromJson(Map<String, dynamic> j) {
    final c = j['cell'] as Map<String, dynamic>;
    return CellCondition(
      position: Position.fromJson(c['position']),
      layer: c['layer'] as String,
      kind: c['kind'] as String?,
      isEmpty: c['isEmpty'] as bool?,
      hasTag: c['hasTag'] as String?,
    );
  }

  @override
  bool evaluate(ConditionContext ctx) {
    if (kind != null) {
      return ctx.entityKindAt(layer, position) == kind;
    }
    if (isEmpty != null) {
      return ctx.isCellEmpty(layer, position) == isEmpty;
    }
    if (hasTag != null) {
      return ctx.hasTagAt(layer, position, hasTag!);
    }
    return false;
  }
}

/// Check avatar state (used in `if`).
class AvatarCondition implements Condition {
  final Position? at;
  final dynamic hasItem; // String | bool

  AvatarCondition({this.at, this.hasItem});

  factory AvatarCondition.fromJson(Map<String, dynamic> j) {
    final c = j['avatar'] as Map<String, dynamic>;
    return AvatarCondition(
      at: c['at'] != null ? Position.fromJson(c['at']) : null,
      hasItem: c['hasItem'],
    );
  }

  @override
  bool evaluate(ConditionContext ctx) {
    if (at != null && ctx.avatarPosition != at) return false;
    if (hasItem != null) {
      final item = ctx.avatarItem;
      if (hasItem is bool) {
        final wantItem = hasItem as bool;
        if (wantItem && item == null) return false;
        if (!wantItem && item != null) return false;
      } else if (hasItem is String) {
        if (item != hasItem) return false;
      }
    }
    return true;
  }
}

/// Check a state variable (used in `if`).
class VariableCondition implements Condition {
  final String name;
  final String op;
  final dynamic value;

  VariableCondition({required this.name, required this.op, required this.value});

  factory VariableCondition.fromJson(Map<String, dynamic> j) {
    final c = j['variable'] as Map<String, dynamic>;
    return VariableCondition(
      name: c['name'] as String,
      op: c['op'] as String,
      value: c['value'],
    );
  }

  @override
  bool evaluate(ConditionContext ctx) {
    final v = ctx.variable(name);
    return _compare(v, op, value);
  }

  bool _compare(dynamic a, String op, dynamic b) {
    if (a is num && b is num) {
      switch (op) {
        case 'eq': return a == b;
        case 'neq': return a != b;
        case 'gt': return a > b;
        case 'gte': return a >= b;
        case 'lt': return a < b;
        case 'lte': return a <= b;
      }
    }
    if (op == 'eq') return a == b;
    if (op == 'neq') return a != b;
    return false;
  }
}

/// Check if an emitter has remaining items (used in `if`).
class EmitterHasNextCondition implements Condition {
  final String emitterId;
  EmitterHasNextCondition(this.emitterId);
  factory EmitterHasNextCondition.fromJson(Map<String, dynamic> j) =>
      EmitterHasNextCondition(
          (j['emitter_has_next'] as Map<String, dynamic>)['emitterId'] as String);

  @override
  bool evaluate(ConditionContext ctx) => ctx.emitterHasNext(emitterId);
}

/// Count entities matching a selector (used in `if`).
class BoardCountCondition implements Condition {
  final String? kind;
  final String? tag;
  final String? layerId;
  final String op;
  final int value;

  BoardCountCondition({this.kind, this.tag, this.layerId, required this.op, required this.value});

  factory BoardCountCondition.fromJson(Map<String, dynamic> j) {
    final c = j['board_count'] as Map<String, dynamic>;
    return BoardCountCondition(
      kind: c['kind'] as String?,
      tag: c['tag'] as String?,
      layerId: c['layer'] as String?,
      op: c['op'] as String,
      value: c['value'] as int,
    );
  }

  @override
  bool evaluate(ConditionContext ctx) {
    final count = ctx.countEntities(kind: kind, tag: tag, layerId: layerId);
    switch (op) {
      case 'eq': return count == value;
      case 'neq': return count != value;
      case 'gt': return count > value;
      case 'gte': return count >= value;
      case 'lt': return count < value;
      case 'lte': return count <= value;
      default: return false;
    }
  }
}

class AllOfCondition implements Condition {
  final List<Condition> conditions;
  AllOfCondition(this.conditions);
  factory AllOfCondition.fromJson(Map<String, dynamic> j) => AllOfCondition(
        (j['all_of'] as List)
            .map((e) => Condition.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
  @override
  bool evaluate(ConditionContext ctx) => conditions.every((c) => c.evaluate(ctx));
}

class AnyOfCondition implements Condition {
  final List<Condition> conditions;
  AnyOfCondition(this.conditions);
  factory AnyOfCondition.fromJson(Map<String, dynamic> j) => AnyOfCondition(
        (j['any_of'] as List)
            .map((e) => Condition.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
  @override
  bool evaluate(ConditionContext ctx) => conditions.any((c) => c.evaluate(ctx));
}

class NotCondition implements Condition {
  final Condition condition;
  NotCondition(this.condition);
  factory NotCondition.fromJson(Map<String, dynamic> j) =>
      NotCondition(Condition.fromJson(j['not'] as Map<String, dynamic>));
  @override
  bool evaluate(ConditionContext ctx) => !condition.evaluate(ctx);
}
