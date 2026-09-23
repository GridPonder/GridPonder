// Parity mirror of engines/python/test_text_renderer.py — same scenario,
// same expected grid string, so the two engines double as an informal
// text-renderer parity check for the `territory` layer.
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
      'systems': <dynamic>[],
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

  test('multi-cell legend and overlap use public game identity', () {
    final game = _makeElasticGame();
    final level = LevelDefinition.fromJson(_makeElasticLevel(), game.layers);
    final engine = TurnEngine(game, level);
    final rendered = TextRenderer.render(engine.state, game, level: level);

    expect(rendered, contains('║/═/╬=Bellows body'));
    expect(rendered, isNot(contains('pipe body')));
    expect(rendered, isNot(contains('pipe exit')));
    expect(
        rendered, contains('[markers] 1(Target 1) + [structures] ╬(Bellows)'));
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

    final anonymous = TextRenderer.render(
      state,
      game,
      includeLegend: false,
      kindSymbolOverrides: {
        'yellow_to_green': 'C',
        'yellow_to_red': 'D',
      },
    );
    expect(anonymous.split('\n').first, equals('CD'));
  });
}
