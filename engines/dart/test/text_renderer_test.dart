// Parity mirror of engines/python/test_text_renderer.py — same scenarios,
// same expected strings, so the two engines double as an informal
// text-renderer parity check (territory layer, pack-declared layers,
// whitespace symbols, entity state).
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _makeGame() {
  final data = {
    'id': 'com.gridponder.test_text_renderer',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
      {'id': 'actors', 'occupancy': 'zero_or_one'},
      {'id': 'territory', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'empty': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': '.',
      },
      'wei': {
        'layer': 'actors',
        'tags': ['actor'],
        'symbol': 'W',
      },
      'terr_wei': {
        'layer': 'territory',
        'tags': ['territory'],
        'symbol': '1',
      },
    },
    'actions': [
      {
        'id': 'move',
        'params': {
          'direction': {
            'type': 'direction',
            'values': ['up', 'down', 'left', 'right'],
          },
        },
      },
    ],
    'systems': [
      {
        'id': 'movement',
        'type': 'coupled_actors',
        'config': {
          'claim': {
            'layer': 'territory',
            'map': {'wei': 'terr_wei'},
          },
        },
      },
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_text_renderer');
}

/// 3x1 board: (0,0) owned-but-empty cell, (1,0) actor standing on an owned
/// cell, (2,0) plain unowned ground.
Map<String, dynamic> _makeLevel() {
  return {
    'id': 'test_level',
    'board': {
      'size': [3, 1],
      'layers': {
        'ground': {'format': 'sparse', 'entries': []},
        'actors': {
          'format': 'sparse',
          'entries': [
            {
              'position': [1, 0],
              'kind': 'wei'
            },
          ],
        },
        'territory': {
          'format': 'sparse',
          'entries': [
            {
              'position': [0, 0],
              'kind': 'terr_wei'
            },
            {
              'position': [1, 0],
              'kind': 'terr_wei'
            },
          ],
        },
      },
    },
    'state': {},
    'goals': [],
    'loseConditions': [],
  };
}

TurnEngine _engineFor(GameDefinition game, Map<String, dynamic> levelJson) {
  final level = LevelDefinition.fromJson(levelJson, game.layers);
  return TurnEngine(game, level);
}

void main() {
  test('territory symbol shown on owned empty cell and hidden under actor', () {
    final game = _makeGame();
    final level = _makeLevel();
    final engine = _engineFor(game, level);

    final rendered =
        TextRenderer.render(engine.state, game, includeLegend: false);
    final gridLine = rendered.split('\n').first;

    expect(gridLine, equals('1W.'), reason: "expected '1W.', got '$gridLine'");
  });

  test('whitespace symbol is rendered visibly', () {
    final game = GameDefinition.fromJson({
      'id': 'ws',
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'void'},
      ],
      'entityKinds': {
        'void': {'layer': 'ground', 'symbol': ' ', 'uiName': 'Open air'},
      },
    }, id: 'ws');
    final engine = _engineFor(game, {
      'id': 'l',
      'board': {
        'size': [2, 1],
        'layers': <String, dynamic>{},
      },
      'state': {
        'avatar': {'enabled': false},
      },
      'goals': [],
    });
    final rendered =
        TextRenderer.render(engine.state, game, includeLegend: false);
    expect(rendered.split('\n').first, '··');
  });

  GameDefinition watcherGame() => GameDefinition.fromJson({
        'id': 'watch',
        'layers': [
          {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
          {'id': 'actors', 'occupancy': 'zero_or_one'},
        ],
        'entityKinds': {
          'empty': {'layer': 'ground', 'symbol': '.'},
          'watcher': {'layer': 'actors', 'symbol': 'W', 'uiName': 'Watcher'},
        },
      }, id: 'watch');

  Map<String, dynamic> watcherLevel() => {
        'id': 'l',
        'board': {
          'size': [2, 1],
          'layers': {
            'actors': {
              'format': 'sparse',
              'entries': [
                {
                  'position': [1, 0],
                  'kind': 'watcher',
                  'behavior': 'stalk',
                  'gaze': 'left',
                },
              ],
            },
          },
        },
        'state': {
          'avatar': {'enabled': false},
        },
        'goals': [],
      };

  test('entity state includes non-symbol parameters', () {
    final game = watcherGame();
    final engine = _engineFor(game, watcherLevel());
    final rendered = TextRenderer.render(engine.state, game);
    expect(rendered, contains('(1,0) Watcher: behavior=stalk, gaze=left'));
  });

  test('anonymous entity state preserves dynamics without kind name', () {
    final game = watcherGame();
    final engine = _engineFor(game, watcherLevel());
    final rendered = TextRenderer.render(engine.state, game,
        kindSymbolOverrides: {'watcher': 'A'});
    expect(rendered, contains('(1,0) A: behavior=stalk, gaze=left'));
    expect(rendered, isNot(contains('Watcher')));
  });

  group('pack-declared layers', () {
    // Layers outside the built-in list (e.g. Liftprint `ink`/`plate`) are
    // drawn in every block: after the known non-ground layers, in board
    // order, above ground. Expected strings produced by the Python renderer.
    GameDefinition game() => GameDefinition.fromJson({
          'id': 'custom',
          'layers': [
            {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
            {'id': 'ink', 'occupancy': 'zero_or_one'},
            {'id': 'plate', 'occupancy': 'zero_or_one'},
            {'id': 'actors', 'occupancy': 'zero_or_one'},
          ],
          'entityKinds': {
            'empty': {'layer': 'ground', 'symbol': '.'},
            'void': {'layer': 'ground', 'symbol': ' ', 'uiName': 'Open air'},
            'ink_red': {'layer': 'ink', 'symbol': 'r', 'uiName': 'red ink'},
            'mark': {'layer': 'plate', 'symbol': '1', 'uiName': 'red mark'},
            'hero': {'layer': 'actors', 'symbol': 'H', 'uiName': 'Hero'},
            'counter': {
              'layer': 'plate',
              'symbol': '?',
              'symbolParam': 'value',
              'uiName': 'counter',
            },
          },
        }, id: 'custom');

    Map<String, dynamic> level() => {
          'id': 'l',
          'board': {
            'size': [4, 2],
            'layers': {
              'ground': [
                ['empty', 'void', 'empty', 'empty'],
                ['empty', 'empty', 'empty', 'void'],
              ],
              'ink': {
                'format': 'sparse',
                'entries': [
                  {
                    'position': [0, 0],
                    'kind': 'ink_red'
                  },
                  {
                    'position': [2, 0],
                    'kind': 'ink_red',
                    'wet': true
                  },
                ],
              },
              'plate': {
                'format': 'sparse',
                'entries': [
                  {
                    'position': [0, 0],
                    'kind': 'mark'
                  },
                  {
                    'position': [1, 0],
                    'kind': 'mark'
                  },
                  {
                    'position': [2, 1],
                    'kind': 'counter',
                    'value': 7,
                    'tint': 'blue'
                  },
                ],
              },
              'actors': {
                'format': 'sparse',
                'entries': [
                  {
                    'position': [1, 0],
                    'kind': 'hero',
                    'hp': [3, 4]
                  },
                ],
              },
            },
          },
          'state': {
            'avatar': {'enabled': false},
          },
          'goals': [],
        };

    test('named render matches the Python renderer', () {
      final g = game();
      final engine = _engineFor(g, level());
      expect(
          TextRenderer.render(engine.state, g),
          'rHr.\n..N·\n\n'
          'Each character is one cell, each line is one row. Legend: '
          '.=empty  ·=Open air  r=red ink  1=red mark  '
          'N=counter (exact value in "Number values")  H=Hero\n\n'
          'Number values: (2,1)=7\n\n'
          'Stacked cells (grid shows only top symbol):\n'
          '  (0,0): r(red ink) + 1(red mark)\n'
          '  (1,0): H(Hero) + 1(red mark) + ·(Open air)\n\n'
          'Entity state:\n'
          '  (1,0) Hero: hp=[3, 4]\n'
          '  (2,0) red ink: wet=True\n'
          '  (2,1) counter: tint=blue');
    });

    test('anonymous render matches the Python renderer', () {
      final g = game();
      final engine = _engineFor(g, level());
      expect(
          TextRenderer.render(engine.state, g, kindSymbolOverrides: {
            'ink_red': 'A',
            'mark': 'B',
            'hero': 'C',
            'counter': 'D',
          }),
          'ACA.\n..N·\n\n'
          'Each character is one cell, each line is one row. Legend: '
          '.=empty  ·=Open air  A=?  B=?  '
          'N=? (exact value in "Number values")  C=?\n\n'
          'Number values: (2,1)=7\n\n'
          'Stacked cells (grid shows only top symbol):\n'
          '  (0,0): A(?) + B(?)\n'
          '  (1,0): C(?) + B(?) + ·(Open air)\n\n'
          'Entity state:\n'
          '  (1,0) C: hp=[3, 4]\n'
          '  (2,0) A: wet=True\n'
          '  (2,1) D: tint=blue');
    });

    test('layer order: known non-ground, then declared, then ground', () {
      final g = game();
      final engine = _engineFor(g, level());
      expect(TextRenderer.orderedLayers(engine.state),
          ['actors', 'ink', 'plate', 'ground']);
    });
  });
}
