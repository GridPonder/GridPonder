import 'dart:math';
import 'package:shared_preferences/shared_preferences.dart';
import 'playtest_beacon.dart';

const _sessionIdKey = 'playtest_session_id';

/// Fire-and-forget UX tracking for playtest builds. Entirely inert unless
/// built with `--dart-define=PLAYTEST_TRACK=1` — normal/production builds
/// never generate a session id or send a request.
class PlaytestTracker {
  static const bool _compiledIn = bool.fromEnvironment(
    'PLAYTEST_TRACK',
    defaultValue: false,
  );

  final bool enabled;
  final Future<void> Function(Uri uri) _send;
  String? _sessionId;

  PlaytestTracker({bool? enabled, Future<void> Function(Uri uri)? send})
    : enabled = enabled ?? _compiledIn,
      _send = send ?? sendBeacon;

  Future<String> _ensureSessionId() async {
    final existing = _sessionId;
    if (existing != null) return existing;
    final prefs = await SharedPreferences.getInstance();
    var id = prefs.getString(_sessionIdKey);
    if (id == null) {
      id = _generateId();
      await prefs.setString(_sessionIdKey, id);
    }
    _sessionId = id;
    return id;
  }

  String _generateId() {
    final rnd = Random();
    return List.generate(16, (_) => rnd.nextInt(16).toRadixString(16)).join();
  }

  Future<void> track(
    String event, {
    String? level,
    String? action,
    String? outcome,
    String? src,
    int? n,
    String? pos,
  }) async {
    if (!enabled) return;
    final session = await _ensureSessionId();
    final params = <String, String>{'session': session, 'event': event};
    if (level != null) params['level'] = level;
    if (action != null) params['action'] = action;
    if (outcome != null) params['outcome'] = outcome;
    if (src != null) params['src'] = src;
    if (n != null) params['n'] = '$n';
    if (pos != null && pos.isNotEmpty) params['pos'] = pos;
    await _send(Uri(path: '/track', queryParameters: params));
  }
}
