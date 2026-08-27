import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:gridponder_app/src/services/playtest_tracker.dart';

void main() {
  test('does nothing when disabled', () async {
    var sent = false;
    final tracker = PlaytestTracker(
      enabled: false,
      send: (uri) async {
        sent = true;
      },
    );
    await tracker.track('move', level: 'sp_001');
    expect(sent, isFalse);
  });

  test('is a true no-op with production defaults (no --dart-define)', () async {
    final defaultTracker = PlaytestTracker();
    expect(defaultTracker.enabled, isFalse);

    SharedPreferences.setMockInitialValues({});
    var sent = false;
    final tracker = PlaytestTracker(
      send: (uri) async {
        sent = true;
      },
    );
    await tracker.track('move', level: 'sp_001');
    expect(sent, isFalse);

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('playtest_session_id'), isNull);
  });

  test('sends an event with the expected query params when enabled', () async {
    SharedPreferences.setMockInitialValues({});
    Uri? captured;
    final tracker = PlaytestTracker(
      enabled: true,
      send: (uri) async {
        captured = uri;
      },
    );
    await tracker.track(
      'move',
      level: 'sp_001',
      action: 'move_up',
      outcome: 'accepted',
      src: 'user',
      n: 3,
      pos: '2.5',
    );
    expect(captured, isNotNull);
    expect(captured!.path, '/track');
    expect(captured!.queryParameters['event'], 'move');
    expect(captured!.queryParameters['level'], 'sp_001');
    expect(captured!.queryParameters['action'], 'move_up');
    expect(captured!.queryParameters['outcome'], 'accepted');
    expect(captured!.queryParameters['src'], 'user');
    expect(captured!.queryParameters['n'], '3');
    expect(captured!.queryParameters['pos'], '2.5');
    expect(captured!.queryParameters['session'], isNotEmpty);
  });

  test('omits pos when it is empty', () async {
    SharedPreferences.setMockInitialValues({});
    Uri? captured;
    final tracker = PlaytestTracker(
      enabled: true,
      send: (uri) async {
        captured = uri;
      },
    );
    await tracker.track('move', level: 'sp_001', pos: '');
    expect(captured!.queryParameters.containsKey('pos'), isFalse);
  });

  test('reuses the same session id across calls', () async {
    SharedPreferences.setMockInitialValues({});
    final uris = <Uri>[];
    final tracker = PlaytestTracker(
      enabled: true,
      send: (uri) async {
        uris.add(uri);
      },
    );
    await tracker.track('level_start', level: 'sp_001');
    await tracker.track('level_start', level: 'sp_002');
    expect(uris, hasLength(2));
    expect(
      uris[0].queryParameters['session'],
      uris[1].queryParameters['session'],
    );
  });

  test('swallows an exception from send without propagating it', () async {
    SharedPreferences.setMockInitialValues({});
    final tracker = PlaytestTracker(
      enabled: true,
      send: (uri) async {
        throw StateError('network is down');
      },
    );
    // Tracking must fail silently — a thrown beacon must never surface to a
    // caller, since no call site awaits track().
    await expectLater(tracker.track('move', level: 'sp_001'), completes);
  });

  test('persists the session id across tracker instances', () async {
    SharedPreferences.setMockInitialValues({
      'playtest_session_id': 'existing-id-123',
    });
    Uri? captured;
    final tracker = PlaytestTracker(
      enabled: true,
      send: (uri) async {
        captured = uri;
      },
    );
    await tracker.track('level_start', level: 'sp_001');
    expect(captured!.queryParameters['session'], 'existing-id-123');
  });
}
