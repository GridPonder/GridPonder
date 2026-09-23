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
      {'id': 'territory', 'occupancy': 'zero_or_one'},
      {'id': 'actors', 'occupancy': 'zero_or_one'},
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

GameDefinition _makeElasticGame() => GameDefinition.fromJson({
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
        {'id': 'markers', 'occupancy': 'zero_or_one'},
        {'id': 'objects', 'occupancy': 'zero_or_one'},
      ],
      'entityKinds': {
        'floor': {'layer': 'ground', 'symbol': '.'},
        'target': {
          'layer': 'markers',
          'symbol': '1',
          'uiName': 'Target 1',
        },
        'wall': {
          'layer': 'objects',
          'symbol': 'X',
          'uiName': 'Completed target wall',
        },
        'elastic_block': {
          'layer': 'structures',
          'symbol': 'B',
          'uiName': 'Bellows',
        },
      },
      'actions': <dynamic>[],
      'systems': [
        {
          'id': 'bellows_motion',
          'type': 'elastic_block',
          'config': {
            'objectKind': 'elastic_block',
            'targets': [
              {
                'id': 'target_1',
                'markerKind': 'target',
                'onLeave': 'wall',
                'wallKind': 'wall',
              },
            ],
          },
        },
      ],
    });

Map<String, dynamic> _makeElasticLevel() => {
      'id': 'elastic',
      'board': {
        'size': [3, 1],
        'layers': {
          'markers': {
            'format': 'sparse',
            'entries': [
              {
                'position': [1, 0],
                'kind': 'target'
              },
            ],
          },
        },
        'multiCellObjects': [
          {
            'id': 'bellows',
            'kind': 'elastic_block',
            'cells': [
              [1, 0],
            ],
          },
        ],
      },
      'state': {
        'variables': {
          'completedTargetIds': ['target_1'],
          'consumedTargetIds': <dynamic>[],
          'completedTargetCount': 1,
        },
        'avatar': {'enabled': false},
      },
      'goals': <dynamic>[],
    };

GameDefinition _makeOcclusionGame() => GameDefinition.fromJson({
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
        {'id': 'objects', 'occupancy': 'zero_or_one'},
      ],
      'entityKinds': {
        'floor': {'layer': 'ground', 'symbol': '.', 'uiName': 'Open floor'},
        'parking': {
          'layer': 'ground',
          'symbol': ':',
          'uiName': 'Hidden parking floor',
        },
        'key': {
          'layer': 'objects',
          'symbol': 'K',
          'uiName': 'Yellow key',
        },
        'door': {
          'layer': 'objects',
          'symbol': 'L',
          'uiName': 'Locked door',
        },
        'slab': {
          'layer': 'structures',
          'tags': ['observation_occluder', 'public_piece'],
          'symbol': 'B',
          'uiName': 'Blue slab',
        },
      },
      'actions': <dynamic>[],
      'systems': [
        {'id': 'slide', 'type': 'sliding_blocks'},
      ],
    });

Map<String, dynamic> _makeOcclusionLevel() => {
      'id': 'occlusion',
      'board': {
        'size': [4, 1],
        'layers': {
          'ground': {
            'format': 'sparse',
            'entries': [
              {
                'position': [0, 0],
                'kind': 'parking'
              },
              {
                'position': [1, 0],
                'kind': 'parking'
              },
            ],
          },
          'objects': {
            'format': 'sparse',
            'entries': [
              {
                'position': [0, 0],
                'kind': 'key',
                'owner': 'yellow'
              },
              {
                'position': [1, 0],
                'kind': 'door'
              },
            ],
          },
        },
        'multiCellObjects': [
          {
            'id': 'slab_f_yellow_key',
            'kind': 'slab',
            'cells': [
              [0, 0],
              [1, 0],
            ],
            'params': {'axis': 'horizontal'},
          },
        ],
      },
      'state': {
        'avatar': {'enabled': false}
      },
      'goals': <dynamic>[],
    };

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
    // Pack-declared layers (e.g. Liftprint `ink`/`plate`) are drawn in every
    // block in the declared order, last declared on top. Expected strings
    // produced by the Python renderer.
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
          '1Hr.\n..N·\n\n'
          'Each character is one cell, each line is one row. Legend: '
          '.=empty  ·=Open air  r=red ink  1=red mark  '
          'N=counter (exact value in "Number values")  H=Hero\n\n'
          'Number values: (2,1)=7\n\n'
          'Stacked cells (grid shows only top symbol):\n'
          '  (0,0): [plate] 1(red mark) + [ink] r(red ink)\n'
          '  (1,0): [actors] H(Hero) + [plate] 1(red mark) + '
          '[ground] ·(Open air)\n\n'
          'Entity state:\n'
          '  (1,0) Hero: hp=[3, 4]\n'
          '  (2,1) counter: tint=blue\n'
          '  (2,0) red ink: wet=True');
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
          'BCA.\n..N·\n\n'
          'Each character is one cell, each line is one row. Legend: '
          '.=empty  ·=Open air  A=?  B=?  '
          'N=? (exact value in "Number values")  C=?\n\n'
          'Number values: (2,1)=7\n\n'
          'Stacked cells (grid shows only top symbol):\n'
          '  (0,0): B(?) + A(?)\n'
          '  (1,0): C(?) + B(?) + ·(?)\n\n'
          'Entity state:\n'
          '  (1,0) C: hp=[3, 4]\n'
          '  (2,1) D: tint=blue\n'
          '  (2,0) A: wet=True');
    });

    test('layer order: declared order reversed (last declared on top)', () {
      final g = game();
      final engine = _engineFor(g, level());
      expect(TextRenderer.orderedLayers(engine.state, g),
          ['actors', 'plate', 'ink', 'ground']);
    });
  });

  test('observation_background yields the cell to visible content', () {
    // Mirrors test_observation_background_yields_the_cell_to_visible_content.
    final game = GameDefinition.fromJson({
      'id': 'bg',
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
        {'id': 'ink', 'occupancy': 'zero_or_one'},
        {'id': 'pocket', 'occupancy': 'zero_or_one'},
      ],
      'entityKinds': {
        'empty': {'layer': 'ground', 'symbol': '.'},
        'mark': {'layer': 'ground', 'symbol': '1', 'uiName': 'mark'},
        'ink': {'layer': 'ink', 'symbol': 'r', 'uiName': 'ink'},
        'held': {'layer': 'pocket', 'symbol': 'R', 'uiName': 'held ink'},
        'slot': {
          'layer': 'pocket',
          'symbol': 'o',
          'uiName': 'empty slot',
          'tags': ['observation_background'],
        },
      },
    }, id: 'bg');
    final level = LevelDefinition.fromJson({
      'id': 'bg',
      'board': {
        'size': [4, 1],
        'layers': {
          'ground': {
            'format': 'sparse',
            'entries': [
              {'position': [1, 0], 'kind': 'mark'},
            ],
          },
          'ink': {
            'format': 'sparse',
            'entries': [
              {'position': [0, 0], 'kind': 'ink'},
              {'position': [3, 0], 'kind': 'ink'},
            ],
          },
          'pocket': {
            'format': 'sparse',
            'entries': [
              {'position': [0, 0], 'kind': 'slot'},
              {'position': [1, 0], 'kind': 'slot'},
              {'position': [2, 0], 'kind': 'slot'},
              {'position': [3, 0], 'kind': 'held'},
            ],
          },
        },
      },
      'state': {
        'avatar': {'enabled': false},
        'overlay': {'x': 0, 'y': 0, 'width': 2, 'height': 1},
      },
      'goals': [],
    }, game.layers);
    final engine = TurnEngine(game, level);
    final rendered = TextRenderer.render(engine.state, game);
    expect(rendered.split('\n').first, 'r1oR');
    expect(rendered, contains('(0,0): [ink] r(ink) + [pocket] o(empty slot)'));
    expect(
        rendered, contains('(1,0): [ground] 1(mark) + [pocket] o(empty slot)'));
    expect(rendered.split('Stacked cells').last, isNot(contains('(2,0)')));
    expect(rendered, contains('(3,0): [pocket] R(held ink) + [ink] r(ink)'));
    expect(rendered, contains('operate on:\nr1'));
  });

  test('board-unchanged note survives a system status block', () {
    // Mirrors test_board_unchanged_note_survives_a_system_status_block: the
    // runners render the previous board with the level, so the prompt must
    // compare against a render with the same inputs.
    final game = _makeElasticGame();
    final level = LevelDefinition.fromJson(_makeElasticLevel(), game.layers);
    final engine = TurnEngine(game, level);
    final before = TextRenderer.render(engine.state, game,
        includeLegend: false, level: level);
    expect(before, contains('completed, still occupied by Bellows'));
    final obs = AgentObservation.build(game, level, engine.state,
        lastAction: const GameAction('move', {'direction': 'up'}),
        previousBoardText: before);
    expect(LlmAgent.buildPrompt(obs), contains('The board did not change.'));
  });

  test('multi-cell legend and overlap use public game identity', () {
    final game = _makeElasticGame();
    final level = LevelDefinition.fromJson(_makeElasticLevel(), game.layers);
    final engine = TurnEngine(game, level);
    final rendered = TextRenderer.render(engine.state, game, level: level);

    expect(rendered, contains('║/═/╬=Bellows body'));
    expect(rendered, isNot(contains('pipe body')));
    expect(rendered, isNot(contains('pipe exit')));
    expect(
        rendered, contains('[markers] 1(Target 1) + [multi-cell] ╬(Bellows)'));
    expect(rendered, contains('completed, still occupied by Bellows'));
    expect(rendered,
        contains('becomes a wall only after the Bellows fully vacates it'));
  });

  test('consumed target reports original geometry and wall state', () {
    final game = _makeElasticGame();
    final level = LevelDefinition.fromJson(_makeElasticLevel(), game.layers);
    final engine = TurnEngine(game, level);
    engine.state.board.setEntity('markers', const Position(1, 0), null);
    engine.state.board.setEntity(
        'objects', const Position(1, 0), const EntityInstance('wall'));
    engine.state.board.multiCellObjects.first.cells
      ..clear()
      ..add(const Position(2, 0));
    engine.state.variables['consumedTargetIds'] = ['target_1'];

    final rendered = TextRenderer.render(engine.state, game, level: level);
    expect(rendered, contains('Target 1 [1]: cells (1,0)'));
    expect(
        rendered, contains('completed and converted to Completed target wall'));
  });

  test('occluding public piece hides then reveals board contents', () {
    final game = _makeOcclusionGame();
    final engine = _engineFor(game, _makeOcclusionLevel());

    final concealed = TextRenderer.render(engine.state, game);
    expect(concealed.split('\n').first, equals('══..'));
    for (final leaked in [
      'Yellow key',
      'Locked door',
      'Hidden parking floor',
      'slab_f_yellow_key',
    ]) {
      expect(concealed, isNot(contains(leaked)),
          reason: 'concealed observation leaked $leaked');
    }
    expect(concealed, contains('Piece 1 [Blue slab]'));
    expect(concealed, contains('axis: horizontal'));
    expect(concealed, contains('footprint: (0,0) (1,0)'));

    engine.state.board.multiCellObjects.first.cells
      ..clear()
      ..addAll([const Position(2, 0), const Position(3, 0)]);
    final revealed = TextRenderer.render(engine.state, game);
    expect(revealed.split('\n').first, equals('KL══'));
    expect(revealed, contains('Yellow key'));
    expect(revealed, contains('Locked door'));
    expect(revealed, contains('Hidden parking floor'));

    engine.state.board.setEntity('objects', const Position(0, 0), null);
    final collected = TextRenderer.render(engine.state, game);
    expect(collected.split('\n').first, equals(':L══'));
    expect(collected, isNot(contains('Yellow key')));
  });

  test('declared layer order and stacks preserve circuit state', () {
    final game = GameDefinition.fromJson({
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
        {'id': 'territory', 'occupancy': 'zero_or_one'},
        {'id': 'markers', 'occupancy': 'zero_or_one'},
        {'id': 'objects', 'occupancy': 'zero_or_one'},
      ],
      'entityKinds': {
        'floor': {'layer': 'ground', 'symbol': '.'},
        'conduit': {
          'layer': 'territory',
          'symbol': 'c',
          'uiName': 'Powered conduit',
        },
        'contact': {
          'layer': 'markers',
          'symbol': 'A',
          'uiName': 'Closed contact',
        },
        'core': {
          'layer': 'markers',
          'symbol': 'O',
          'uiName': 'Powered core',
        },
        'prism': {
          'layer': 'objects',
          'symbol': 'P',
          'uiName': 'Prism',
        },
      },
      'actions': <dynamic>[],
      'systems': <dynamic>[],
    });
    final level = {
      'id': 'circuit-layers',
      'board': {
        'size': [2, 1],
        'layers': {
          'territory': {
            'format': 'sparse',
            'entries': [
              {
                'position': [0, 0],
                'kind': 'conduit'
              },
              {
                'position': [1, 0],
                'kind': 'conduit'
              },
            ],
          },
          'markers': {
            'format': 'sparse',
            'entries': [
              {
                'position': [0, 0],
                'kind': 'contact'
              },
              {
                'position': [1, 0],
                'kind': 'core'
              },
            ],
          },
          'objects': {
            'format': 'sparse',
            'entries': [
              {
                'position': [0, 0],
                'kind': 'prism'
              },
            ],
          },
        },
      },
      'state': {
        'avatar': {'enabled': false}
      },
      'goals': <dynamic>[],
    };

    final rendered = TextRenderer.render(_engineFor(game, level).state, game);
    expect(rendered.split('\n').first, equals('PO'));
    expect(
        rendered,
        contains('[objects] P(Prism) + [markers] A(Closed contact) + '
            '[territory] c(Powered conduit)'));
    expect(rendered,
        contains('[markers] O(Powered core) + [territory] c(Powered conduit)'));
  });

  test('shared observation symbol hides internal phase', () {
    final game = GameDefinition.fromJson({
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
        {'id': 'markers', 'occupancy': 'zero_or_one'},
      ],
      'entityKinds': {
        'floor': {'layer': 'ground', 'symbol': '.'},
        'yellow_to_green': {
          'layer': 'markers',
          'symbol': 'A',
          'observationSymbol': 'Y',
          'uiName': 'Yellow signal',
        },
        'yellow_to_red': {
          'layer': 'markers',
          'symbol': 'B',
          'observationSymbol': 'Y',
          'uiName': 'Yellow signal',
        },
      },
      'actions': <dynamic>[],
      'systems': <dynamic>[],
    });
    final level = {
      'id': 'hidden-phase',
      'board': {
        'size': [2, 1],
        'layers': {
          'markers': {
            'format': 'sparse',
            'entries': [
              {
                'position': [0, 0],
                'kind': 'yellow_to_green'
              },
              {
                'position': [1, 0],
                'kind': 'yellow_to_red'
              },
            ],
          },
        },
      },
      'state': {
        'avatar': {'enabled': false}
      },
      'goals': <dynamic>[],
    };

    final state = _engineFor(game, level).state;
    final rendered = TextRenderer.render(state, game);
    expect(rendered.split('\n').first, equals('YY'));
    expect('Y=Yellow signal'.allMatches(rendered), hasLength(1));
    expect(rendered.toLowerCase(), isNot(contains('yellow to green')));
    expect(rendered.toLowerCase(), isNot(contains('yellow to red')));

    final labels = buildAnonKindToLabel(game);
    expect(labels['yellow_to_green'], equals(labels['yellow_to_red']));
    final anonymous =
        TextRenderer.render(state, game, kindSymbolOverrides: labels);
    final letter = labels['yellow_to_green']!;
    expect(anonymous.split('\n').first, equals(letter * 2));
    expect('$letter=?'.allMatches(anonymous), hasLength(1));
  });

  // ── Review fixes: mirrors of the Python tests of the same names ─────────

  test('shared observation symbol maps to one anon label', () {
    final game = _makeSharedSymbolGame();
    final labels = buildAnonKindToLabel(game);
    expect(labels, equals({'ore': 'A', 'pad': 'B', 'pickaxe': 'A'}));
    final ore = TextRenderer.render(
        _engineFor(game, _sharedSymbolLevel('ore')).state, game,
        kindSymbolOverrides: labels);
    final pickaxe = TextRenderer.render(
        _engineFor(game, _sharedSymbolLevel('pickaxe')).state, game,
        kindSymbolOverrides: labels);
    expect(pickaxe, equals(ore));
  });

  test('shared observation symbol name is board independent', () {
    final game = _makeSharedSymbolGame();
    final ore = TextRenderer.render(
        _engineFor(game, _sharedSymbolLevel('ore')).state, game);
    final pickaxe = TextRenderer.render(
        _engineFor(game, _sharedSymbolLevel('pickaxe')).state, game);
    expect(pickaxe, equals(ore));
    expect(pickaxe, contains('Q=Lump (a lump)'));
    expect(pickaxe, contains('[objects] Q(Lump) + [markers] p(Pad)'));
    expect(pickaxe, isNot(contains('Pickaxe')));
    expect(pickaxe, isNot(contains('breaks rocks')));
  });

  test('observationSymbol validation rejects avatar and empty', () {
    for (final bad in ['@', '']) {
      expect(
          () => GameDefinition.fromJson({
                'layers': <dynamic>[],
                'entityKinds': {
                  'x': {
                    'layer': 'objects',
                    'symbol': 'x',
                    'observationSymbol': bad
                  },
                },
              }),
          throwsFormatException,
          reason: 'observationSymbol "$bad" was accepted');
    }
  });

  test('anonymous stack omits layer ids', () {
    final game = _makeSharedSymbolGame();
    final rendered = TextRenderer.render(
        _engineFor(game, _sharedSymbolLevel('pickaxe')).state, game,
        kindSymbolOverrides: buildAnonKindToLabel(game));
    expect(rendered, contains('  (0,0): A(?) + B(?)'));
    for (final vocabulary in [
      '[objects]',
      '[markers]',
      'objects',
      'markers',
      'Lump'
    ]) {
      expect(rendered, isNot(contains(vocabulary)));
    }
  });

  test('anonymous occluder and public piece conceal contents', () {
    final game = _makeOcclusionGame();
    final labels = buildAnonKindToLabel(game);
    final engine = _engineFor(game, _makeOcclusionLevel());
    final concealed = TextRenderer.render(engine.state, game,
        kindSymbolOverrides: labels);
    expect(concealed.split('\n').first, equals('══..'));
    final hidden = [labels['key']!, labels['door']!, labels['parking']!];
    for (final leaked in [
      for (final label in hidden) ...['$label=', '$label(', ' $label:'],
      'owner=yellow',
      'slab_f_yellow_key',
      'Blue slab',
      'slab',
    ]) {
      expect(concealed, isNot(contains(leaked)), reason: leaked);
    }
    expect(concealed, contains('Piece 1 [?]'));
    expect(concealed, contains('axis: horizontal'));
    expect(concealed, contains('footprint: (0,0) (1,0)'));
    expect(concealed, contains('multi-cell object body'));

    engine.state.board.multiCellObjects.first.cells
      ..clear()
      ..addAll([const Position(2, 0), const Position(3, 0)]);
    final revealed = TextRenderer.render(engine.state, game,
        kindSymbolOverrides: labels);
    expect(revealed.split('\n').first,
        equals('${labels['key']}${labels['door']}══'));
  });

  test('empty axis is not printed', () {
    final game = _makeOcclusionGame();
    final level = _makeOcclusionLevel();
    ((level['board'] as Map)['multiCellObjects'] as List).first['params'] = {
      'axis': ''
    };
    final rendered = TextRenderer.render(_engineFor(game, level).state, game);
    expect(rendered, isNot(contains('axis')));
  });

  test('axis needs the system that owns it', () {
    final game = _makeOcclusionGame();
    final bare = GameDefinition(
      id: game.id,
      title: game.title,
      layers: game.layers,
      actions: game.actions,
      entityKinds: game.entityKinds,
      systems: const [],
      rules: game.rules,
      levelSequence: game.levelSequence,
      defaults: game.defaults,
    );
    final rendered = TextRenderer.render(
        _engineFor(bare, _makeOcclusionLevel()).state, bare);
    expect(rendered, isNot(contains('axis')));
  });

  test('pipe stack follows grid order without background noise', () {
    final game = _makePipeGame();
    final rendered = TextRenderer.render(_engineFor(game, _pipeLevel()).state,
        game);
    expect(rendered.split('\n').first, equals('◄N.'));
    expect(
        rendered,
        contains('║/═/╬=pipe body  ▲/▼/◄/►=pipe exit '
            '(arrow = exit direction)'));
    expect(rendered, isNot(contains('(0,0):')));
    expect(
        rendered,
        contains('  (1,0): [objects] N(number) + [multi-cell] ═(pipe) + '
            '[ground] #(void)'));
    final labels = buildAnonKindToLabel(game);
    final anonymous = TextRenderer.render(
        _engineFor(game, _pipeLevel()).state, game,
        kindSymbolOverrides: labels);
    expect(anonymous, contains('  (1,0): N(?) + ═(?) + ${labels['void']}(?)'));
    expect(anonymous, contains('multi-cell object exit'));
    expect(anonymous, isNot(contains('pipe')));
  });

  test('system status blocks follow declaration order', () {
    final game = _twoBellowsGame();
    final level = LevelDefinition.fromJson(_twoBellowsLevel(), game.layers);
    final rendered =
        TextRenderer.render(TurnEngine(game, level).state, game, level: level);
    final lump = rendered
        .indexOf('Target status (exact Lump footprint match required):');
    final blob = rendered
        .indexOf('Target status (exact Blob footprint match required):');
    expect(lump, greaterThanOrEqualTo(0));
    expect(blob, greaterThan(lump));
    expect(rendered,
        contains('  Pad [T]: cells (2,0); unfinished (0/1 cells covered)'));
    expect(rendered,
        contains('  Pad [T]: cells (0,0); unfinished (1/1 cells covered)'));
    expect(rendered, isNot(contains('Secret')));
    final anonymous = TextRenderer.render(TurnEngine(game, level).state, game,
        level: level, kindSymbolOverrides: buildAnonKindToLabel(game));
    expect(anonymous, isNot(contains('Target status')));
  });

  test('initial board is parsed once and shared by renders', () {
    final game = _twoBellowsGame();
    final level = LevelDefinition.fromJson(_twoBellowsLevel(), game.layers);
    expect(identical(level.initialBoard, level.initialBoard), isTrue);
    final engine = TurnEngine(game, level);
    final first = TextRenderer.render(engine.state, game, level: level);
    final second = TextRenderer.render(engine.state, game, level: level);
    expect(second, equals(first));
  });
}

GameDefinition _makeSharedSymbolGame() => GameDefinition.fromJson({
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
        {'id': 'markers', 'occupancy': 'zero_or_one'},
        {'id': 'objects', 'occupancy': 'zero_or_one'},
      ],
      'entityKinds': {
        'floor': {'layer': 'ground', 'symbol': '.'},
        'pad': {'layer': 'markers', 'symbol': 'p', 'uiName': 'Pad'},
        'ore': {
          'layer': 'objects',
          'symbol': 'r',
          'observationSymbol': 'Q',
          'uiName': 'Lump',
          'description': 'a lump',
        },
        'pickaxe': {
          'layer': 'objects',
          'symbol': 'k',
          'observationSymbol': 'Q',
          'uiName': 'Pickaxe',
          'description': 'breaks rocks',
        },
      },
      'actions': <dynamic>[],
      'systems': <dynamic>[],
    });

Map<String, dynamic> _sharedSymbolLevel(String kind) => {
      'id': 'shared',
      'board': {
        'size': [2, 1],
        'layers': {
          'markers': {
            'format': 'sparse',
            'entries': [
              {
                'position': [0, 0],
                'kind': 'pad'
              },
            ],
          },
          'objects': {
            'format': 'sparse',
            'entries': [
              {
                'position': [0, 0],
                'kind': kind,
                'charge': 1
              },
            ],
          },
        },
      },
      'state': {
        'avatar': {'enabled': false}
      },
      'goals': <dynamic>[],
    };

GameDefinition _makePipeGame() => GameDefinition.fromJson({
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
        {'id': 'objects', 'occupancy': 'zero_or_one'},
      ],
      'entityKinds': {
        'empty': {'layer': 'ground', 'symbol': '.'},
        'void': {'layer': 'ground', 'symbol': '#'},
        'pipe': {'layer': 'ground', 'symbol': '|'},
        'number': {'layer': 'objects', 'symbol': 'n', 'symbolParam': 'value'},
      },
      'actions': <dynamic>[],
      'systems': <dynamic>[],
    });

Map<String, dynamic> _pipeLevel() => {
      'id': 'pipe',
      'board': {
        'size': [3, 1],
        'layers': {
          'ground': {
            'format': 'sparse',
            'entries': [
              {
                'position': [0, 0],
                'kind': 'void'
              },
              {
                'position': [1, 0],
                'kind': 'void'
              },
            ],
          },
          'objects': {
            'format': 'sparse',
            'entries': [
              {
                'position': [1, 0],
                'kind': 'number',
                'value': 2
              },
            ],
          },
        },
        'multiCellObjects': [
          {
            'id': 'p1',
            'kind': 'pipe',
            'cells': [
              [0, 0],
              [1, 0],
            ],
            'params': {
              'exitPosition': [0, 0],
              'exitDirection': 'left'
            },
          },
        ],
      },
      'state': {
        'avatar': {'enabled': false}
      },
      'goals': <dynamic>[],
    };

GameDefinition _twoBellowsGame() => GameDefinition.fromJson({
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
        {'id': 'markers', 'occupancy': 'zero_or_one'},
      ],
      'entityKinds': {
        'floor': {'layer': 'ground', 'symbol': '.'},
        't_a': {
          'layer': 'markers',
          'symbol': '1',
          'observationSymbol': 'T',
          'uiName': 'Pad'
        },
        't_b': {
          'layer': 'markers',
          'symbol': '2',
          'observationSymbol': 'T',
          'uiName': 'Secret'
        },
        'blob': {'layer': 'structures', 'symbol': 'B', 'uiName': 'Blob'},
        'lump': {'layer': 'structures', 'symbol': 'L', 'uiName': 'Lump'},
      },
      'actions': <dynamic>[],
      'systems': [
        {
          'id': 'second_declared_first',
          'type': 'elastic_block',
          'config': {
            'objectKind': 'lump',
            'targets': [
              {'id': 'b', 'markerKind': 't_b'},
            ],
          },
        },
        {
          'id': 'blob_motion',
          'type': 'elastic_block',
          'config': {
            'objectKind': 'blob',
            'targets': [
              {'id': 'a', 'markerKind': 't_a'},
            ],
          },
        },
      ],
    });

Map<String, dynamic> _twoBellowsLevel() => {
      'id': 'two-bellows',
      'board': {
        'size': [3, 1],
        'layers': {
          'markers': {
            'format': 'sparse',
            'entries': [
              {
                'position': [0, 0],
                'kind': 't_a'
              },
              {
                'position': [2, 0],
                'kind': 't_b'
              },
            ],
          },
        },
        'multiCellObjects': [
          {
            'id': 'blob',
            'kind': 'blob',
            'cells': [
              [0, 0],
            ],
          },
          {
            'id': 'lump',
            'kind': 'lump',
            'cells': [
              [1, 0],
            ],
          },
        ],
      },
      'state': {
        'avatar': {'enabled': false}
      },
      'goals': <dynamic>[],
    };
