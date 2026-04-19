import 'package:flutter/foundation.dart';

/// Tracks hint availability and usage for a single level session.
class HintStatus {
  final bool isAvailable;
  final bool isUsed;
  const HintStatus({required this.isAvailable, required this.isUsed});
}

class HintService {
  /// Minutes after level start when each hint unlocks.
  /// Hint 1: 30 s, Hint 2: 2 min, Hint 3: 4 min.
  /// In debug builds all hints are available immediately.
  static List<double> get _timingsMinutes =>
      kDebugMode ? [0.0, 0.0, 0.0] : [0.5, 2.0, 4.0];

  final List<int> hintStops;
  final DateTime _startTime;
  final List<bool> _used;

  HintService({required this.hintStops})
      : _startTime = DateTime.now(),
        _used = List.filled(hintStops.length, false);

  double get elapsedMinutes =>
      DateTime.now().difference(_startTime).inMilliseconds / 60000.0;

  bool isAvailable(int i) {
    if (i >= hintStops.length) return false;
    final timings = _timingsMinutes;
    final t = i < timings.length ? timings[i] : timings.last;
    return elapsedMinutes >= t;
  }

  bool isUsed(int i) => i < _used.length && _used[i];

  void markUsed(int i) {
    if (i < _used.length) _used[i] = true;
  }

  List<HintStatus> get statuses => List.generate(
        hintStops.length,
        (i) => HintStatus(isAvailable: isAvailable(i), isUsed: _used[i]),
      );

  /// Index of the best hint to play next:
  /// first available & unused; if all used, last available; -1 if none available.
  int get nextIndex {
    for (int i = 0; i < hintStops.length; i++) {
      if (isAvailable(i) && !_used[i]) return i;
    }
    for (int i = hintStops.length - 1; i >= 0; i--) {
      if (isAvailable(i)) return i;
    }
    return -1;
  }

  bool get hasAnyAvailable => nextIndex >= 0;
}
