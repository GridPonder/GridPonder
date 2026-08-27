import '../models/game_state.dart';

/// Shared runtime-variable reading for systems that keep a counter (a tape
/// index, an edit budget) in `state.variables`. Single home so
/// `coupled_actors` and `terrain_edit` cannot drift on how a malformed value
/// is tolerated.
///
/// Only a plain `num` (`int` or finite `double`) is accepted. Anything else —
/// including a `String` or `bool`, and non-finite doubles (`NaN`,
/// `Infinity`, which would otherwise throw from `.toInt()`) — falls back to
/// [defaultValue], matching the Python engine's `read_int_variable`.
int readIntVariable(LevelState state, String? name, {int defaultValue = 0}) {
  if (name == null) return defaultValue;
  final value = state.variables[name];
  if (value is num && value.isFinite) return value.toInt();
  return defaultValue;
}
