import '../models/condition.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// Implements ConditionContext using live LevelState + a triggering event.
class _Ctx implements ConditionContext {
  final GameEvent event;
  final LevelState state;
  final GameDefinition game;

  _Ctx(this.event, this.state, this.game);

  @override
  Map<String, dynamic> get eventPayload => event.payload;

  @override
  String get eventType => event.type;

  @override
  String? entityKindAt(String layerId, Position pos) =>
      state.board.getEntity(layerId, pos)?.kind;

  @override
  bool hasTagAt(String layerId, Position pos, String tag) =>
      state.board.hasTagAt(layerId, pos, tag, game.entityKinds);

  @override
  bool isCellEmpty(String layerId, Position pos) =>
      state.board.getEntity(layerId, pos) == null;

  @override
  bool get avatarEnabled => state.avatar.enabled;

  @override
  Position? get avatarPosition => state.avatar.position;

  @override
  String? get avatarItem => state.avatar.inventory.slot;

  @override
  dynamic variable(String name) => state.variables[name];

  @override
  bool emitterHasNext(String emitterId) {
    final mco = state.board.getMultiCellObject(emitterId);
    if (mco == null) return false;
    final queue = mco.params['queue'] as List?;
    if (queue == null) return false;
    final idx = (mco.params['currentIndex'] as int?) ?? 0;
    return idx < queue.length;
  }

  @override
  int countEntities({String? kind, String? tag, String? layerId}) {
    int count = 0;
    final layers = layerId != null
        ? [state.board.layers[layerId]].whereType<dynamic>()
        : state.board.layers.values;
    for (final layer in layers) {
      for (final entry in layer.entries()) {
        if (kind != null && entry.value.kind == kind) count++;
        if (tag != null && game.hasTag(entry.value.kind, tag)) count++;
      }
    }
    return count;
  }
}

class ConditionEvaluator {
  bool evaluate(Condition? condition, GameEvent event, LevelState state,
      GameDefinition game) {
    if (condition == null) return true;
    return condition.evaluate(_Ctx(event, state, game));
  }
}
