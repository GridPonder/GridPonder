import 'playtest_tracker.dart';

/// Milliseconds on a monotonic clock; injectable so tests control time.
typedef PlaytestClock = int Function();

final Stopwatch _monotonic = Stopwatch()..start();
int _defaultClock() => _monotonic.elapsedMilliseconds;

/// The per-level lifecycle of playtest tracking: which level is open, how long
/// it has been open, which attempt the tester is on, and how much of that time
/// the UI spent busy. Every event it sends carries the same stamps:
///
/// - `t`: ms since the level was opened.
/// - `busy`: ms of that during which the UI held input — move animations and
///   hint/solve replays. `t - busy` is time the tester could have acted, so
///   the gap in `t - busy` between two events is pure think time; the gap in
///   `t` alone includes the previous move's animation.
/// - `at`: the 1-based attempt; a reset ends one attempt and starts the next.
///
/// A level is *open* from [startLevel] until [exitLevel]. Leaving it by any
/// route — another level, a story page, closing the screen — must call
/// [exitLevel] at that moment, so the exit is stamped when the tester left
/// rather than when the next level happened to load.
class PlaytestSession {
  PlaytestSession(this.tracker, {PlaytestClock? clock})
    : _now = clock ?? _defaultClock;

  final PlaytestTracker tracker;
  final PlaytestClock _now;

  String? _level;
  int _openedAt = 0;
  int _busyMs = 0;
  int _busyDepth = 0;
  int _busySince = 0;
  int _attempt = 1;
  bool _lossLogged = false;
  bool _completed = false;

  bool get enabled => tracker.enabled;

  /// The open level, or null between levels (e.g. on a story page).
  String? get level => _level;
  int get attempt => _attempt;

  int get _t => _now() - _openedAt;
  int get _busy => _busyMs + (_busyDepth > 0 ? _now() - _busySince : 0);

  /// Opens [levelId]. Closes the previous level first if one is still open,
  /// but a caller that knows the tester is leaving should call [exitLevel]
  /// itself, at the moment they leave.
  void startLevel(String levelId, {int exitDepth = 0, String? rev}) {
    exitLevel(exitDepth);
    _level = levelId;
    _openedAt = _now();
    _busyMs = 0;
    _busyDepth = 0;
    _attempt = 1;
    _lossLogged = false;
    _completed = false;
    tracker.track(
      'level_start',
      level: levelId,
      t: 0,
      busy: 0,
      at: 1,
      rev: rev,
    );
  }

  /// Closes the open level. Logs `level_exit` unless the tester completed the
  /// current attempt — leaving after a win is not an abandon. [depth] is how
  /// many moves deep the tester was. No-op when no level is open.
  void exitLevel(int depth) {
    final level = _level;
    if (level == null) return;
    if (!_completed) {
      tracker.track(
        'level_exit',
        level: level,
        n: depth,
        t: _t,
        busy: _busy,
        at: _attempt,
      );
    }
    _level = null;
    _busyDepth = 0;
  }

  /// Marks the UI busy — input held — until the matching [endBusy]. Nests, so
  /// a replay can hold the UI across the moves it animates.
  void beginBusy() {
    if (_level == null) return;
    if (_busyDepth++ == 0) _busySince = _now();
  }

  void endBusy() {
    if (_level == null || _busyDepth == 0) return;
    if (--_busyDepth == 0) _busyMs += _now() - _busySince;
  }

  /// One move. [outcome] is `accepted` or `rejected`; the remaining fields are
  /// passed through to the tracker unchanged.
  void move({
    required String action,
    required String outcome,
    required String src,
    required int depth,
    String? p,
    String? av,
    String? pos,
    String? tx,
    String? bd,
    String? vars,
  }) {
    final level = _level;
    if (level == null) return;
    tracker.track(
      'move',
      level: level,
      action: action,
      outcome: outcome,
      src: src,
      n: depth,
      t: _t,
      busy: _busy,
      at: _attempt,
      p: p,
      av: av,
      pos: pos,
      tx: tx,
      bd: bd,
      vars: vars,
    );
  }

  /// The level was lost. Logged once per loss: undo and reset re-arm it, since
  /// dying again after stepping back is a fresh fact.
  void failed(String reason, int depth) {
    final level = _level;
    if (level == null || _lossLogged) return;
    _lossLogged = true;
    tracker.track(
      'level_failed',
      level: level,
      reason: reason,
      n: depth,
      t: _t,
      busy: _busy,
      at: _attempt,
    );
  }

  /// An undo from [depthBefore] moves deep.
  void undo(int depthBefore) {
    final level = _level;
    if (level == null) return;
    _lossLogged = false;
    tracker.track(
      'undo',
      level: level,
      n: depthBefore,
      t: _t,
      busy: _busy,
      at: _attempt,
    );
  }

  /// A reset from [depthBefore] moves deep: logged against the attempt it
  /// ends, then the next attempt begins. Hint and Solve replays reset the
  /// board too and must log here, or the final path cannot be reconstructed.
  void reset(int depthBefore) {
    final level = _level;
    if (level == null) return;
    tracker.track(
      'reset',
      level: level,
      n: depthBefore,
      t: _t,
      busy: _busy,
      at: _attempt,
    );
    _attempt += 1;
    _lossLogged = false;
    _completed = false;
  }

  void hintRequested(int depth) {
    final level = _level;
    if (level == null) return;
    tracker.track(
      'hint_requested',
      level: level,
      n: depth,
      t: _t,
      busy: _busy,
      at: _attempt,
    );
  }

  /// The level was won with a final path [depth] moves long. Consumes the
  /// exit: leaving afterwards is not an abandon, until a reset starts a new
  /// attempt.
  void completed(int depth) {
    final level = _level;
    if (level == null || _completed) return;
    _completed = true;
    tracker.track(
      'level_complete',
      level: level,
      n: depth,
      t: _t,
      busy: _busy,
      at: _attempt,
    );
  }
}
