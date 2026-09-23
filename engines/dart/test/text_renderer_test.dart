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
    expect(rendered, contains('1(Target 1) + ╬(Bellows)'));
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
}
