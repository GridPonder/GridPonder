// Parity mirror of engines/python/test_balance_goal.py — behavioural cases
// for the `balance` goal type.
import 'package:gridponder_engine/engine.dart';
import 'package:gridponder_engine/src/engine/goal_evaluator.dart';
import 'package:gridponder_engine/src/engine/lose_evaluator.dart';
import 'package:test/test.dart';

// ---------------------------------------------------------------------------
// Fixtures: a 3x3 territory layer over a 3x3 all-`empty` ground (claimable=9).
// ---------------------------------------------------------------------------

GameDefinition _makeGame({bool declareGroundDefault = true}) {
  final groundLayer = <String, dynamic>{
    'id': 'ground',
    'occupancy': 'exactly_one',
    if (declareGroundDefault) 'default': 'empty',
  };
  final data = {
    'id': 'com.gridponder.test_balance_goal',
    'layers': [
      groundLayer,
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
      'contested': {
        'layer': 'ground',
        'tags': ['walkable', 'contested'],
        'symbol': 'C',
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

/// 3x3 ground (claimable=9 when every cell counts), territory cells as given.
///
/// [contestedCells] marks ground cells as the `contested` kind — used by the
/// list-valued `claimableKind` case and by the overwrite-guard tests, where the
/// *board* carrying tagged cells (not the config) is what matters.
LevelState _makeState(GameDefinition game, List<List<dynamic>> territory,
    {int size = 3, List<List<int>> contestedCells = const []}) {
  final boardJson = <String, dynamic>{
    'size': [size, size],
    'layers': {
      'ground': {
        'format': 'sparse',
        'entries': [
          for (final c in contestedCells)
            {
              'position': [c[0], c[1]],
              'kind': 'contested',
            }
        ],
      },
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

/// Same as [_goal] but with a list-valued `claimableKind`, so both `empty` and
/// `contested` ground count toward the claimable total.
GoalDef _goalListClaimableKind() => const GoalDef(
      id: 'balance_goal',
      type: 'balance',
      config: {
        'layer': 'territory',
        'owners': ['terr_wei', 'terr_shu', 'terr_wu'],
        'claimableLayer': 'ground',
        'claimableKind': ['empty', 'contested'],
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

// ---------------------------------------------------------------------------
// Over-claim guard under claim.overwrite (DSL 0.8)
//
// Both balance lose conditions share an over-claim test ("someone holds more
// than their equal share, and claims are permanent, so this is dead"). That
// premise fails when cells can be repainted. The guard is board-level, not
// config-level: a policy declared game-wide is inert on boards that place no
// tagged cells.
// ---------------------------------------------------------------------------

/// A GameDefinition declaring a `tagged` overwrite policy on an actor system.
/// Whether the guard trips is decided by the BOARD carrying tagged cells, not
/// by this config.
GameDefinition _makeGameWithContestedOverwrite({bool enabled = true}) {
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
      'contested': {
        'layer': 'ground',
        'tags': ['walkable', 'contested'],
        'symbol': 'C',
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
    'systems': [
      {
        'id': 'movement',
        'type': 'coupled_actors',
        'enabled': enabled,
        'config': {
          'claim': {
            'layer': 'territory',
            'map': <String, dynamic>{},
            'overwrite': {'mode': 'tagged', 'tag': 'contested'},
          },
        },
      },
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_balance_goal');
}

/// Evaluates one balance lose condition against the list-claimableKind goal.
///
/// The guard tests place contested cells on the board, which would otherwise
/// drop `claimable` from 9 to 8 under a string `claimableKind: 'empty'` — and
/// 8 % 3 != 0 trips the "equal shares are arithmetically impossible" branch
/// *before* the over-claim test, masking what these tests actually check.
LoseStatus _loseWith(GameDefinition game, LevelState state, String type) =>
    LoseEvaluator().evaluate(
      <LoseConditionDef>[
        LoseConditionDef.fromJson({
          'type': type,
          'config': const {'goalId': 'balance_goal'},
        }),
      ],
      state,
      goals: <GoalDef>[_goalListClaimableKind()],
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

    test('connected balance accepts three supplied regions', () {
      final game = _makeGame();
      final state = _makeState(game, const [
        [0, 0, 'terr_wei'],
        [1, 0, 'terr_wei'],
        [2, 0, 'terr_wei'],
        [0, 1, 'terr_shu'],
        [1, 1, 'terr_shu'],
        [2, 1, 'terr_shu'],
        [0, 2, 'terr_wu'],
        [1, 2, 'terr_wu'],
        [2, 2, 'terr_wu'],
      ]);
      final goal = GoalDef(
        id: 'balance_goal',
        type: 'balance',
        config: {
          ..._goal().config,
          'requireConnected': true,
          'connectionSources': const {
            'terr_wei': [0, 0],
            'terr_shu': [0, 1],
            'terr_wu': [0, 2],
          },
        },
      );

      final status = _evaluateWith(game, state, goal);

      expect(status.isWon, isTrue);
      expect(status.progress['balance_goal'], closeTo(1.0, 1e-9));
    });

    test('connected balance rejects an equal but cut-off region', () {
      final game = _makeGame();
      final state = _makeState(game, const [
        [0, 0, 'terr_wei'],
        [1, 0, 'terr_wei'],
        [2, 2, 'terr_wei'],
        [2, 0, 'terr_shu'],
        [2, 1, 'terr_shu'],
        [1, 1, 'terr_shu'],
        [0, 1, 'terr_wu'],
        [0, 2, 'terr_wu'],
        [1, 2, 'terr_wu'],
      ]);
      final goal = GoalDef(
        id: 'balance_goal',
        type: 'balance',
        config: {
          ..._goal().config,
          'requireConnected': true,
          'connectionSources': const {
            'terr_wei': [0, 0],
            'terr_shu': [2, 0],
            'terr_wu': [0, 2],
          },
        },
      );

      final status = _evaluateWith(game, state, goal);

      expect(status.isWon, isFalse);
      expect(status.progress['balance_goal'], closeTo(8 / 9, 1e-9));
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

    test('claimableKind accepts a list of kinds', () {
      // 3x3 with 3 `contested` cells and 6 `empty`. Territory is 3/3/3 = 9 owned.
      //   claimableKind 'empty'                -> claimable=6, owned=9 -> not complete
      //   claimableKind ['empty','contested']  -> claimable=9, owned=9 -> complete + equal
      final game = _makeGame();
      final territory =
          _territory({'terr_wei': 3, 'terr_shu': 3, 'terr_wu': 3});
      final state = _makeState(game, territory, contestedCells: const [
        [0, 0],
        [1, 0],
        [2, 0],
      ]);

      expect(_evaluate(game, state).isWon, isFalse,
          reason: 'string claimableKind counts only `empty` (6), '
              'so 9 owned != 6 claimable');

      final status = _evaluateWith(game, state, _goalListClaimableKind());
      expect(status.isWon, isTrue,
          reason: 'list claimableKind must count empty+contested (9) '
              '-> complete + equal -> done');
      expect(status.progress['balance_goal'], closeTo(1.0, 1e-9));
    });

    test('omitted claimableLayer defaults to ground', () {
      final game = _makeGame();
      final state = _makeState(
        game,
        _territory({'terr_wei': 3, 'terr_shu': 3, 'terr_wu': 3}),
      );
      final config = <String, dynamic>{..._goal().config}
        ..remove('claimableLayer');
      final goal = GoalDef(
        id: 'balance_goal',
        type: 'balance',
        config: config,
      );

      final status = _evaluateWith(game, state, goal);

      expect(status.isWon, isTrue);
      expect(status.progress['balance_goal'], closeTo(1.0, 1e-9));
    });

    test('missing declared default matches effective empty kind', () {
      final game = _makeGame(declareGroundDefault: false);
      final state = _makeState(
        game,
        _territory({'terr_wei': 3, 'terr_shu': 3, 'terr_wu': 3}),
      );
      final goal = _goalNoClaimableKind();

      final status = _evaluateWith(game, state, goal);
      final loseStatus = LoseEvaluator().evaluate(
        <LoseConditionDef>[
          LoseConditionDef.fromJson(const {
            'type': 'balance_unreachable',
            'config': {'goalId': 'balance_goal'},
          }),
        ],
        state,
        goals: [goal],
        game: game,
      );

      expect(status.isWon, isTrue);
      expect(status.progress['balance_goal'], closeTo(1.0, 1e-9));
      expect(loseStatus.isLost, isFalse);
    });

    test('requireComplete false does not win with zero owned territory', () {
      final game = _makeGame();
      final state = _makeState(game, const []);
      final goal = GoalDef(
        id: 'balance_goal',
        type: 'balance',
        config: {
          ..._goal().config,
          'requireComplete': false,
        },
      );

      final status = _evaluateWith(game, state, goal);

      expect(status.isWon, isFalse);
      expect(status.progress['balance_goal'], 0.0);
    });

    test('lose conditions ignore non-complete or non-equal balance goals', () {
      final game = _makeGame();
      final unequalState = _makeState(
        game,
        _territory({'terr_wei': 4, 'terr_shu': 3, 'terr_wu': 2}),
      );
      final partialState = _makeState(
        game,
        _territory({'terr_wei': 1, 'terr_shu': 1, 'terr_wu': 1}),
        size: 4,
      );
      final cases = <(LevelState, GoalDef)>[
        (
          unequalState,
          GoalDef(
            id: 'balance_goal',
            type: 'balance',
            config: {..._goal().config, 'requireEqual': false},
          ),
        ),
        (
          partialState,
          GoalDef(
            id: 'balance_goal',
            type: 'balance',
            config: {..._goal().config, 'requireComplete': false},
          ),
        ),
      ];

      for (final (state, goal) in cases) {
        for (final type in [
          'balance_unreachable',
          'balance_budget_exhausted'
        ]) {
          final status = LoseEvaluator().evaluate(
            <LoseConditionDef>[
              LoseConditionDef.fromJson({
                'type': type,
                'config': const {'goalId': 'balance_goal'},
              }),
            ],
            state,
            goals: [goal],
            game: game,
          );
          expect(status.isLost, isFalse, reason: '$type must be conservative');
        }
      }
    });
  });

  group('balance budget accounting', () {
    test('aggregates budgets for actors mapped to the same owner', () {
      final game = _makeGame();
      final state = _makeState(
        game,
        _territory({'terr_wei': 1, 'terr_shu': 3, 'terr_wu': 3}),
      );
      state.variables['actorMovesRemaining'] = {'worker_a': 1, 'worker_b': 1};
      final status = LoseEvaluator().evaluate(
        <LoseConditionDef>[
          LoseConditionDef.fromJson(const {
            'type': 'balance_budget_exhausted',
            'config': {
              'goalId': 'balance_goal',
              'actorToOwner': {
                'worker_a': 'terr_wei',
                'worker_b': 'terr_wei',
              },
            },
          }),
        ],
        state,
        goals: <GoalDef>[_goal()],
        game: game,
      );

      expect(status.isLost, isFalse);
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

  group('over-claim guard under claim.overwrite', () {
    test('balance_unreachable suppressed when board has contested cells', () {
      // 4/3/2 with a contested cell present: the over-share owner can be
      // repainted back down, so the condition must stay quiet.
      final game = _makeGameWithContestedOverwrite();
      final territory =
          _territory({'terr_wei': 4, 'terr_shu': 3, 'terr_wu': 2});
      final state = _makeState(game, territory, contestedCells: const [
        [0, 0]
      ]);

      final status = _loseWith(game, state, 'balance_unreachable');

      expect(status.isLost, isFalse,
          reason: 'overclaim is recoverable while contested cells exist');
    });

    test('balance_budget_exhausted suppressed when board has contested cells',
        () {
      // THE tk_015 CASE. balance_budget_exhausted carries the same over-claim
      // test as balance_unreachable, and tk_015 uses THIS condition — without
      // the guard it would lose the instant a kingdom steals a contested cell
      // and transiently exceeds its third, which is the level's core action.
      final game = _makeGameWithContestedOverwrite();
      final territory =
          _territory({'terr_wei': 4, 'terr_shu': 3, 'terr_wu': 2});
      final state = _makeState(game, territory, contestedCells: const [
        [0, 0]
      ]);

      final status = _loseWith(game, state, 'balance_budget_exhausted');

      expect(status.isLost, isFalse,
          reason: 'transient overclaim must not lose while contested cells '
              'exist');
    });

    test('over-claim still fires when board has no contested cells', () {
      // A `tagged` overwrite declared game-wide must NOT disable the over-claim
      // test on boards that place no tagged cells. This is what makes it safe
      // to declare the policy once in game.json: without it, every level in the
      // pack silently loses its fail condition and no gold-path test notices.
      final game = _makeGameWithContestedOverwrite();
      final territory =
          _territory({'terr_wei': 4, 'terr_shu': 3, 'terr_wu': 2});
      final state = _makeState(game, territory);

      expect(_loseWith(game, state, 'balance_unreachable').isLost, isTrue,
          reason: 'no contested cells -> overclaim is still terminal');
      expect(_loseWith(game, state, 'balance_budget_exhausted').isLost, isTrue,
          reason: 'no contested cells -> overclaim is still terminal');
    });

    test('disabled actor systems do not make claims overwritable', () {
      final game = _makeGameWithContestedOverwrite(enabled: false);
      final territory =
          _territory({'terr_wei': 4, 'terr_shu': 3, 'terr_wu': 2});
      final state = _makeState(game, territory, contestedCells: const [
        [0, 0]
      ]);

      final status = _loseWith(game, state, 'balance_unreachable');

      expect(status.isLost, isTrue);
    });
  });
}
