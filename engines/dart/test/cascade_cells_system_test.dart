import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

Map<String, dynamic> _cell(int charge,
        {int threshold = 4, String kernel = 'plus'}) =>
    {
      'kind': 'cascade_cell',
      'charge': charge,
      'threshold': threshold,
      'kernel': kernel,
    };

GameDefinition _game([Map<String, dynamic> config = const {}]) {
  return GameDefinition.fromJson({
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
      {'id': 'objects', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'floor': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': '.',
      },
      'cascade_cell': {
        'layer': 'objects',
        'tags': ['cascade_cell'],
        'symbol': 'C',
        'symbolParam': 'charge',
        'params': {
          'charge': {'type': 'integer', 'required': true},
          'threshold': {'type': 'integer', 'required': true},
          'kernel': {'type': 'string', 'required': true},
        },
      },
    },
    'actions': [
      {
        'id': 'tap_cell',
        'params': {
          'position': {'type': 'position'}
        },
      },
    ],
    'systems': [
      {'id': 'cascade', 'type': 'cascade_cells', 'config': config},
    ],
    'defaults': {
      'avatar': {'enabled': false}
    },
  }, id: 'cascade_test');
}

LevelDefinition _level(
  GameDefinition game,
  List<List<dynamic>> objects, {
  List<Map<String, dynamic>> goals = const [],
}) {
  return LevelDefinition.fromJson({
    'id': 'cascade_test',
    'board': {
      'size': [objects.first.length, objects.length],
      'layers': {'objects': objects},
    },
    'state': {
      'avatar': {'enabled': false}
    },
    'goals': goals,
    'loseConditions': <dynamic>[],
  }, game.layers);
}

List<List<int>> _charges(TurnEngine engine) => [
      for (var y = 0; y < engine.state.board.height; y++)
        [
          for (var x = 0; x < engine.state.board.width; x++)
            engine.state.board
                .getEntity('objects', Position(x, y))!
                .param('charge') as int,
        ],
    ];

void main() {
  test('center click resolves three waves and matches charge target', () {
    final game = _game();
    final initial = [
      [_cell(1), _cell(3), _cell(1)],
      [_cell(3), _cell(3), _cell(3)],
      [_cell(1), _cell(3), _cell(1)],
    ];
    final target = [
      [
        {'kind': 'cascade_cell', 'charge': 3},
        {'kind': 'cascade_cell', 'charge': 1},
        {'kind': 'cascade_cell', 'charge': 3},
      ],
      [
        {'kind': 'cascade_cell', 'charge': 1},
        {'kind': 'cascade_cell', 'charge': 0},
        {'kind': 'cascade_cell', 'charge': 1},
      ],
      [
        {'kind': 'cascade_cell', 'charge': 3},
        {'kind': 'cascade_cell', 'charge': 1},
        {'kind': 'cascade_cell', 'charge': 3},
      ],
    ];
    final goals = <Map<String, dynamic>>[
      {
        'id': 'target',
        'type': 'board_match',
        'config': {
          'targetLayers': {'objects': target},
          'matchMode': 'exact',
          'matchParams': ['charge'],
        },
      },
    ];
    final engine = TurnEngine(game, _level(game, initial, goals: goals));

    final result = engine.executeTurn(const GameAction('tap_cell', {
      'position': [1, 1]
    }));

    expect(result.accepted, isTrue);
    expect(result.isWon, isTrue);
    expect(_charges(engine), [
      [3, 1, 3],
      [1, 0, 1],
      [3, 1, 3],
    ]);
    expect(
      result.events
          .where((event) => event.type == 'cascade_wave_started')
          .map((event) => event.payload['wave'])
          .toList(),
      [1, 2, 3],
    );
    expect(engine.state.actionCount, 1);
  });

  test('each built-in kernel hits only its offsets', () {
    final expected = <String, Set<Position>>{
      'plus': {
        const Position(2, 1),
        const Position(3, 2),
        const Position(2, 3),
        const Position(1, 2),
      },
      'x': {
        const Position(1, 1),
        const Position(3, 1),
        const Position(3, 3),
        const Position(1, 3),
      },
      'h': {const Position(1, 2), const Position(3, 2)},
      'v': {const Position(2, 1), const Position(2, 3)},
    };
    for (final entry in expected.entries) {
      final game = _game();
      final board = List<List<dynamic>>.generate(
        5,
        (_) => List<dynamic>.generate(5, (_) => _cell(0)),
      );
      board[2][2] = _cell(3, kernel: entry.key);
      final engine = TurnEngine(game, _level(game, board));

      final result = engine.executeTurn(const GameAction('tap_cell', {
        'position': [2, 2]
      }));

      expect(result.accepted, isTrue, reason: entry.key);
      for (var y = 0; y < 5; y++) {
        for (var x = 0; x < 5; x++) {
          final position = Position(x, y);
          final charge = engine.state.board
              .getEntity('objects', position)!
              .param('charge');
          expect(charge, entry.value.contains(position) ? 1 : 0,
              reason: '${entry.key} at $position');
        }
      }
    }
  });

  test('overflow can explode the same cell in consecutive waves', () {
    final game = _game({
      'kernels': {
        'burst': [
          [1, 0],
          [1, 0],
          [1, 0],
          [1, 0],
          [1, 0],
        ],
        'none': <dynamic>[],
      },
    });
    final engine = TurnEngine(
      game,
      _level(game, [
        [_cell(3, kernel: 'burst'), _cell(3, kernel: 'none')]
      ]),
    );

    final result = engine.executeTurn(const GameAction('tap_cell', {
      'position': [0, 0]
    }));

    expect(result.accepted, isTrue);
    expect(_charges(engine), [
      [0, 0]
    ]);
    expect(
      result.events
          .where((event) => event.type == 'cell_exploded')
          .map((event) => [event.position, event.payload['wave']])
          .toList(),
      [
        [const Position(0, 0), 1],
        [const Position(1, 0), 2],
        [const Position(1, 0), 3],
      ],
    );
  });

  test('invalid click is vetoed without counting', () {
    final game = _game();
    final engine = TurnEngine(
        game,
        _level(game, [
          [_cell(0), null]
        ]));
    final beforeCharge = engine.state.board
        .getEntity('objects', const Position(0, 0))!
        .param('charge');

    final result = engine.executeTurn(const GameAction('tap_cell', {
      'position': [1, 0]
    }));

    expect(result.accepted, isFalse);
    expect(
      engine.state.board
          .getEntity('objects', const Position(0, 0))!
          .param('charge'),
      beforeCharge,
    );
    expect(engine.state.actionCount, 0);
  });

  test('wave limit veto rolls back the complete transition', () {
    final game = _game({
      'maxWaves': 2,
      'kernels': {
        'loop': [
          [0, 0],
          [0, 0],
          [0, 0],
          [0, 0],
        ],
      },
    });
    final engine = TurnEngine(
      game,
      _level(game, [
        [_cell(3, kernel: 'loop')]
      ]),
    );
    final beforeCharge = engine.state.board
        .getEntity('objects', const Position(0, 0))!
        .param('charge');

    final result = engine.executeTurn(const GameAction('tap_cell', {
      'position': [0, 0]
    }));

    expect(result.accepted, isFalse);
    expect(
        result.events.map((event) => event.type).toList(), ['action_vetoed']);
    expect(
      engine.state.board
          .getEntity('objects', const Position(0, 0))!
          .param('charge'),
      beforeCharge,
    );
    expect(engine.state.actionCount, 0);
  });

  test('per-cell threshold is respected', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(game, [
        [_cell(1, threshold: 2, kernel: 'h'), _cell(0)]
      ]),
    );

    final result = engine.executeTurn(const GameAction('tap_cell', {
      'position': [0, 0]
    }));

    expect(result.accepted, isTrue);
    expect(_charges(engine), [
      [0, 1]
    ]);
  });
}
