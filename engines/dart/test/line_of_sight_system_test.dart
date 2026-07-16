import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _game({
  Map<String, dynamic> visibilityConfig = const {},
  List<Map<String, dynamic>> rules = const [],
}) {
  return GameDefinition.fromJson({
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
      {'id': 'objects', 'occupancy': 'zero_or_one'},
      {'id': 'actors', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'floor': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': '.',
      },
      'observer': {
        'layer': 'structures',
        'tags': ['observer', 'sliding_block'],
        'symbol': 'O',
      },
      'blocker': {
        'layer': 'structures',
        'tags': ['sliding_block'],
        'symbol': 'B',
      },
      'beacon': {
        'layer': 'objects',
        'tags': ['visible_target'],
        'symbol': 'T',
      },
      'sensor': {
        'layer': 'actors',
        'tags': ['sensor'],
        'symbol': 'S',
      },
      'wall': {
        'layer': 'objects',
        'tags': ['opaque'],
        'symbol': '#',
      },
      'gate_closed': {
        'layer': 'objects',
        'tags': ['opaque'],
        'symbol': 'G',
      },
      'gate_open': {
        'layer': 'objects',
        'tags': [],
        'symbol': 'g',
      },
    },
    'actions': [
      {
        'id': 'move',
        'params': {
          'position': {'type': 'position'},
          'direction': {
            'type': 'direction',
            'values': ['up', 'down', 'left', 'right'],
          },
        },
      },
    ],
    'systems': [
      {
        'id': 'sliding',
        'type': 'sliding_blocks',
        'config': {
          'validGroundTags': ['walkable'],
          'blockingLayers': ['objects'],
          'blockingTags': ['opaque'],
        },
      },
      {
        'id': 'visibility',
        'type': 'line_of_sight',
        'config': {
          'triggerEvents': ['multi_cell_object_moved'],
          'sourceTags': ['observer'],
          'targetLayer': 'objects',
          'targetTags': ['visible_target'],
          'blockingLayers': ['objects'],
          'blockingTags': ['opaque'],
          ...visibilityConfig,
        },
      },
    ],
    'rules': rules,
    'defaults': {
      'avatar': {'enabled': false},
      'maxCascadeDepth': 3,
    },
  }, id: 'line_of_sight_test');
}

LevelDefinition _level(
  GameDefinition game, {
  List<Map<String, dynamic>> objects = const [],
  List<Map<String, dynamic>> actors = const [],
  List<Map<String, dynamic>> extraMultiCellObjects = const [],
}) {
  return LevelDefinition.fromJson({
    'id': 'visibility',
    'board': {
      'size': [4, 4],
      'layers': {
        'ground': {'format': 'sparse', 'entries': []},
        'objects': {'format': 'sparse', 'entries': objects},
        'actors': {'format': 'sparse', 'entries': actors},
      },
      'multiCellObjects': [
        {
          'id': 'observer',
          'kind': 'observer',
          'cells': [
            {
              'position': [0, 3]
            },
          ],
          'params': {'axis': 'horizontal'},
        },
        ...extraMultiCellObjects,
      ],
    },
    'state': {
      'variables': {'signalsDetected': 0},
      'avatar': {'enabled': false},
    },
    'goals': [],
    'rules': [],
    'solution': {'goldPath': []},
  }, game.layers);
}

void main() {
  test('detects a clear orthogonal sightline after a configured event', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(
        game,
        objects: const [
          {
            'position': [1, 0],
            'kind': 'beacon'
          },
        ],
      ),
    );

    final result = engine.executeTurn(GameAction('move', {
      'position': [0, 3],
      'direction': 'right',
    }));

    final event = result.events.firstWhere(
      (item) => item.type == 'line_of_sight_detected',
    );
    expect(event.position, const Position(1, 0));
    expect(event.payload['sourcePosition'], const Position(1, 3));
    expect(event.payload['sourceId'], 'observer');
    expect(event.payload['sourceKind'], 'observer');
  });

  test('multi-cell objects and configured opaque layers block sight', () {
    final game = _game();
    final covered = TurnEngine(
      game,
      _level(
        game,
        objects: const [
          {
            'position': [1, 0],
            'kind': 'beacon'
          },
        ],
        extraMultiCellObjects: const [
          {
            'id': 'cover',
            'kind': 'blocker',
            'cells': [
              {
                'position': [1, 0]
              },
            ],
            'params': {'axis': 'vertical'},
          },
        ],
      ),
    );
    final coveredResult = covered.executeTurn(GameAction('move', {
      'position': [0, 3],
      'direction': 'right',
    }));
    expect(
      coveredResult.events.where(
        (item) => item.type == 'line_of_sight_detected',
      ),
      isEmpty,
    );

    final opaque = TurnEngine(
      game,
      _level(
        game,
        objects: const [
          {
            'position': [1, 0],
            'kind': 'beacon'
          },
          {
            'position': [1, 2],
            'kind': 'wall'
          },
        ],
      ),
    );
    final opaqueResult = opaque.executeTurn(GameAction('move', {
      'position': [0, 3],
      'direction': 'right',
    }));
    expect(
      opaqueResult.events.where(
        (item) => item.type == 'line_of_sight_detected',
      ),
      isEmpty,
    );
  });

  test('supports layer sources, unlimited matches, and trigger filtering', () {
    final visibilityConfig = <String, dynamic>{
      'sourceLayer': 'actors',
      'sourceKinds': ['sensor'],
      'sourceTags': <String>[],
      'maxMatches': 0,
    };
    final levelObjects = const [
      {
        'position': [2, 1],
        'kind': 'beacon',
      },
      {
        'position': [0, 0],
        'kind': 'beacon',
      },
    ];
    final levelActors = const [
      {
        'position': [0, 1],
        'kind': 'sensor',
      },
    ];

    final game = _game(visibilityConfig: visibilityConfig);
    final engine = TurnEngine(
      game,
      _level(game, objects: levelObjects, actors: levelActors),
    );
    final result = engine.executeTurn(GameAction('move', {
      'position': [0, 3],
      'direction': 'right',
    }));
    expect(
      result.events
          .where((event) => event.type == 'line_of_sight_detected')
          .length,
      2,
    );

    final filteredGame = _game(
      visibilityConfig: {
        ...visibilityConfig,
        'triggerEvents': ['variable_changed'],
      },
    );
    final filteredEngine = TurnEngine(
      filteredGame,
      _level(filteredGame, objects: levelObjects, actors: levelActors),
    );
    final filteredResult = filteredEngine.executeTurn(GameAction('move', {
      'position': [0, 3],
      'direction': 'right',
    }));
    expect(
      filteredResult.events.where(
        (event) => event.type == 'line_of_sight_detected',
      ),
      isEmpty,
    );
  });

  test('detection events compose with ordinary rules', () {
    final game = _game(rules: const [
      {
        'id': 'record_signal',
        'on': 'line_of_sight_detected',
        'where': {
          'event': {'kind': 'beacon'},
        },
        'then': [
          {
            'destroy': {
              'position': r'$event.position',
              'layer': 'objects',
            },
          },
          {
            'increment_variable': {
              'name': 'signalsDetected',
              'amount': 1,
            },
          },
        ],
      },
      {
        'id': 'open_gate',
        'on': 'variable_changed',
        'where': {
          'event': {
            'param': 'variable',
            'equals': 'signalsDetected',
          },
        },
        'then': [
          {
            'transform': {
              'position': [3, 0],
              'layer': 'objects',
              'toKind': 'gate_open',
            },
          },
        ],
      },
    ]);
    final engine = TurnEngine(
      game,
      _level(
        game,
        objects: const [
          {
            'position': [1, 0],
            'kind': 'beacon'
          },
          {
            'position': [3, 0],
            'kind': 'gate_closed'
          },
        ],
      ),
    );

    final result = engine.executeTurn(GameAction('move', {
      'position': [0, 3],
      'direction': 'right',
    }));

    expect(result.accepted, isTrue);
    expect(engine.state.variables['signalsDetected'], 1);
    expect(
      engine.state.board.getEntity('objects', const Position(1, 0)),
      isNull,
    );
    expect(
      engine.state.board.getEntity('objects', const Position(3, 0))?.kind,
      'gate_open',
    );
  });
}
