import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:gridponder_engine/engine.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Tracks completed levels and determines whether a level is playable.
///
/// In debug builds ([kDebugMode] == true) all levels are always unlocked —
/// useful for development and integration tests. In release builds levels
/// unlock sequentially: completing level N unlocks level N+1 within the
/// same pack.
///
/// Progress is persisted via [SharedPreferences]:
///   - Mobile / Desktop: stored in the OS-managed preferences file.
///   - Web: stored in `window.localStorage`; persists across browser
///     sessions but is cleared when the user wipes browser data.
class ProgressService {
  static const _prefsKey = 'gridponder_completed_levels';

  final SharedPreferences _prefs;
  final Set<String> _completed;

  /// True when running in a debug build — all levels are unlocked.
  final bool isDeveloperMode;

  ProgressService._(this._prefs, this._completed, this.isDeveloperMode);

  static Future<ProgressService> create() async {
    final prefs = await SharedPreferences.getInstance();
    final completed =
        Set<String>.from(prefs.getStringList(_prefsKey) ?? []);
    return ProgressService._(prefs, completed, kDebugMode);
  }

  // ---------------------------------------------------------------------------
  // Querying
  // ---------------------------------------------------------------------------

  /// Returns true if [levelId] may be played.
  ///
  /// Always true in developer mode. Otherwise true if [levelId] is the first
  /// level entry in [sequence], or if the immediately preceding level entry
  /// has been completed.
  ///
  /// Story entries in [sequence] are ignored for unlock purposes — they are
  /// always accessible.
  bool isUnlocked(String levelId, List<SequenceEntry> sequence) {
    if (isDeveloperMode) return true;
    final levels =
        sequence.where((e) => e.type == 'level').toList();
    final idx = levels.indexWhere((e) => e.ref == levelId);
    if (idx <= 0) return true; // first level, or ID not found
    final prevRef = levels[idx - 1].ref!;
    return _completed.contains(prevRef);
  }

  /// Returns true if [levelId] has been completed at least once.
  bool isCompleted(String levelId) => _completed.contains(levelId);

  /// Number of [levelIds] that have been completed.
  int completedCount(List<String> levelIds) =>
      levelIds.where(_completed.contains).length;

  // ---------------------------------------------------------------------------
  // Recording progress
  // ---------------------------------------------------------------------------

  /// Records [levelId] as completed and persists to storage.
  /// No-op if already completed.
  Future<void> markCompleted(String levelId) async {
    if (_completed.contains(levelId)) return;
    _completed.add(levelId);
    await _prefs.setStringList(_prefsKey, _completed.toList());
  }
}
