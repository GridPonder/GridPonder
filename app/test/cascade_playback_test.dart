import 'package:flutter_test/flutter_test.dart';
import 'package:gridponder_app/src/animation/cascade_playback.dart';
import 'package:gridponder_engine/engine.dart';

void main() {
  test('groups click, explosion, and incoming changes into visible phases', () {
    const center = Position(1, 1);
    const top = Position(1, 0);
    const left = Position(0, 1);
    final events = [
      GameEvent.cellCharged(
        center,
        beforeCharge: 3,
        afterCharge: 4,
        delta: 1,
        wave: 0,
        source: 'click',
        layer: 'objects',
      ),
      GameEvent.cascadeWaveStarted(1, const [center]),
      GameEvent.cellExploded(
        center,
        beforeCharge: 4,
        afterCharge: 0,
        threshold: 4,
        kernel: 'plus',
        wave: 1,
        layer: 'objects',
      ),
      GameEvent.cellCharged(
        top,
        beforeCharge: 3,
        afterCharge: 4,
        delta: 1,
        wave: 1,
        source: 'cascade',
        layer: 'objects',
        sourcePositions: const [center],
      ),
      GameEvent.cellCharged(
        left,
        beforeCharge: 2,
        afterCharge: 3,
        delta: 1,
        wave: 1,
        source: 'cascade',
        layer: 'objects',
        sourcePositions: const [center],
      ),
    ];

    final steps = cascadePlaybackSteps(events);

    expect(steps.map((step) => step.kind).toList(), [
      CascadePlaybackKind.clickCharge,
      CascadePlaybackKind.explosion,
      CascadePlaybackKind.incomingCharge,
    ]);
    expect(steps[0].changes.single.afterCharge, 4);
    expect(steps[1].changes.single.afterCharge, 0);
    expect(steps[2].changes.map((change) => change.position).toList(), [
      top,
      left,
    ]);
    expect(steps[2].changes.first.sourcePositions, const [center]);
  });

  test('keeps newly unstable cells in the following wave', () {
    const center = Position(1, 1);
    const top = Position(1, 0);
    final events = [
      GameEvent.cellExploded(
        center,
        beforeCharge: 4,
        afterCharge: 0,
        threshold: 4,
        kernel: 'plus',
        wave: 1,
        layer: 'objects',
      ),
      GameEvent.cellCharged(
        top,
        beforeCharge: 3,
        afterCharge: 4,
        delta: 1,
        wave: 1,
        source: 'cascade',
        layer: 'objects',
        sourcePositions: const [center],
      ),
      GameEvent.cellExploded(
        top,
        beforeCharge: 4,
        afterCharge: 0,
        threshold: 4,
        kernel: 'plus',
        wave: 2,
        layer: 'objects',
      ),
    ];

    final steps = cascadePlaybackSteps(events);

    expect(steps.map((step) => step.wave).toList(), [1, 1, 2]);
    expect(steps.last.kind, CascadePlaybackKind.explosion);
  });

  test('preserves the configured value parameter for visual replay', () {
    final steps = cascadePlaybackSteps([
      GameEvent.cellCharged(
        const Position(0, 0),
        beforeCharge: 2,
        afterCharge: 3,
        delta: 1,
        wave: 0,
        source: 'click',
        layer: 'signals',
        param: 'energy',
      ),
    ]);

    expect(steps.single.changes.single.param, 'energy');
  });
}
