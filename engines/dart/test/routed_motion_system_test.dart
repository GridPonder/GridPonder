import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

const _routes = <String, dynamic>{
  'road_h': {'left': 'right', 'right': 'left'},
  'road_v': {'up': 'down', 'down': 'up'},
  'corner_ne': {'up': 'right', 'right': 'up'},
  'corner_se': {'right': 'down', 'down': 'right'},
  'corner_sw': {'down': 'left', 'left': 'down'},
  'corner_nw': {'left': 'up', 'up': 'left'},
};

GameDefinition _game() => GameDefinition.fromJson({
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'void'},
        {'id': 'markers', 'occupancy': 'zero_or_one'},
        {'id': 'objects', 'occupancy': 'zero_or_one'},
      ],
      'entityKinds': {
        'void': {'layer': 'ground', 'tags': <String>[], 'symbol': 'V'},
        'road_h': {
          'layer': 'ground',
          'tags': ['route'],
          'symbol': '-',
        },
        'road_v': {
          'layer': 'ground',
          'tags': ['route'],
          'symbol': '|',
        },
        'corner_ne': {
          'layer': 'ground',
          'tags': ['route'],
          'symbol': '1',
        },
        'corner_se': {
          'layer': 'ground',
          'tags': ['route'],
          'symbol': '2',
        },
        'corner_sw': {
          'layer': 'ground',
          'tags': ['route'],
          'symbol': '3',
        },
        'corner_nw': {
          'layer': 'ground',
          'tags': ['route'],
          'symbol': '4',
        },
        'truck': {
          'layer': 'objects',
          'tags': ['routed_mover', 'cargo'],
          'symbol': 'T',
        },
        'barrier': {'layer': 'objects', 'tags': <String>[], 'symbol': 'B'},
        'exit_red': {
          'layer': 'markers',
          'tags': ['route_exit'],
          'symbol': 'E',
        },
      },
      'actions': [
        {
          'id': 'rotate_cell',
          'params': {
            'position': {'type': 'position'},
          },
        },
        {'id': 'advance', 'params': <String, dynamic>{}},
      ],
      'systems': [
        {
          'id': 'rotate_roads',
          'type': 'cell_rotation',
          'config': {
            'cycles': {
              'road_h': 'road_v',
              'road_v': 'road_h',
              'corner_ne': 'corner_se',
              'corner_se': 'corner_sw',
              'corner_sw': 'corner_nw',
              'corner_nw': 'corner_ne',
            },
          },
        },
        {
          'id': 'traffic',
          'type': 'routed_motion',
          'config': {'routes': _routes, 'failureVariable': 'crashes'},
        },
      ],
    }, id: 'routed_motion_test');

Map<String, dynamic> _levelJson({
  List<int> size = const [3, 2],
  List<Map<String, dynamic>> ground = const [],
  List<Map<String, dynamic>> objects = const [],
  List<Map<String, dynamic>> markers = const [],
  bool withGoal = false,
}) =>
    {
      'id': 'route_test',
      'board': {
        'size': size,
        'layers': {
          'ground': {'format': 'sparse', 'entries': ground},
          'objects': {'format': 'sparse', 'entries': objects},
          'markers': {'format': 'sparse', 'entries': markers},
        },
      },
      'state': {
        'avatar': {'enabled': false},
        'variables': {'crashes': 0},
      },
      'goals': withGoal
          ? [
              {
                'id': 'deliver',
                'type': 'all_cleared',
                'config': {'tag': 'cargo'},
              },
            ]
          : <Map<String, dynamic>>[],
      'loseConditions': [
        {
          'type': 'variable_threshold',
          'config': {
            'variable': 'crashes',
            'target': 1,
            'comparison': 'gte',
          },
        },
      ],
    };

Map<String, dynamic> _prototypeLevel() => _levelJson(
      ground: [
        {
          'position': [2, 0],
          'kind': 'road_v'
        },
        {
          'position': [0, 1],
          'kind': 'road_h'
        },
        {
          'position': [1, 1],
          'kind': 'road_h'
        },
        {
          'position': [2, 1],
          'kind': 'corner_se'
        },
      ],
      objects: [
        {
          'position': [0, 1],
          'kind': 'truck',
          'heading': 'right',
          'color': 'red',
        },
      ],
      markers: [
        {
          'position': [2, 0],
          'kind': 'exit_red',
          'color': 'red'
        },
      ],
      withGoal: true,
    );

TurnEngine _engine(Map<String, dynamic> levelJson) {
  final game = _game();
  return TurnEngine(game, LevelDefinition.fromJson(levelJson, game.layers));
}

void main() {
  test('first level gold path prepares the corner before the truck arrives',
      () {
    final engine = _engine(_prototypeLevel());

    expect(
      engine
          .executeTurn(GameAction('rotate_cell', {
            'position': [2, 1]
          }))
          .accepted,
      isTrue,
    );
    expect(
      engine
          .executeTurn(GameAction('rotate_cell', {
            'position': [2, 1]
          }))
          .accepted,
      isTrue,
    );
    final result = engine.executeTurn(const GameAction('advance'));

    expect(result.isWon, isTrue);
    expect(
        engine.state.board.getEntity('objects', const Position(2, 0)), isNull);
    expect(engine.state.actionCount, 3);
  });

  test('an occupied road cannot rotate or tick traffic', () {
    final engine = _engine(_prototypeLevel());

    final result = engine.executeTurn(
      GameAction('rotate_cell', {
        'position': [0, 1]
      }),
    );

    expect(result.accepted, isFalse);
    expect(
      engine.state.board.getEntity('objects', const Position(0, 1)),
      isNotNull,
    );
    expect(engine.state.actionCount, 0);
  });

  test('an unprepared corner loses without partially moving', () {
    final engine = _engine(_prototypeLevel());
    engine.executeTurn(const GameAction('advance'));

    final result = engine.executeTurn(const GameAction('advance'));

    expect(result.isLost, isTrue);
    expect(engine.state.variables['crashes'], 1);
    expect(
      engine.state.board.getEntity('objects', const Position(1, 1)),
      isNotNull,
    );
    expect(
      engine.state.board.getEntity('objects', const Position(2, 1)),
      isNull,
    );
  });

  test('a convoy can enter cells vacated on the same tick', () {
    final engine = _engine(
      _levelJson(
        size: const [4, 1],
        ground: [
          for (var x = 0; x < 4; x++)
            {
              'position': [x, 0],
              'kind': 'road_h'
            },
        ],
        objects: [
          {
            'position': [0, 0],
            'kind': 'truck',
            'heading': 'right'
          },
          {
            'position': [1, 0],
            'kind': 'truck',
            'heading': 'right'
          },
        ],
      ),
    );

    final result = engine.executeTurn(const GameAction('advance'));

    expect(result.accepted, isTrue);
    expect(engine.state.variables['crashes'], 0);
    expect(
      engine.state.board.getEntity('objects', const Position(1, 0)),
      isNotNull,
    );
    expect(
      engine.state.board.getEntity('objects', const Position(2, 0)),
      isNotNull,
    );
  });

  test('two trucks claiming one destination fail atomically', () {
    final engine = _engine(
      _levelJson(
        size: const [3, 1],
        ground: [
          for (var x = 0; x < 3; x++)
            {
              'position': [x, 0],
              'kind': 'road_h'
            },
        ],
        objects: [
          {
            'position': [0, 0],
            'kind': 'truck',
            'heading': 'right'
          },
          {
            'position': [2, 0],
            'kind': 'truck',
            'heading': 'left'
          },
        ],
      ),
    );

    final result = engine.executeTurn(const GameAction('advance'));

    expect(result.isLost, isTrue);
    expect(
      engine.state.board.getEntity('objects', const Position(0, 0)),
      isNotNull,
    );
    expect(
      engine.state.board.getEntity('objects', const Position(2, 0)),
      isNotNull,
    );
    final reasons = result.events
        .where((event) => event.type == 'routed_motion_failed')
        .map((event) => event['reason'])
        .toSet();
    expect(reasons, {'same_destination'});
  });
}
