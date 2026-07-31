// Parity mirror of engines/python/test_goal_renderer.py — goal text for the
// `balance` goal type, in clear and anonymous mode.
//
// Without a branch of its own a `balance` goal falls through to the renderer's
// default, which emits the goal's *type name* — so an anonymous run was told
// its objective was the literal word "balance".
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _makeGame() {
  final data = {
    'id': 'com.gridponder.test_goal_renderer',
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
      'terr_wei': {
        'layer': 'territory',
        'uiName': 'Wei territory',
        'symbol': 'w',
      },
      'terr_shu': {
        'layer': 'territory',
        'uiName': 'Shu territory',
        'symbol': 's',
      },
      'terr_wu': {
        'layer': 'territory',
        'uiName': 'Wu territory',
        'symbol': 'u',
      },
    },
    'actions': <dynamic>[],
    'systems': <dynamic>[],
  };
  return GameDefinition.fromJson(data, id: 'test_goal_renderer');
}

/// Seven of nine cells claimed: 3 Wei, 2 Shu, 2 Wu.
const _partial = [
  [0, 0, 'terr_wei'],
  [1, 0, 'terr_wei'],
  [2, 0, 'terr_wei'],
  [0, 1, 'terr_shu'],
  [1, 1, 'terr_shu'],
  [0, 2, 'terr_wu'],
  [1, 2, 'terr_wu'],
];

LevelState _makeState(GameDefinition game) {
  final boardJson = {
    'size': [3, 3],
    'layers': {
      'ground': {'format': 'sparse', 'entries': <dynamic>[]},
      'territory': {
        'format': 'sparse',
        'entries': [
          for (final t in _partial)
            {
              'position': [t[0], t[1]],
              'kind': t[2],
            },
        ],
      },
    },
  };
  final board = Board.fromJson(boardJson, game.layers);
  return LevelState.fromJson(const <String, dynamic>{}, board);
}

LevelDefinition _makeLevel(
  GameDefinition game, {
  bool requireEqual = true,
  bool requireComplete = true,
}) {
  return LevelDefinition.fromJson({
    'id': 'lvl',
    'board': {
      'size': [3, 3],
      'layers': <String, dynamic>{},
    },
    'goals': [
      {
        'id': 'balance_goal',
        'type': 'balance',
        'config': {
          'layer': 'territory',
          'owners': ['terr_wei', 'terr_shu', 'terr_wu'],
          'claimableLayer': 'ground',
          'claimableKind': 'empty',
          'requireComplete': requireComplete,
          'requireEqual': requireEqual,
        },
      },
    ],
  }, game.layers);
}

String _render(
  GameDefinition game, {
  bool anonymize = false,
  bool requireEqual = true,
  bool requireComplete = true,
}) {
  return LlmAgent.describeGoals(
    _makeLevel(game,
        requireEqual: requireEqual, requireComplete: requireComplete),
    _makeState(game),
    game,
    anonymize: anonymize,
    kindToLabel: anonymize ? buildAnonKindToLabel(game) : const {},
  );
}

void main() {
  group('balance goal text', () {
    test('is not rendered as the word balance', () {
      final text = _render(_makeGame(), anonymize: true);
      expect(text.trim(), isNot('balance'));
      expect(text.length, greaterThan('balance'.length));
    });

    test('names the owners in clear mode', () {
      final text = _render(_makeGame());
      for (final name in ['Wei territory', 'Shu territory', 'Wu territory']) {
        expect(text, contains(name));
      }
    });

    test('asks for every cell and an equal split', () {
      final text = _render(_makeGame()).toLowerCase();
      expect(text, contains('every'));
      expect(text, contains('equal'));
    });

    test('reports progress against the claimable total', () {
      final text = _render(_makeGame());
      expect(text, contains('7'));
      expect(text, contains('9'));
    });

    test('without requireEqual it does not demand an equal split', () {
      final text = _render(_makeGame(), requireEqual: false).toLowerCase();
      expect(text, isNot(contains('equal')));
    });

    test('without requireComplete it does not demand every cell', () {
      final text = _render(_makeGame(), requireComplete: false).toLowerCase();
      expect(text, isNot(contains('every')));
    });

    test('anonymous mode uses aliases and never the real names', () {
      final text = _render(_makeGame(), anonymize: true);
      for (final leak in ['Wei', 'Shu', 'Wu', 'terr_wei', 'terr_shu']) {
        expect(text, isNot(contains(leak)));
      }
    });

    test('anonymous mode never names the layer', () {
      final text = _render(_makeGame(), anonymize: true).toLowerCase();
      expect(text, isNot(contains('territory')));
    });

    test('anonymous mode still says what to do and how far along', () {
      final game = _makeGame();
      final text = _render(game, anonymize: true);
      final labels = buildAnonKindToLabel(game);
      for (final owner in ['terr_wei', 'terr_shu', 'terr_wu']) {
        expect(text, contains(labels[owner]!));
      }
      expect(text, contains('7'));
      expect(text, contains('9'));
    });
  });
}
