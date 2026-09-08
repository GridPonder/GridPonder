import 'package:gridponder_engine/engine.dart';

/// Builds the board snapshot shown while an `entity_path` animation runs.
///
/// Cell transforms emitted before the first path event must already be visible
/// while the mover travels. Preserve the transformed entity's instance params:
/// sprite templates such as `signal_green_{entrySide}.png` depend on them.
LevelState buildPathAnimationState(
  LevelState preState,
  Iterable<GameEvent> events,
) {
  final animationState = preState.copy();
  for (final event in events) {
    if (event.type == 'entity_path_moved') break;
    if (event.type != 'cell_transformed' || event.position == null) continue;
    final layer = event.payload['layer'] as String?;
    final toKind = event.payload['toKind'] as String?;
    if (layer == null || toKind == null) continue;

    final previous = animationState.board.getEntity(layer, event.position!);
    final eventParams = event.payload['params'];
    final params = eventParams is Map
        ? Map<String, dynamic>.from(eventParams)
        : Map<String, dynamic>.from(previous?.params ?? const {});
    animationState.board.setEntity(
      layer,
      event.position!,
      EntityInstance(toKind, params),
    );
  }
  return animationState;
}
