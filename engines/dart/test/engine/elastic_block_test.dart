import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _game({Map<String, dynamic> config = const {}}) {
  return GameDefinition.fromJson({
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
      {'id': 'objects', 'occupancy': 'zero_or_one'},
      {'id': 'markers', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'floor': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': '.',
      },
      'void': {'layer': 'ground', 'tags': [], 'symbol': '#'},
      'wall': {
        'layer': 'objects',
        'tags': ['solid'],
        'symbol': 'W',
      },
      'crate': {
        'layer': 'objects',
        'tags': ['solid', 'pushable'],
        'symbol': 'C',
      },
      'coin': {'layer': 'objects', 'tags': [], 'symbol': 'O'},
      'target_a': {'layer': 'markers', 'tags': [], 'symbol': 'A'},
      'target_b': {'layer': 'markers', 'tags': [], 'symbol': 'T'},
      'elastic_block': {
        'layer': 'structures',
        'tags': ['solid'],
        'symbol': 'B',
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
        'id': 'elastic',
        'type': 'elastic_block',
        'config': {'objectKind': 'elastic_block', ...config},
      },
    ],
    'rules': [],
    'defaults': {
      'avatar': {'enabled': false},
    },
  }, id: 'elastic_block_test');
}

LevelDefinition _level(
  GameDefinition game,
  List<List<int>> cells, {
  List<int> size = const [4, 4],
  List<Map<String, dynamic>> objects = const [],
  List<Map<String, dynamic>> markers = const [],
}) {
  return LevelDefinition.fromJson({
    'id': 'test',
    'board': {
      'size': size,
      'layers': {
        'ground': {'format': 'sparse', 'entries': []},
        'objects': {'format': 'sparse', 'entries': objects},
        'markers': {'format': 'sparse', 'entries': markers},
      },
      'multiCellObjects': [
        {'id': 'block', 'kind': 'elastic_block', 'cells': cells},
      ],
    },
    'state': {
      'variables': {},
      'avatar': {'enabled': false},
    },
    'goals': [],
    'rules': [],
    'solution': {'goldPath': []},
  }, game.layers);
}

Set<Position> _positions(TurnEngine engine) =>
    engine.state.board.getMultiCellObject('block')!.cells.toSet();

void main() {
  test('empty board follows the worked example', () {
    final game = _game();
    final engine = TurnEngine(
        game,
        _level(game, const [
          [0, 3]
        ]));

    for (final direction in ['up', 'right', 'right', 'up']) {
      expect(
        engine
            .executeTurn(GameAction('move', {'direction': direction}))
            .accepted,
        isTrue,
      );
    }

    expect(_positions(engine), {const Position(3, 0)});
  });

  test('partial blocking stops the whole face', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(
        game,
        const [
          [0, 0],
          [0, 1]
        ],
        size: const [4, 2],
        objects: const [
          {
            'position': [2, 1],
            'kind': 'wall'
          },
        ],
      ),
    );

    final result =
        engine.executeTurn(const GameAction('move', {'direction': 'right'}));

    expect(result.accepted, isTrue);
    expect(_positions(engine), {
      const Position(0, 0),
      const Position(0, 1),
      const Position(1, 0),
      const Position(1, 1),
    });
  });

  test('crate is bulldozed until it jams', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(
        game,
        const [
          [0, 0]
        ],
        size: const [5, 1],
        objects: const [
          {
            'position': [2, 0],
            'kind': 'crate'
          },
          {
            'position': [4, 0],
            'kind': 'wall'
          },
        ],
      ),
    );

    final result =
        engine.executeTurn(const GameAction('move', {'direction': 'right'}));

    expect(result.accepted, isTrue);
    expect(_positions(engine), {
      const Position(0, 0),
      const Position(1, 0),
      const Position(2, 0),
    });
    expect(
      engine.state.board.getEntity('objects', const Position(3, 0))?.kind,
      'crate',
    );
    expect(result.events.where((event) => event.type == 'object_pushed').length,
        1);
  });

  test('blocked press collapses against the leading edge', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(
        game,
        const [
          [0, 0],
          [1, 0],
          [2, 0]
        ],
        size: const [4, 1],
        objects: const [
          {
            'position': [3, 0],
            'kind': 'wall'
          },
        ],
      ),
    );

    final result =
        engine.executeTurn(const GameAction('move', {'direction': 'right'}));

    expect(result.accepted, isTrue);
    expect(_positions(engine), {const Position(2, 0)});
    expect(
        result.events.any((event) => event.type == 'elastic_block_collapsed'),
        isTrue);
  });

  test('blocked one-thick press is rejected transactionally', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(
        game,
        const [
          [2, 0]
        ],
        size: const [4, 1],
        objects: const [
          {
            'position': [3, 0],
            'kind': 'wall'
          },
        ],
      ),
    );

    final result =
        engine.executeTurn(const GameAction('move', {'direction': 'right'}));

    expect(result.accepted, isFalse);
    expect(_positions(engine), {const Position(2, 0)});
    expect(engine.state.actionCount, 0);
  });

  test('crate chain jams without moving', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(
        game,
        const [
          [0, 0]
        ],
        size: const [4, 1],
        objects: const [
          {
            'position': [1, 0],
            'kind': 'crate'
          },
          {
            'position': [2, 0],
            'kind': 'crate'
          },
        ],
      ),
    );

    final result =
        engine.executeTurn(const GameAction('move', {'direction': 'right'}));

    expect(result.accepted, isFalse);
    expect(_positions(engine), {const Position(0, 0)});
    expect(
      engine.state.board.getEntity('objects', const Position(1, 0))?.kind,
      'crate',
    );
    expect(
      engine.state.board.getEntity('objects', const Position(2, 0))?.kind,
      'crate',
    );
  });

  test('chainPush moves adjacent crates together', () {
    final game = _game(config: const {'chainPush': true});
    final engine = TurnEngine(
      game,
      _level(
        game,
        const [
          [0, 0]
        ],
        size: const [5, 1],
        objects: const [
          {
            'position': [1, 0],
            'kind': 'crate'
          },
          {
            'position': [2, 0],
            'kind': 'crate'
          },
        ],
      ),
    );

    final result =
        engine.executeTurn(const GameAction('move', {'direction': 'right'}));

    expect(result.accepted, isTrue);
    expect(_positions(engine), {
      const Position(0, 0),
      const Position(1, 0),
      const Position(2, 0),
    });
    expect(
      engine.state.board.getEntity('objects', const Position(3, 0))?.kind,
      'crate',
    );
    expect(
      engine.state.board.getEntity('objects', const Position(4, 0))?.kind,
      'crate',
    );
    final origins = result.events
        .where((event) => event.type == 'object_pushed')
        .map((event) => event.payload['originPosition'])
        .toSet();
    expect(origins, {const Position(1, 0), const Position(2, 0)});
  });

  test('push does not overwrite a nonblocking entity', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(
        game,
        const [
          [0, 0]
        ],
        size: const [4, 1],
        objects: const [
          {
            'position': [1, 0],
            'kind': 'crate'
          },
          {
            'position': [2, 0],
            'kind': 'coin'
          },
        ],
      ),
    );

    final result =
        engine.executeTurn(const GameAction('move', {'direction': 'right'}));

    expect(result.accepted, isFalse);
    expect(
      engine.state.board.getEntity('objects', const Position(1, 0))?.kind,
      'crate',
    );
    expect(
      engine.state.board.getEntity('objects', const Position(2, 0))?.kind,
      'coin',
    );
  });

  test('completed target transforms only after full exit', () {
    final game = _game(config: {
      'targets': [
        {'id': 'a', 'markerKind': 'target_a', 'onLeave': 'wall'},
      ],
    });
    final engine = TurnEngine(
      game,
      _level(
        game,
        const [
          [0, 3]
        ],
        markers: const [
          {
            'position': [3, 0],
            'kind': 'target_a'
          },
        ],
      ),
    );
    for (final direction in ['up', 'right', 'right', 'up']) {
      engine.executeTurn(GameAction('move', {'direction': direction}));
    }

    expect(engine.state.variables['completedTargetCount'], 1);
    expect(
        engine.state.board.getEntity('objects', const Position(3, 0)), isNull);

    engine.executeTurn(const GameAction('move', {'direction': 'down'}));
    expect(
        engine.state.board.getEntity('objects', const Position(3, 0)), isNull);
    final result =
        engine.executeTurn(const GameAction('move', {'direction': 'down'}));

    expect(
      engine.state.board.getEntity('objects', const Position(3, 0))?.kind,
      'wall',
    );
    expect(
        result.events.any((event) => event.type == 'target_consumed'), isTrue);
    expect(engine.state.variables['completedTargetCount'], 1);
  });

  test('multiple targets require exact matches and can create void', () {
    final game = _game(config: {
      'targets': [
        {'id': 'a', 'markerKind': 'target_a', 'onLeave': 'none'},
        {'id': 'b', 'markerKind': 'target_b', 'onLeave': 'void'},
      ],
    });
    final engine = TurnEngine(
      game,
      _level(
        game,
        const [
          [0, 0]
        ],
        size: const [4, 1],
        markers: const [
          {
            'position': [0, 0],
            'kind': 'target_a'
          },
          {
            'position': [3, 0],
            'kind': 'target_b'
          },
        ],
      ),
    );

    engine.executeTurn(const GameAction('move', {'direction': 'right'}));
    expect(engine.state.variables['completedTargetCount'] ?? 0, 0);
    engine.executeTurn(const GameAction('move', {'direction': 'right'}));
    expect(engine.state.variables['completedTargetIds'], ['b']);
    engine.executeTurn(const GameAction('move', {'direction': 'left'}));
    engine.executeTurn(const GameAction('move', {'direction': 'left'}));

    expect(engine.state.variables['completedTargetIds'], ['a', 'b']);
    expect(engine.state.variables['completedTargetCount'], 2);
    expect(
      engine.state.board.getEntity('ground', const Position(3, 0))?.kind,
      'void',
    );
  });
}
