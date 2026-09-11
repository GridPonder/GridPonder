import 'package:gridponder_engine/engine.dart';

/// Returns the selected cell for an accepted action backed by an opted-in tap
/// binding. This keeps direct input, Solve, and Hint playback consistent.
Position? selectionPositionForAction(
  GameAction action,
  Iterable<GestureBinding> bindings,
) {
  for (final binding in bindings) {
    if (binding.gesture != 'tap_cell' ||
        binding.action != action.actionId ||
        !binding.showSelection) {
      continue;
    }

    String? positionParam;
    binding.paramMapping?.forEach((key, value) {
      if (value == 'tap_position') positionParam = key;
    });
    if (positionParam == null) continue;

    final raw = action.params[positionParam];
    if (raw is List && raw.length >= 2 && raw[0] is num && raw[1] is num) {
      return Position((raw[0] as num).toInt(), (raw[1] as num).toInt());
    }
  }
  return null;
}
