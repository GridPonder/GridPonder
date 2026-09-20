import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gridponder_app/src/screens/play_screen.dart';
import 'package:gridponder_app/src/services/pack_service.dart';
import 'package:gridponder_app/src/services/settings_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/recording_tracker.dart';

// Carrot Quest's sequence runs fw_007 → story → fw_ice_002, which is the case
// that used to leave a level's clock running through a story page.
const _pack = 'carrot_quest';
const _levelBeforeStory = 'fw_007';
const _levelAfterStory = 'fw_ice_002';

/// Runs frames until a move's motion has played out. A turn chains several
/// animations, each needing frames of its own, so one long pump is not enough.
Future<void> settle(WidgetTester tester) async {
  for (var i = 0; i < 40; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

void main() {
  late PackService pack;
  late SettingsService settings;

  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<RecordingTracker> open(WidgetTester tester, String levelId) async {
    await tester.runAsync(() async {
      settings = await SettingsService.create();
      pack = await PackService.load(_pack);
    });
    final tracker = RecordingTracker();
    await tester.pumpWidget(
      MaterialApp(
        home: PlayScreen(
          packService: pack,
          settings: settings,
          startLevelId: levelId,
          tracker: tracker,
        ),
      ),
    );
    await tester.pump();
    return tracker;
  }

  testWidgets('leaving a level for a story page logs the exit at once', (
    tester,
  ) async {
    final tracker = await open(tester, _levelBeforeStory);
    final start = tracker.events.single;
    expect(start['event'], 'level_start');
    expect(start['t'], 0);
    expect(start['rev'], pack.levelRevision(_levelBeforeStory));
    expect(start['rev'], matches(RegExp(r'^[0-9a-f]{8}$')));

    await tester.tap(find.byIcon(Icons.navigate_next));
    await tester.pump();
    expect(tracker.names, ['level_start', 'level_exit']);
    expect(tracker.events.last['level'], _levelBeforeStory);

    // From the story page into the next level: the old level is already
    // closed, so the only new event is the next level's start.
    await tester.tap(find.byIcon(Icons.navigate_next));
    await tester.pump();
    expect(tracker.names, ['level_start', 'level_exit', 'level_start']);
    expect(tracker.events.last['level'], _levelAfterStory);

    // Closing the screen closes the open level.
    await tester.pumpWidget(const SizedBox());
    expect(tracker.names.last, 'level_exit');
    expect(tracker.events.last['level'], _levelAfterStory);
  });

  testWidgets('moves, undo and reset carry timing and the attempt', (
    tester,
  ) async {
    final tracker = await open(tester, _levelBeforeStory);
    // fw_007's gold path opens with `move right`, so this move is legal.
    expect(
      pack.level(_levelBeforeStory).solution.goldPath.first.params['direction'],
      'right',
    );

    await tester.sendKeyEvent(LogicalKeyboardKey.arrowRight);
    await settle(tester);
    final move = tracker.named('move').single;
    expect(move['outcome'], 'accepted');
    expect(move['src'], 'user');
    expect(move['at'], 1);
    expect(move['n'], 1);
    expect(move['t'], isNotNull);
    expect(move['busy'], isNotNull);
    expect(move['p'], 'direction=right');
    // Only the avatar moves here, and it is reported in av, not bd.
    expect(move['av'], isNotEmpty);

    await tester.tap(find.text('Undo'));
    await tester.pump();
    expect(tracker.named('undo').single['n'], 1);

    await tester.sendKeyEvent(LogicalKeyboardKey.arrowRight);
    await settle(tester);
    await tester.longPress(find.text('Undo'));
    await tester.pump();
    final reset = tracker.named('reset').single;
    expect(reset['at'], 1);
    expect(reset['n'], 1);

    await tester.sendKeyEvent(LogicalKeyboardKey.arrowRight);
    await settle(tester);
    expect(tracker.named('move').last['at'], 2);

    await tester.pumpWidget(const SizedBox());
    final exit = tracker.named('level_exit').single;
    expect(exit['at'], 2);
    expect(exit['n'], 1);
  });
}
