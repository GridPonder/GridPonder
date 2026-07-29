import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

// Mirrors engines/python/test_flank_capture.py. The harness matches the Pincer
// pack wiring: ground empty/wall + a `pieces` layer of alien/human driven by
// individual_actors + flank_capture.

GameDefinition _game() {
  return GameDefinition.fromJson({
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
      {'id': 'pieces', 'occupancy': 'zero_or_one'},
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
      'alien': {
        'layer': 'pieces',
        'tags': ['actor'],
        'symbol': 'A',
      },
      'human': {
        'layer': 'pieces',
        'tags': [],
        'symbol': 'H',
      },
    },
    'actions': [
      {
        'id': 'tap_cell',
        'params': {
          'position': {'type': 'position'},
        },
      },
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
        'id': 'actors',
        'type': 'individual_actors',
        'config': {
          'actorLayer': 'pieces',
          'actorTag': 'actor',
          'groundLayer': 'ground',
          'wallTag': 'solid',
        },
      },
      {
        'id': 'capture',
        'type': 'flank_capture',
        'config': {
          'pieceLayer': 'pieces',
          'pairs': {'alien': 'human', 'human': 'alien'},
          'order': ['alien', 'human'],
          'wallLayer': 'ground',
          'wallTag': 'solid',
        },
      },
    ],
    'rules': [],
    'defaults': {
      'avatar': {'enabled': false},
      'maxCascadeDepth': 3,
    },
  }, id: 'flank_capture_test');
}

LevelDefinition _level(
  GameDefinition game, {
  required List<int> size,
  required List<Map<String, dynamic>> pieces,
  List<List<int>> walls = const [],
}) {
  return LevelDefinition.fromJson({
    'id': 't',
    'board': {
      'size': size,
      'layers': {
        'ground': {
          'format': 'sparse',
          'entries': [
            for (final w in walls) {'position': w, 'kind': 'wall'},
          ],
        },
        'pieces': {'format': 'sparse', 'entries': pieces},
      },
    },
    'state': {
      'avatar': {'enabled': false},
    },
    'goals': [
      {
        'id': 'clear',
        'type': 'all_cleared',
        'config': {'kind': 'human'},
      },
    ],
    'loseConditions': [],
    'solution': {'goldPath': []},
  }, game.layers);
}

String? _piece(TurnEngine engine, int x, int y) =>
    engine.state.board.getEntity('pieces', Position(x, y))?.kind;

TurnResult _selectMove(TurnEngine engine, List<int> select, String direction) {
  engine.executeTurn(GameAction('tap_cell', {'position': select}));
  return engine.executeTurn(GameAction('move', {'direction': direction}));
}

void main() {
  test('possess a human bracketed between two aliens', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(game, size: [
        5,
        1
      ], pieces: const [
        {
          'position': [0, 0],
          'kind': 'alien'
        },
        {
          'position': [2, 0],
          'kind': 'human'
        },
        {
          'position': [3, 0],
          'kind': 'alien'
        },
      ]),
    );

    final result = _selectMove(engine, [0, 0], 'right');
    expect(_piece(engine, 2, 0), 'alien');
    expect(
      result.events.any((e) =>
          e.type == 'cell_transformed' && e.payload['toKind'] == 'alien'),
      isTrue,
    );
  });

  test('a wall is the second jaw', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(game, size: [
        4,
        1
      ], pieces: const [
        {
          'position': [0, 0],
          'kind': 'alien'
        },
        {
          'position': [2, 0],
          'kind': 'human'
        },
      ], walls: const [
        [3, 0]
      ]),
    );

    _selectMove(engine, [0, 0], 'right');
    expect(_piece(engine, 2, 0), 'alien');
  });

  test('the board edge is not a terminal', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(game, size: [
        4,
        1
      ], pieces: const [
        {
          'position': [1, 0],
          'kind': 'alien'
        },
        {
          'position': [3, 0],
          'kind': 'human'
        },
      ]),
    );

    _selectMove(engine, [1, 0], 'right'); // alien 1->2
    expect(_piece(engine, 3, 0), 'human');
  });

  test('over-reaching exposes the mover', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(game, size: [
        3,
        3
      ], pieces: const [
        {
          'position': [0, 1],
          'kind': 'human'
        },
        {
          'position': [2, 1],
          'kind': 'human'
        },
        {
          'position': [1, 0],
          'kind': 'alien'
        },
      ]),
    );

    _selectMove(engine, [1, 0], 'down');
    expect(_piece(engine, 1, 1), 'human');
  });

  test('single snapshot: possess and expose off the pre-flip board', () {
    // Mover steps down into row y=2 = "human alien(B) human alien". One snapshot
    // means (2,2) is possessed AND still counts as B's right terminal, so B is
    // exposed the same move; a post-possess reading would have spared B.
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(game, size: [
        5,
        5
      ], pieces: const [
        {
          'position': [0, 2],
          'kind': 'human'
        },
        {
          'position': [2, 2],
          'kind': 'human'
        },
        {
          'position': [3, 2],
          'kind': 'alien'
        },
        {
          'position': [1, 1],
          'kind': 'alien'
        },
      ]),
    );

    _selectMove(engine, [1, 1], 'down'); // alien (1,1)->(1,2) = B
    expect(_piece(engine, 2, 2), 'alien'); // possessed
    expect(_piece(engine, 1, 2), 'human'); // exposed (self-flip)
    expect(_piece(engine, 0, 2), 'human'); // terminal untouched
    expect(_piece(engine, 3, 2), 'alien'); // terminal untouched
  });

  test('captures are anchored to the mover', () {
    // A human pair pinned between two walls is not possessed by an alien move
    // elsewhere on the row.
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(game, size: [
        6,
        1
      ], pieces: const [
        {
          'position': [1, 0],
          'kind': 'human'
        },
        {
          'position': [2, 0],
          'kind': 'human'
        },
        {
          'position': [5, 0],
          'kind': 'alien'
        },
      ], walls: const [
        [0, 0],
        [3, 0]
      ]),
    );

    _selectMove(engine, [5, 0], 'left'); // alien 5->4, far from the pair
    expect(_piece(engine, 1, 0), 'human');
    expect(_piece(engine, 2, 0), 'human');
  });

  test('a blocked move captures nothing', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(game, size: [
        4,
        1
      ], pieces: const [
        {
          'position': [0, 0],
          'kind': 'alien'
        },
        {
          'position': [1, 0],
          'kind': 'human'
        },
        {
          'position': [2, 0],
          'kind': 'alien'
        },
      ]),
    );

    final result = _selectMove(engine, [0, 0], 'right'); // blocked by human
    expect(result.events.any((e) => e.type == 'actor_blocked'), isTrue);
    expect(result.events.any((e) => e.type == 'cell_transformed'), isFalse);
    expect(_piece(engine, 1, 0), 'human');
  });
}
