import 'package:gridponder_app/src/services/playtest_tracker.dart';

/// A tracker that records every event synchronously, with its fields, instead
/// of sending beacons — so tests see events in call order.
class RecordingTracker extends PlaytestTracker {
  RecordingTracker() : super(enabled: true, send: (_) async {});

  final List<Map<String, Object?>> events = [];

  List<String> get names => [for (final e in events) e['event'] as String];

  Iterable<Map<String, Object?>> named(String event) =>
      events.where((e) => e['event'] == event);

  @override
  Future<void> track(
    String event, {
    String? level,
    String? action,
    String? outcome,
    String? src,
    int? n,
    String? pos,
    String? av,
    String? tx,
    int? t,
    int? busy,
    int? at,
    String? reason,
    String? rev,
    String? bd,
    String? vars,
    String? p,
  }) async {
    events.add({
      'event': event,
      'level': level,
      'action': action,
      'outcome': outcome,
      'src': src,
      'n': n,
      'pos': pos,
      'av': av,
      'tx': tx,
      't': t,
      'busy': busy,
      'at': at,
      'reason': reason,
      'rev': rev,
      'bd': bd,
      'vars': vars,
      'p': p,
    });
  }
}
