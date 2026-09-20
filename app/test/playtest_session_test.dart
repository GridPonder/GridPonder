import 'package:flutter_test/flutter_test.dart';
import 'package:gridponder_app/src/services/playtest_session.dart';

import 'support/recording_tracker.dart';

void main() {
  late RecordingTracker tracker;
  late int now;
  late PlaytestSession session;

  setUp(() {
    tracker = RecordingTracker();
    now = 1000;
    session = PlaytestSession(tracker, clock: () => now);
  });

  test('level_start carries t, busy, attempt and revision', () {
    session.startLevel('l1', rev: 'abcd1234');
    expect(tracker.events.single, containsPair('event', 'level_start'));
    expect(tracker.events.single, containsPair('t', 0));
    expect(tracker.events.single, containsPair('busy', 0));
    expect(tracker.events.single, containsPair('at', 1));
    expect(tracker.events.single, containsPair('rev', 'abcd1234'));
  });

  test('busy time covers the animation, so t - busy is pure think time', () {
    session.startLevel('l1');
    now += 2000; // thinks for 2s
    session.move(action: 'move', outcome: 'accepted', src: 'user', depth: 1);
    session.beginBusy();
    now += 700; // the move animates for 0.7s, input held
    session.endBusy();
    now += 3000; // thinks for 3s
    session.move(action: 'move', outcome: 'accepted', src: 'user', depth: 2);

    final moves = tracker.named('move').toList();
    int active(Map<String, Object?> e) => (e['t'] as int) - (e['busy'] as int);
    expect(moves[0]['t'], 2000);
    expect(moves[1]['t'], 5700);
    expect(moves[1]['busy'], 700);
    expect(active(moves[1]) - active(moves[0]), 3000);
  });

  test('nested busy windows count once, and an open one counts so far', () {
    session.startLevel('l1');
    session.beginBusy(); // replay
    now += 100;
    session.beginBusy(); // a move inside it
    now += 400;
    session.endBusy();
    now += 300; // replay pause between moves
    session.hintRequested(0);
    expect(tracker.named('hint_requested').single['busy'], 800);
    session.endBusy();
    now += 50;
    session.undo(1);
    expect(tracker.named('undo').single['busy'], 800);
  });

  test('exit is stamped at the moment of leaving, and only once', () {
    session.startLevel('l1');
    now += 4000;
    session.exitLevel(3);
    now += 60000; // time on a story page does not belong to the level
    session.exitLevel(3);
    session.startLevel('l2');

    final exit = tracker.named('level_exit').single;
    expect(exit['level'], 'l1');
    expect(exit['t'], 4000);
    expect(exit['n'], 3);
    expect(session.level, 'l2');
  });

  test('events between levels are dropped', () {
    session.startLevel('l1');
    session.exitLevel(0);
    tracker.events.clear();
    session.move(action: 'move', outcome: 'accepted', src: 'user', depth: 1);
    session.undo(1);
    session.reset(1);
    session.beginBusy();
    session.endBusy();
    expect(tracker.events, isEmpty);
  });

  test('opening a level closes the one still open', () {
    session.startLevel('l1');
    session.startLevel('l2', exitDepth: 2);
    expect(tracker.names, ['level_start', 'level_exit', 'level_start']);
    expect(tracker.named('level_exit').single['n'], 2);
  });

  test('a completed attempt consumes the exit until a reset', () {
    session.startLevel('l1');
    session.completed(5);
    session.completed(5); // win detected again on a rebuild
    session.exitLevel(5);
    expect(tracker.names, ['level_start', 'level_complete']);

    session.startLevel('l1');
    session.completed(5);
    session.reset(5);
    session.exitLevel(0);
    expect(tracker.names.last, 'level_exit');
  });

  test('reset ends the attempt it is logged against', () {
    session.startLevel('l1');
    session.reset(4);
    session.reset(2);
    final resets = tracker.named('reset').toList();
    expect([for (final r in resets) r['at']], [1, 2]);
    expect([for (final r in resets) r['n']], [4, 2]);
    expect(session.attempt, 3);
  });

  test('a loss is logged once, and undo or reset re-arm it', () {
    session.startLevel('l1');
    session.failed('fell', 3);
    session.failed('fell', 3);
    expect(tracker.named('level_failed').length, 1);
    session.undo(3);
    session.failed('fell', 3);
    expect(tracker.named('level_failed').length, 2);
    session.reset(3);
    session.failed('fell', 1);
    final fails = tracker.named('level_failed').toList();
    expect(fails.length, 3);
    expect(fails.last['at'], 2);
    expect(fails.last['reason'], 'fell');
  });

  test('a new level starts again at attempt 1 with fresh clocks', () {
    session.startLevel('l1');
    session.beginBusy();
    now += 500;
    session.reset(0);
    session.startLevel('l2');
    now += 100;
    session.undo(0);
    final undo = tracker.named('undo').single;
    expect(undo['at'], 1);
    expect(undo['t'], 100);
    expect(undo['busy'], 0);
  });
}
