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

  test('sends av alongside pos as a separate field', () async {
    // `av` (the player's own cell) and `pos` (actor-layer cells) are logged
    // separately so analysis can tell the player's path from the actors
    // around them.
    SharedPreferences.setMockInitialValues({});
    Uri? captured;
    final tracker = PlaytestTracker(
      enabled: true,
      send: (uri) async {
        captured = uri;
      },
    );
    await tracker.track('move', level: 'fb_001', pos: '5.5', av: '1.2');
    expect(captured!.queryParameters['pos'], '5.5');
    expect(captured!.queryParameters['av'], '1.2');
  });

  test('omits av when it is empty', () async {
    // Actor-layer packs have no avatar; the field must be absent, not ''.
    SharedPreferences.setMockInitialValues({});
    Uri? captured;
    final tracker = PlaytestTracker(
      enabled: true,
      send: (uri) async {
        captured = uri;
      },
    );
    await tracker.track('move', level: 'pc_001', pos: '5.5', av: '');
    expect(captured!.queryParameters.containsKey('av'), isFalse);
    expect(captured!.queryParameters['pos'], '5.5');
  });

  test('sends tx, the cells this turn transformed', () async {
    // Terrain that changes under its own rules (Firebreak's fire) is in
    // neither av nor pos; tx is the only field that carries it.
    SharedPreferences.setMockInitialValues({});
    Uri? captured;
    final tracker = PlaytestTracker(
      enabled: true,
      send: (uri) async {
        captured = uri;
      },
    );
    await tracker.track('move', level: 'fb_001', av: '1.2', tx: '3.2:fire');
    expect(captured!.queryParameters['tx'], '3.2:fire');
    expect(captured!.queryParameters['av'], '1.2');
  });

  test('omits tx when no cell transformed', () async {
    SharedPreferences.setMockInitialValues({});
    Uri? captured;
    final tracker = PlaytestTracker(
      enabled: true,
      send: (uri) async {
        captured = uri;
      },
    );
    await tracker.track('move', level: 'fb_001', av: '1.2', tx: '');
    expect(captured!.queryParameters.containsKey('tx'), isFalse);
  });

  test('sends busy, the UI-held share of t', () async {
    // t - busy is the time the tester could act; the gap in it between two
    // events is think time with the previous move's animation removed.
    SharedPreferences.setMockInitialValues({});
    Uri? captured;
    final tracker = PlaytestTracker(
      enabled: true,
      send: (uri) async {
        captured = uri;
      },
    );
    await tracker.track('move', level: 'pp_001', t: 5700, busy: 700);
    expect(captured!.queryParameters['t'], '5700');
    expect(captured!.queryParameters['busy'], '700');
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

  test(
    'sends timing, attempt, reason, rev, board delta, vars and params',
    () async {
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
        level: 'fb_001',
        t: 1234,
        at: 2,
        reason: 'max_actions',
        rev: 'cafe1234',
        bd: '1.2:ground:floor',
        vars: 'burned:1',
        p: 'direction=up',
      );
      expect(captured!.queryParameters['t'], '1234');
      expect(captured!.queryParameters['at'], '2');
      expect(captured!.queryParameters['reason'], 'max_actions');
      expect(captured!.queryParameters['rev'], 'cafe1234');
      expect(captured!.queryParameters['bd'], '1.2:ground:floor');
      expect(captured!.queryParameters['vars'], 'burned:1');
      expect(captured!.queryParameters['p'], 'direction=up');
    },
  );

  test('omits empty board delta, vars and params', () async {
    // A move that changed no cells and no variables, from a no-param action,
    // must not clutter the log with empty fields (same rule as pos/av/tx).
    SharedPreferences.setMockInitialValues({});
    Uri? captured;
    final tracker = PlaytestTracker(
      enabled: true,
      send: (uri) async {
        captured = uri;
      },
    );
    await tracker.track('move', level: 'fb_001', bd: '', vars: '', p: '');
    expect(captured!.queryParameters.containsKey('bd'), isFalse);
    expect(captured!.queryParameters.containsKey('vars'), isFalse);
    expect(captured!.queryParameters.containsKey('p'), isFalse);
  });
}
