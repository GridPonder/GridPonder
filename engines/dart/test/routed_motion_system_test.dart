import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

const _routes = <String, dynamic>{
  'road_h': {'left': 'right', 'right': 'left'},
  'road_v': {'up': 'down', 'down': 'up'},
  'corner_ne': {'up': 'right', 'right': 'up'},
  'corner_se': {'right': 'down', 'down': 'right'},
  'corner_sw': {'down': 'left', 'left': 'down'},
  'corner_nw': {'left': 'up', 'up': 'left'},
  'u_turn': {'left': 'left'},
};

GameDefinition _game({
  String movementMode = 'single_step',
  String blockedBehavior = 'fail',
  bool allowUTurns = true,
  bool exitRequiresRoute = true,
  Map<String, dynamic> routes = _routes,
  String? routeSelectorLayer,
}) =>
    GameDefinition.fromJson({
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
        'u_turn': {
          'layer': 'ground',
          'tags': ['route'],
          'symbol': 'U',
        },
        'junction_t': {
          'layer': 'ground',
          'tags': ['route'],
          'symbol': '+',
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
        for (final kind in [
          'selector_up',
          'selector_right',
          'selector_yellow',
        ])
          kind: {
            'layer': 'markers',
            'tags': ['route_selector'],
            'symbol': kind,
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
          'config': {
            'routes': routes,
            'failureVariable': 'crashes',
            'movementMode': movementMode,
            'blockedBehavior': blockedBehavior,
            'allowUTurns': allowUTurns,
            'exitRequiresRoute': exitRequiresRoute,
            if (routeSelectorLayer != null)
              'routeSelectorLayer': routeSelectorLayer,
          },
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

TurnEngine _engine(
  Map<String, dynamic> levelJson, {
  GameDefinition? game,
}) {
  game ??= _game();
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

  group('until_blocked movement', () {
    late GameDefinition flowGame;

    setUp(() {
      flowGame = _game(
        movementMode: 'until_blocked',
        blockedBehavior: 'stop',
        allowUTurns: false,
      );
    });

    test('follows a connected path to an exit in one action', () {
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
              'heading': 'right',
              'color': 'red',
            },
          ],
          markers: [
            {
              'position': [3, 0],
              'kind': 'exit_red',
              'color': 'red',
            },
          ],
          withGoal: true,
        ),
        game: flowGame,
      );

      final result = engine.executeTurn(const GameAction('advance'));

      expect(result.isWon, isTrue);
      expect(engine.state.actionCount, 1);
      expect(engine.state.board.layers['objects']!.entries(), isEmpty);
      final pathEvent = result.events.singleWhere(
        (event) => event.type == 'entity_path_moved',
      );
      expect(pathEvent.payload['path'], const [
        Position(0, 0),
        Position(1, 0),
        Position(2, 0),
        Position(3, 0),
      ]);
      final animation = result.animations.singleWhere(
        (step) => step.type == 'entity_path',
      );
      expect(animation.extra['delivered'], isTrue);
      expect(animation.extra['path'], const [
        [0, 0],
        [1, 0],
        [2, 0],
        [3, 0],
      ]);
    });

    test('matching exit can accept horizontal and vertical arrivals', () {
      final game = _game(
        movementMode: 'until_blocked',
        blockedBehavior: 'stop',
        allowUTurns: false,
        exitRequiresRoute: false,
      );
      final cases = [
        (
          name: 'horizontal',
          size: const [2, 1],
          source: const Position(0, 0),
          target: const Position(1, 0),
          sourceRoad: 'road_h',
          targetRoad: 'road_v',
          heading: 'right',
        ),
        (
          name: 'vertical',
          size: const [1, 2],
          source: const Position(0, 1),
          target: const Position(0, 0),
          sourceRoad: 'road_v',
          targetRoad: 'road_h',
          heading: 'up',
        ),
      ];

      for (final scenario in cases) {
        final engine = _engine(
          _levelJson(
            size: scenario.size,
            ground: [
              {
                'position': [scenario.source.x, scenario.source.y],
                'kind': scenario.sourceRoad,
              },
              {
                'position': [scenario.target.x, scenario.target.y],
                'kind': scenario.targetRoad,
              },
            ],
            objects: [
              {
                'position': [scenario.source.x, scenario.source.y],
                'kind': 'truck',
                'heading': scenario.heading,
                'color': 'red',
              },
            ],
            markers: [
              {
                'position': [scenario.target.x, scenario.target.y],
                'kind': 'exit_red',
                'color': 'red',
              },
            ],
            withGoal: true,
          ),
          game: game,
        );

        final result = engine.executeTurn(const GameAction('advance'));

        expect(result.isWon, isTrue, reason: scenario.name);
        expect(
          engine.state.board.layers['objects']!.entries(),
          isEmpty,
          reason: scenario.name,
        );
      }
    });

    test('junction follows its local selector and waits without one', () {
      final game = _game(
        movementMode: 'until_blocked',
        blockedBehavior: 'stop',
        allowUTurns: false,
        routeSelectorLayer: 'markers',
        routes: {
          ..._routes,
          'junction_t': {
            'left': {
              'selector_up': 'up',
              'selector_right': 'right',
            },
          },
        },
      );

      TurnEngine buildEngine(String selectorKind) => _engine(
            _levelJson(
              size: const [3, 2],
              ground: const [
                {
                  'position': [0, 1],
                  'kind': 'road_h'
                },
                {
                  'position': [1, 1],
                  'kind': 'junction_t'
                },
                {
                  'position': [2, 1],
                  'kind': 'road_h'
                },
                {
                  'position': [1, 0],
                  'kind': 'road_v'
                },
              ],
              objects: const [
                {
                  'position': [0, 1],
                  'kind': 'truck',
                  'heading': 'right',
                  'color': 'red',
                },
              ],
              markers: [
                {
                  'position': [1, 1],
                  'kind': selectorKind,
                },
                {
                  'position': selectorKind == 'selector_up'
                      ? const [1, 0]
                      : const [2, 1],
                  'kind': 'exit_red',
                  'color': 'red',
                },
              ],
              withGoal: true,
            ),
            game: game,
          );

      for (final selector in ['selector_up', 'selector_right']) {
        final engine = buildEngine(selector);
        final result = engine.executeTurn(const GameAction('advance'));

        expect(result.isWon, isTrue, reason: selector);
        final path = result.events.singleWhere(
          (event) => event.type == 'entity_path_moved',
        );
        expect(
          path.payload['path'],
          selector == 'selector_up'
              ? const [Position(0, 1), Position(1, 1), Position(1, 0)]
              : const [Position(0, 1), Position(1, 1), Position(2, 1)],
        );
      }

      final waiting = buildEngine('selector_yellow');
      final result = waiting.executeTurn(const GameAction('advance'));
      expect(result.isWon, isFalse);
      expect(
        waiting.state.board.getEntity('objects', const Position(0, 1)),
        isNotNull,
      );
      expect(
        result.events.any(
          (event) =>
              event.type == 'routed_motion_blocked' &&
              event.payload['reason'] == 'disconnected_road',
        ),
        isTrue,
      );
    });

    test('stops at the last connected cell without crashing', () {
      final engine = _engine(
        _levelJson(
          size: const [3, 1],
          ground: [
            {
              'position': [0, 0],
              'kind': 'road_h'
            },
            {
              'position': [1, 0],
              'kind': 'road_h'
            },
            {
              'position': [2, 0],
              'kind': 'road_v'
            },
          ],
          objects: [
            {
              'position': [0, 0],
              'kind': 'truck',
              'heading': 'right'
            },
          ],
        ),
        game: flowGame,
      );

      final result = engine.executeTurn(const GameAction('advance'));

      expect(result.isLost, isFalse);
      expect(engine.state.variables['crashes'], 0);
      expect(
        engine.state.board.getEntity('objects', const Position(1, 0)),
        isNotNull,
      );
      expect(
        result.events.any(
          (event) =>
              event.type == 'routed_motion_blocked' &&
              event.payload['reason'] == 'disconnected_road',
        ),
        isTrue,
      );
    });

    test('a closed loop runs one lap and terminates at repeated state', () {
      final engine = _engine(
        _levelJson(
          size: const [2, 2],
          ground: [
            {
              'position': [0, 0],
              'kind': 'corner_se'
            },
            {
              'position': [1, 0],
              'kind': 'corner_sw'
            },
            {
              'position': [1, 1],
              'kind': 'corner_nw'
            },
            {
              'position': [0, 1],
              'kind': 'corner_ne'
            },
          ],
          objects: [
            {
              'position': [0, 0],
              'kind': 'truck',
              'heading': 'right'
            },
          ],
        ),
        game: flowGame,
      );

      final result = engine.executeTurn(const GameAction('advance'));

      final path = result.events
          .singleWhere((event) => event.type == 'entity_path_moved')
          .payload['path'];
      expect(path, const [
        Position(0, 0),
        Position(1, 0),
        Position(1, 1),
        Position(0, 1),
        Position(0, 0),
      ]);
      expect(
        result.events.any(
          (event) =>
              event.type == 'routed_motion_blocked' &&
              event.payload['reason'] == 'route_cycle',
        ),
        isTrue,
      );
    });

    test('disallows a configured U-turn and undo restores a travelled path',
        () {
      final uTurnEngine = _engine(
        _levelJson(
          size: const [2, 1],
          ground: [
            {
              'position': [0, 0],
              'kind': 'road_h'
            },
            {
              'position': [1, 0],
              'kind': 'u_turn'
            },
          ],
          objects: [
            {
              'position': [0, 0],
              'kind': 'truck',
              'heading': 'right'
            },
          ],
        ),
        game: flowGame,
      );
      uTurnEngine.executeTurn(const GameAction('advance'));
      expect(
        uTurnEngine.state.board.getEntity('objects', const Position(0, 0)),
        isNotNull,
      );

      final pathEngine = _engine(
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
          ],
        ),
        game: flowGame,
      );
      pathEngine.executeTurn(const GameAction('advance'));
      expect(
        pathEngine.state.board.getEntity('objects', const Position(2, 0)),
        isNotNull,
      );
      pathEngine.undo();
      expect(
        pathEngine.state.board.getEntity('objects', const Position(0, 0)),
        isNotNull,
      );
    });
  });
}
