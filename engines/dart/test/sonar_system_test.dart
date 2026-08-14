// Parity mirror of engines/python/test_sonar.py — behavioural cases for the
// `sonar` system.
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

const _paired = {
  'sourceLayer': 'actors',
  'targetLayer': 'seams',
  'pairing': {'digger_a': 'seam_a', 'digger_b': 'seam_b'},
};

GameDefinition _makeGame(Map<String, dynamic>? sonarConfig) {
  final systems = <Map<String, dynamic>>[
    {'id': 'crew', 'type': 'coupled_actors', 'config': <String, dynamic>{}},
  ];
  if (sonarConfig != null) {
    systems.add({'id': 'echo', 'type': 'sonar', 'config': sonarConfig});
  }
  final data = {
    'id': 'com.gridponder.test_sonar',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
      {'id': 'seams', 'occupancy': 'zero_or_one'},
      {'id': 'actors', 'occupancy': 'zero_or_one'},
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
      'seam_a': {
        'layer': 'seams',
        'tags': ['goal_target'],
        'symbol': 'a',
      },
      'seam_b': {
        'layer': 'seams',
        'tags': ['goal_target'],
        'symbol': 'b',
      },
      'digger_a': {
        'layer': 'actors',
        'tags': ['actor'],
        'symbol': '1',
      },
      'digger_b': {
        'layer': 'actors',
        'tags': ['actor'],
        'symbol': '2',
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
    'systems': systems,
  };
  return GameDefinition.fromJson(data, id: 'test_sonar');
}

Map<String, dynamic> _makeLevel({
  required List<List<dynamic>> actors,
  required List<List<dynamic>> seams,
  List<List<int>> walls = const [],
}) {
  final layers = <String, dynamic>{
    'seams': {
      'format': 'sparse',
      'entries': [
        for (final s in seams)
          {
            'position': [s[0], s[1]],
            'kind': s[2],
          }
      ],
    },
    'actors': {
      'format': 'sparse',
      'entries': [
        for (final a in actors)
          {
            'position': [a[0], a[1]],
            'kind': a[2],
          }
      ],
    },
  };
  if (walls.isNotEmpty) {
    layers['ground'] = {
      'format': 'sparse',
      'entries': [
        for (final w in walls)
          {
            'position': [w[0], w[1]],
            'kind': 'wall'
          }
      ],
    };
  }
  return {
    'id': 'test_level',
    'board': {
      'size': [6, 3],
      'layers': layers,
    },
    'state': <String, dynamic>{},
    'goals': <dynamic>[],
    'loseConditions': <dynamic>[],
  };
}

TurnEngine _engineFor(GameDefinition game, Map<String, dynamic> levelJson) {
  final level = LevelDefinition.fromJson(levelJson, game.layers);
  return TurnEngine(game, level);
}

GameAction _move(String dir) => GameAction('move', {'direction': dir});

void main() {
  group('sonar', () {
    test('a reading is written on the first turn', () {
      final engine = _engineFor(
        _makeGame(_paired),
        _makeLevel(actors: [
          [1, 1, 'digger_a']
        ], seams: [
          [4, 1, 'seam_a']
        ]),
      );

      engine.executeTurn(_move('right'));

      expect(engine.state.variables['echo_digger_a'], 2,
          reason: 'digger at (2,1), seam at (4,1) -> 2');
    });

    test('the reading shrinks as the digger approaches', () {
      final engine = _engineFor(
        _makeGame(_paired),
        _makeLevel(actors: [
          [1, 1, 'digger_a']
        ], seams: [
          [4, 1, 'seam_a']
        ]),
      );

      final readings = <dynamic>[];
      for (var i = 0; i < 3; i++) {
        engine.executeTurn(_move('right'));
        readings.add(engine.state.variables['echo_digger_a']);
      }

      expect(readings, equals([2, 1, 0]));
    });

    test('pairing sends each digger its own seam', () {
      final engine = _engineFor(
        _makeGame(_paired),
        _makeLevel(actors: [
          [1, 1, 'digger_a'],
          [2, 1, 'digger_b']
        ], seams: [
          [5, 1, 'seam_a'],
          [0, 1, 'seam_b']
        ]),
      );

      engine.executeTurn(_move('right'));

      expect(engine.state.variables['echo_digger_a'], 3);
      expect(engine.state.variables['echo_digger_b'], 3);
    });

    test('the reading ignores terrain entirely', () {
      // Same geometry with and without a wall in the way must read identically:
      // sonar says how far, never how to get there.
      int readWith(List<List<int>> walls) {
        final engine = _engineFor(
          _makeGame(_paired),
          _makeLevel(actors: [
            [1, 1, 'digger_a']
          ], seams: [
            [3, 1, 'seam_a']
          ], walls: walls),
        );
        engine.executeTurn(_move('down'));
        return engine.state.variables['echo_digger_a'] as int;
      }

      expect(readWith(const []), 3);
      expect(
        readWith(const [
          [2, 1],
          [2, 2]
        ]),
        3,
        reason: 'terrain must not affect the reading',
      );
    });

    test('a source with no paired target reads -1', () {
      final engine = _engineFor(
        _makeGame(_paired),
        _makeLevel(actors: [
          [1, 1, 'digger_b']
        ], seams: [
          [4, 1, 'seam_a']
        ]),
      );

      engine.executeTurn(_move('right'));

      expect(engine.state.variables['echo_digger_b'], -1,
          reason: 'never leave a stale value from a previous turn');
    });

    test('unpaired mode reads the nearest target of any kind', () {
      final engine = _engineFor(
        _makeGame({'sourceLayer': 'actors', 'targetLayer': 'seams'}),
        _makeLevel(actors: [
          [2, 1, 'digger_a']
        ], seams: [
          [5, 1, 'seam_a'],
          [3, 1, 'seam_b']
        ]),
      );

      engine.executeTurn(_move('down'));

      // digger ends at (2,2); seam_b (3,1) is 2 away, seam_a (5,1) is 4
      expect(engine.state.variables['echo_digger_a'], 2);
    });

    test('a custom variablePrefix is honoured', () {
      final engine = _engineFor(
        _makeGame({..._paired, 'variablePrefix': 'dist_'}),
        _makeLevel(actors: [
          [1, 1, 'digger_a']
        ], seams: [
          [4, 1, 'seam_a']
        ]),
      );

      engine.executeTurn(_move('right'));

      expect(engine.state.variables['dist_digger_a'], 2);
      expect(engine.state.variables.containsKey('echo_digger_a'), isFalse);
    });

    test('a missing targetLayer is inert', () {
      // Tolerance contract: both engines must write nothing rather than each
      // inventing a fallback layer.
      final engine = _engineFor(
        _makeGame({'sourceLayer': 'actors'}),
        _makeLevel(actors: [
          [1, 1, 'digger_a']
        ], seams: [
          [4, 1, 'seam_a']
        ]),
      );

      engine.executeTurn(_move('right'));

      expect(engine.state.variables.keys.where((k) => k.startsWith('echo_')),
          isEmpty);
    });

    test('a non-object pairing falls back to nearest', () {
      final engine = _engineFor(
        _makeGame({..._paired, 'pairing': 'digger_a:seam_a'}),
        _makeLevel(actors: [
          [2, 1, 'digger_a']
        ], seams: [
          [5, 1, 'seam_a'],
          [3, 1, 'seam_b']
        ]),
      );

      engine.executeTurn(_move('down'));

      expect(engine.state.variables['echo_digger_a'], 2);
    });

    test('the reading is a pure function of position', () {
      // Returning to a cell must reproduce the reading exactly, or the
      // variable would add spurious state and break solver dedup.
      final engine = _engineFor(
        _makeGame(_paired),
        _makeLevel(actors: [
          [2, 1, 'digger_a']
        ], seams: [
          [5, 1, 'seam_a']
        ]),
      );

      engine.executeTurn(_move('right'));
      final there = engine.state.variables['echo_digger_a'];
      engine.executeTurn(_move('left'));
      engine.executeTurn(_move('right'));
      final back = engine.state.variables['echo_digger_a'];

      expect(there, 2);
      expect(back, equals(there));
    });
  });
}
