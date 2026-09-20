import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _game({
  bool signalFirst = false,
  Map<String, dynamic> cycleConfigOverrides = const {},
}) {
  final json = <String, dynamic>{
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
        'symbol': '-'
      },
      'road_v': {
        'layer': 'ground',
        'tags': ['route'],
        'symbol': '|'
      },
      'car': {
        'layer': 'objects',
        'tags': ['routed_mover', 'vehicle'],
        'symbol': 'C'
      },
      'exit': {
        'layer': 'markers',
        'tags': ['route_exit'],
        'symbol': 'E'
      },
      'signal_red': {
        'layer': 'markers',
        'tags': ['route_signal', 'route_closed'],
        'symbol': 'R'
      },
      'signal_yellow_to_green': {
        'layer': 'markers',
        'tags': ['route_signal', 'route_closed'],
        'symbol': 'A'
      },
      'signal_green': {
        'layer': 'markers',
        'tags': ['route_signal'],
        'symbol': 'G'
      },
      'signal_yellow_to_red': {
        'layer': 'markers',
        'tags': ['route_signal', 'route_closed'],
        'symbol': 'Y'
      },
    },
    'actions': [
      {
        'id': 'rotate_cell',
        'params': {
          'position': {'type': 'position'}
        }
      }
    ],
    'systems': [
      {
        'id': 'rotate_roads',
        'type': 'cell_rotation',
        'config': {
          'cycles': {'road_h': 'road_v', 'road_v': 'road_h'},
          'blockingLayers': ['objects'],
          'blockingTags': ['routed_mover'],
        }
      },
      {
        'id': 'traffic',
        'type': 'routed_motion',
        'config': {
          'routes': {
            'road_h': {'left': 'right', 'right': 'left'},
            'road_v': {'up': 'down', 'down': 'up'},
          },
          'movementMode': 'until_blocked',
          'blockedBehavior': 'stop',
          'matchParam': 'color',
          'exitMatchParam': 'color',
          'gateLayer': 'markers',
        }
      },
      {
        'id': 'signal_clock',
        'type': 'turn_cycle',
        'config': {
          'triggerActions': ['rotate_cell'],
          'layer': 'markers',
          'cycles': {
            'signal_red': 'signal_yellow_to_green',
            'signal_yellow_to_green': 'signal_green',
            'signal_green': 'signal_yellow_to_red',
            'signal_yellow_to_red': 'signal_red',
          },
          ...cycleConfigOverrides,
        }
      },
    ],
  };
  if (signalFirst) {
    final systems = json['systems'] as List<dynamic>;
    final signalClock = systems.removeLast();
    systems.insert(1, signalClock);
  }
  return GameDefinition.fromJson(json, id: 'turn_cycle_test');
}

LevelDefinition _level(GameDefinition game, {bool reverse = false}) {
  final carX = reverse ? 3 : 0;
  final exitX = reverse ? 0 : 3;
  return LevelDefinition.fromJson({
    'id': 'signal_test',
    'board': {
      'size': [4, 2],
      'layers': {
        'ground': {
          'format': 'sparse',
          'entries': [
            for (var x = 0; x < 4; x++)
              {
                'position': [x, 0],
                'kind': 'road_h'
              },
            {
              'position': [0, 1],
              'kind': 'road_h'
            },
          ]
        },
        'markers': {
          'format': 'sparse',
          'entries': [
            {
              'position': [exitX, 0],
              'kind': 'exit'
            },
            {
              'position': [2, 0],
              'kind': 'signal_red',
              'entrySide': 'left'
            },
          ]
        },
        'objects': {
          'format': 'sparse',
          'entries': [
            {
              'position': [carX, 0],
              'kind': 'car',
              'heading': reverse ? 'left' : 'right'
            }
          ]
        },
      }
    },
    'state': {
      'avatar': {'enabled': false},
      'variables': <String, dynamic>{}
    },
    'goals': [
      {
        'id': 'arrive',
        'type': 'all_cleared',
        'config': {'tag': 'vehicle'}
      }
    ],
    'loseConditions': <dynamic>[],
  }, game.layers);
}

void main() {
  test('malformed cycle entries are ignored instead of throwing', () {
    final game = _game(
      cycleConfigOverrides: {
        'cycles': {'signal_red': 7},
      },
    );
    final engine = TurnEngine(game, _level(game));

    final result = engine.executeTurn(
      const GameAction('rotate_cell', {
        'position': [0, 1]
      }),
    );

    expect(result.accepted, isTrue);
    expect(
      engine.state.board.getEntity('markers', const Position(2, 0))!.kind,
      'signal_red',
    );
  });

  test('declaring signal first changes the light before routed movement', () {
    final game = _game(signalFirst: true);
    final engine = TurnEngine(game, _level(game));

    final first = engine.executeTurn(
      const GameAction('rotate_cell', {
        'position': [0, 1]
      }),
    );
    expect(first.accepted, isTrue);
    expect(
      engine.state.board.getEntity('markers', const Position(2, 0))!.kind,
      'signal_yellow_to_green',
    );
    expect(
      engine.state.board.getEntity('objects', const Position(1, 0)),
      isNotNull,
    );

    final second = engine.executeTurn(
      const GameAction('rotate_cell', {
        'position': [0, 1]
      }),
    );
    expect(second.isWon, isTrue);
    expect(
      engine.state.board.getEntity('markers', const Position(2, 0))!.kind,
      'signal_green',
    );
    final lightChangedAt = second.events.indexWhere(
      (event) =>
          event.type == 'cell_transformed' &&
          event.payload['layer'] == 'markers',
    );
    final vehicleMovedAt = second.events.indexWhere(
      (event) => event.type == 'entity_path_moved',
    );
    expect(lightChangedAt, greaterThanOrEqualTo(0));
    expect(vehicleMovedAt, greaterThan(lightChangedAt));
    final vehiclePath = second.animations.singleWhere(
      (animation) => animation.type == 'entity_path',
    );
    expect(vehiclePath.extra['path'], [
      [1, 0],
      [2, 0],
      [3, 0],
    ]);
    expect(vehiclePath.extra['removedAtEnd'], isTrue);

    expect(engine.undo(), isTrue);
    expect(
      engine.state.board.getEntity('markers', const Position(2, 0))!.kind,
      'signal_yellow_to_green',
    );
    expect(
      engine.state.board.getEntity('objects', const Position(1, 0)),
      isNotNull,
    );
  });

  test('current phase blocks before cycle and undo restores phase', () {
    final game = _game();
    final engine = TurnEngine(game, _level(game));

    final first = engine.executeTurn(
      const GameAction('rotate_cell', {
        'position': [0, 1]
      }),
    );
    expect(first.accepted, isTrue);
    expect(
      engine.state.board.getEntity('objects', const Position(1, 0)),
      isNotNull,
    );
    expect(
      engine.state.board.getEntity('markers', const Position(2, 0))!.kind,
      'signal_yellow_to_green',
    );
    expect(
      first.events.any(
        (event) =>
            event.type == 'routed_motion_blocked' &&
            event.payload['reason'] == 'closed_gate',
      ),
      isTrue,
    );

    engine.executeTurn(
      const GameAction('rotate_cell', {
        'position': [0, 1]
      }),
    );
    expect(
      engine.state.board.getEntity('objects', const Position(1, 0)),
      isNotNull,
    );
    expect(
      engine.state.board.getEntity('markers', const Position(2, 0))!.kind,
      'signal_green',
    );

    final third = engine.executeTurn(
      const GameAction('rotate_cell', {
        'position': [0, 1]
      }),
    );
    expect(third.isWon, isTrue);
    expect(
      engine.state.board.getEntity('markers', const Position(2, 0))!.kind,
      'signal_yellow_to_red',
    );

    expect(engine.undo(), isTrue);
    expect(
      engine.state.board.getEntity('objects', const Position(1, 0)),
      isNotNull,
    );
    final restored =
        engine.state.board.getEntity('markers', const Position(2, 0))!;
    expect(restored.kind, 'signal_green');
    expect(restored.param('entrySide'), 'left');
  });

  test('rejected action does not advance signal', () {
    final game = _game();
    final engine = TurnEngine(game, _level(game));

    final result = engine.executeTurn(
      const GameAction('rotate_cell', {
        'position': [0, 0]
      }),
    );

    expect(result.accepted, isFalse);
    expect(
      engine.state.board.getEntity('markers', const Position(2, 0))!.kind,
      'signal_red',
    );
    expect(engine.state.turnCount, 0);
  });

  test('gate controls only its configured entry side', () {
    final game = _game();
    final engine = TurnEngine(game, _level(game, reverse: true));

    final result = engine.executeTurn(
      const GameAction('rotate_cell', {
        'position': [0, 1]
      }),
    );

    expect(result.isWon, isTrue);
    expect(
      engine.state.board.getEntity('objects', const Position(3, 0)),
      isNull,
    );
  });
}
