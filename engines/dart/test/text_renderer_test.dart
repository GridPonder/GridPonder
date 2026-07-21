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
}
