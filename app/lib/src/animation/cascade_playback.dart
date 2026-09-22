import 'package:gridponder_engine/engine.dart';

/// Deliberately slower than ordinary movement: reading several changing
/// numbers is the mechanic, so each causal phase needs time to register.
const cascadeChargePhaseDuration = Duration(milliseconds: 600);
const cascadeExplosionPhaseDuration = Duration(milliseconds: 800);
const cascadePulseDuration = Duration(milliseconds: 560);

/// Visual phases reconstructed from the deterministic cascade event stream.
///
/// The engine resolves a cascade atomically, but the player needs to see its
/// causal order: the click adds charge, unstable cells burst together, then
/// all incoming charge for that wave lands together.
enum CascadePlaybackKind { clickCharge, explosion, incomingCharge }

class CascadePlaybackChange {
  final Position position;
  final String layer;
  final int beforeCharge;
  final int afterCharge;
  final int delta;

  const CascadePlaybackChange({
    required this.position,
    required this.layer,
    required this.beforeCharge,
    required this.afterCharge,
    required this.delta,
  });
}

class CascadePlaybackStep {
  final CascadePlaybackKind kind;
  final int wave;
  final List<CascadePlaybackChange> changes;

  const CascadePlaybackStep({
    required this.kind,
    required this.wave,
    required this.changes,
  });
}

/// Turns cascade events into simultaneous visual steps in causal order.
List<CascadePlaybackStep> cascadePlaybackSteps(List<GameEvent> events) {
  final clickChanges = <CascadePlaybackChange>[];
  final explosions = <int, List<CascadePlaybackChange>>{};
  final incoming = <int, List<CascadePlaybackChange>>{};

  for (final event in events) {
    final pos = event.position;
    if (pos == null) continue;
    final before = event.payload['beforeCharge'];
    final after = event.payload['afterCharge'];
    if (before is! int || after is! int) continue;
    final layer = event.payload['layer'] as String? ?? 'objects';
    final wave = event.payload['wave'] as int? ?? 0;

    if (event.type == 'cell_exploded') {
      explosions
          .putIfAbsent(wave, () => [])
          .add(
            CascadePlaybackChange(
              position: pos,
              layer: layer,
              beforeCharge: before,
              afterCharge: after,
              delta: after - before,
            ),
          );
      continue;
    }
    if (event.type != 'cell_charged') continue;

    final change = CascadePlaybackChange(
      position: pos,
      layer: layer,
      beforeCharge: before,
      afterCharge: after,
      delta: event.payload['delta'] as int? ?? after - before,
    );
    if (event.payload['source'] == 'click' || wave == 0) {
      clickChanges.add(change);
    } else {
      incoming.putIfAbsent(wave, () => []).add(change);
    }
  }

  final steps = <CascadePlaybackStep>[];
  if (clickChanges.isNotEmpty) {
    steps.add(
      CascadePlaybackStep(
        kind: CascadePlaybackKind.clickCharge,
        wave: 0,
        changes: clickChanges,
      ),
    );
  }

  final waves = {...explosions.keys, ...incoming.keys}.toList()..sort();
  for (final wave in waves) {
    final bursting = explosions[wave];
    if (bursting != null && bursting.isNotEmpty) {
      steps.add(
        CascadePlaybackStep(
          kind: CascadePlaybackKind.explosion,
          wave: wave,
          changes: bursting,
        ),
      );
    }
    final landing = incoming[wave];
    if (landing != null && landing.isNotEmpty) {
      steps.add(
        CascadePlaybackStep(
          kind: CascadePlaybackKind.incomingCharge,
          wave: wave,
          changes: landing,
        ),
      );
    }
  }
  return steps;
}

/// One short-lived pulse drawn over a cell while a playback step is visible.
class CascadeCellFeedback {
  final CascadePlaybackKind kind;
  final int delta;
  final int pulseId;

  const CascadeCellFeedback({
    required this.kind,
    required this.delta,
    required this.pulseId,
  });
}
