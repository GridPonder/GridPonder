import 'position.dart';

/// Applies a per-actor direction transform to a movement delta.
///
/// See docs/dsl/04_systems.md (`coupled_actors.directionTransforms`).
/// Unrecognised or missing transforms are treated as `identity` — both engines
/// must agree, so this is deliberately lenient rather than throwing.
Position transformDelta(Position delta, String? transform) {
  switch (transform) {
    case 'invert':
      return Position(-delta.x, -delta.y);
    case 'mirror_x':
      return Position(-delta.x, delta.y);
    case 'mirror_y':
      return Position(delta.x, -delta.y);
    case 'identity':
    default:
      return delta;
  }
}
