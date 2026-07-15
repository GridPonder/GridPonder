// Parity mirror of engines/python/test_balance_goal.py — behavioural cases
// for the `balance` goal type.
import 'package:gridponder_engine/engine.dart';
import 'package:gridponder_engine/src/engine/goal_evaluator.dart';
import 'package:gridponder_engine/src/engine/lose_evaluator.dart';
import 'package:test/test.dart';

// ---------------------------------------------------------------------------
// Fixtures: a 3x3 territory layer over a 3x3 all-`empty` ground (claimable=9).
// ---------------------------------------------------------------------------

GameDefinition _makeGame() {
  final data = {
    'id': 'com.gridponder.test_balance_goal',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
      {'id': 'territory', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'empty': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': '.',
      },
      'wall': {
        'layer': 'ground',
        'tags': ['solid'],
        'symbol': '#',
      },
      'terr_wei': {
        'layer': 'territory',
        'tags': ['territory'],
        'symbol': '1',
      },
      'terr_shu': {
        'layer': 'territory',
        'tags': ['territory'],
        'symbol': '2',
      },
      'terr_wu': {
        'layer': 'territory',
        'tags': ['territory'],
        'symbol': '3',
      },
    },
    'actions': [],
    'systems': [],
  };
  return GameDefinition.fromJson(data, id: 'test_balance_goal');
}

/// 3x3 all-`empty` ground (claimable=9), territory cells as given.
LevelState _makeState(GameDefinition game, List<List<dynamic>> territory,
    {int size = 3}) {
  final boardJson = <String, dynamic>{
    'size': [size, size],
    'layers': {
      'ground': {'format': 'sparse', 'entries': []},
      'territory': {
        'format': 'sparse',
        'entries': [
          for (final t in territory)
            {
              'position': [t[0], t[1]],
              'kind': t[2],
            }
        ],
      },
    },
  };
  final board = Board.fromJson(boardJson, game.layers);
  return LevelState.fromJson(const <String, dynamic>{}, board);
}

/// Lays out `counts[kind]` cells of each kind along row-major positions of a
/// 3x3 grid, leaving any remaining cells (out of 9) unclaimed.
List<List<dynamic>> _territory(Map<String, int> counts) {
  final cells = <List<dynamic>>[];
  var i = 0;
  for (final entry in counts.entries) {
    for (var n = 0; n < entry.value; n++) {
      cells.add([i % 3, i ~/ 3, entry.key]);
      i++;
    }
  }
  return cells;
}

GoalDef _goal() => const GoalDef(
      id: 'balance_goal',
      type: 'balance',
      config: {
        'layer': 'territory',
        'owners': ['terr_wei', 'terr_shu', 'terr_wu'],
        'claimableLayer': 'ground',
        'claimableKind': 'empty',
        'requireComplete': true,
        'requireEqual': true,
      },
    );

/// Same as [_goal] but with `claimableKind` OMITTED — exercises the
/// `?? _layerDefaultKind(...)` fallback in `_countClaimable`, which must
/// resolve to the `ground` layer's declared default (`empty`).
GoalDef _goalNoClaimableKind() => const GoalDef(
      id: 'balance_goal',
      type: 'balance',
      config: {
        'layer': 'territory',
        'owners': ['terr_wei', 'terr_shu', 'terr_wu'],
        'claimableLayer': 'ground',
        'requireComplete': true,
        'requireEqual': true,
      },
    );

GoalStatus _evaluate(GameDefinition game, LevelState state) =>
    GoalEvaluator().evaluate(<GoalDef>[_goal()], state, game, const []);

GoalStatus _evaluateWith(GameDefinition game, LevelState state, GoalDef goal) =>
    GoalEvaluator().evaluate(<GoalDef>[goal], state, game, const []);

/// Evaluates a lone `balance_unreachable` lose condition (resolved to the
/// balance goal via `goalId`) against the given state.
LoseStatus _loseUnreachable(GameDefinition game, LevelState state) =>
    LoseEvaluator().evaluate(
      <LoseConditionDef>[
        LoseConditionDef.fromJson(const {
          'type': 'balance_unreachable',
          'config': {'goalId': 'balance_goal'},
        }),
      ],
      state,
      goals: <GoalDef>[_goal()],
      game: game,
    );

void main() {
  group('balance goal', () {
    test('incomplete board (8/9 owned) is not done', () {
      final game = _makeGame();
      final territory =
          _territory({'terr_wei': 3, 'terr_shu': 3, 'terr_wu': 2});
      final state = _makeState(game, territory);

      final status = _evaluate(game, state);

      expect(status.isWon, isFalse,
          reason: 'incomplete board (8/9 owned) must not be done');
      expect(status.progress['balance_goal'], closeTo(8 / 9, 1e-9));
    });

    test('complete but unequal shares (4/3/2) is not done', () {
      final game = _makeGame();
      final territory =
          _territory({'terr_wei': 4, 'terr_shu': 3, 'terr_wu': 2});
      final state = _makeState(game, territory);

      final status = _evaluate(game, state);

      expect(status.isWon, isFalse,
          reason: 'unequal shares (4/3/2) must not be done');
      expect(status.progress['balance_goal'], closeTo(1.0, 1e-9));
    });

    test('complete and equal shares (3/3/3) is done', () {
      final game = _makeGame();
      final territory =
          _territory({'terr_wei': 3, 'terr_shu': 3, 'terr_wu': 3});
      final state = _makeState(game, territory);

      final status = _evaluate(game, state);

      expect(status.isWon, isTrue,
          reason: 'complete (9/9) and equal shares (3/3/3) must be done');
      expect(status.progress['balance_goal'], closeTo(1.0, 1e-9));
    });

    test('omitted claimableKind falls back to layer default (empty)', () {
      // Reuses the 3/3/3 complete-and-equal fixture but OMITS `claimableKind`
      // from the goal config, so `_countClaimable` must resolve the claimable
      // kind via `_layerDefaultKind` → the `ground` layer's declared
      // `"default": "empty"`. That still makes claimable=9, so the outcome
      // matches the explicit-`empty` case: complete + equal → done, progress 1.0.
      // If `_layerDefaultKind` returned null instead, claimable would be 0 →
      // owned(9) != claimable(0) → complete=false → done=false, and
      // progress would be 1.0 only via the claimable==0 branch but done would
      // still be false — so this case genuinely locks in the fallback.
      final game = _makeGame();
      final territory =
          _territory({'terr_wei': 3, 'terr_shu': 3, 'terr_wu': 3});
      final state = _makeState(game, territory);

      final status = _evaluateWith(game, state, _goalNoClaimableKind());

      expect(status.isWon, isTrue,
          reason: 'omitted claimableKind must fall back to layer default '
              '(empty) → claimable=9 → complete + equal → done');
      expect(status.progress['balance_goal'], closeTo(1.0, 1e-9));
    });
  });

  group('balance_unreachable lose condition', () {
    test('fires when an owner exceeds its equal share (4/3/2)', () {
      // wei owns 4 of 9 (target 3); claims are permanent, so equal thirds can
      // never be reached → lost immediately.
      final game = _makeGame();
      final territory =
          _territory({'terr_wei': 4, 'terr_shu': 3, 'terr_wu': 2});
      final state = _makeState(game, territory);

      final status = _loseUnreachable(game, state);

      expect(status.isLost, isTrue,
          reason: 'an owner over its equal share (4/3/2) must lose');
      expect(status.reason, 'balance_unreachable');
    });

    test('stays quiet on a still-winnable partial (3/3/2)', () {
      final game = _makeGame();
      final territory =
          _territory({'terr_wei': 3, 'terr_shu': 3, 'terr_wu': 2});
      final state = _makeState(game, territory);

      final status = _loseUnreachable(game, state);

      expect(status.isLost, isFalse,
          reason: 'a still-winnable partial (3/3/2) must not lose');
    });

    test('stays quiet on a balanced 3/3/3 state', () {
      final game = _makeGame();
      final territory =
          _territory({'terr_wei': 3, 'terr_shu': 3, 'terr_wu': 3});
      final state = _makeState(game, territory);

      final status = _loseUnreachable(game, state);

      expect(status.isLost, isFalse,
          reason: 'a balanced 3/3/3 state must not trip balance_unreachable');
    });
  });
}
