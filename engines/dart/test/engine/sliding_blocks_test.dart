import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _game({Map<String, dynamic> config = const {}}) {
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
      'void': {'layer': 'ground', 'tags': [], 'symbol': '#'},
      'exit_floor': {
        'layer': 'ground',
        'tags': ['walkable', 'exit'],
        'symbol': 'E',
      },
      'slider': {
        'layer': 'structures',
        'tags': ['sliding_block'],
        'symbol': 'S',
      },
      'fixed_piece': {
        'layer': 'structures',
        'tags': [],
        'symbol': 'X',
      },
      'coverable_barrier': {
        'layer': 'objects',
        'tags': ['solid', 'coverable'],
        'symbol': 'C',
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
          'moveAction': 'move',
          'validGroundTags': ['walkable'],
          'blockingLayers': ['objects'],
          'blockingTags': ['solid'],
          'coverableTags': ['coverable'],
          'coverableBlockedRoles': ['protected'],
          ...config,
        },
      },
    ],
    'rules': [],
    'defaults': {
      'avatar': {'enabled': false},
    },
  }, id: 'sliding_blocks_test');
}

LevelDefinition _level(
  GameDefinition game,
  String id,
  Map<String, dynamic> board, {
  Map<String, dynamic>? systemOverrides,
}) {
  return LevelDefinition.fromJson({
    'id': id,
    'board': board,
    'state': {
      'variables': {'escapedCount': 0},
      'avatar': {'enabled': false},
    },
    'goals': [],
    'rules': [],
    if (systemOverrides != null) 'systemOverrides': systemOverrides,
    'solution': {'goldPath': []},
  }, game.layers);
}

Map<String, dynamic> _singleBlockBoard({
  String axis = 'horizontal',
  String? role,
  List<int> start = const [0, 0],
  List<int> size = const [3, 2],
  List<Map<String, dynamic>> groundEntries = const [],
  List<Map<String, dynamic>> objectEntries = const [],
  List<Map<String, dynamic>> extraBlocks = const [],
  String? sprite,
}) {
  return {
    'size': size,
    'layers': {
      'ground': {'format': 'sparse', 'entries': groundEntries},
      'objects': {'format': 'sparse', 'entries': objectEntries},
    },
    'multiCellObjects': [
      {
        'id': 'moving',
        'kind': 'slider',
        'cells': [
          {
            'position': start,
            if (sprite != null) 'sprite': sprite,
          },
        ],
        'params': {
          'axis': axis,
          if (role != null) 'role': role,
        },
      },
      ...extraBlocks,
    ],
  };
}

void main() {
  test('vetoed moves leave state, counters, and history unchanged', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(
        game,
        'transactional_veto',
        _singleBlockBoard(
          extraBlocks: const [
            {
              'id': 'fixed',
              'kind': 'fixed_piece',
              'cells': [
                {
                  'position': [1, 0]
                },
              ],
              'params': {'axis': 'fixed'},
            },
          ],
        ),
      ),
    );

    final result = engine.executeTurn(GameAction('move', {
      'position': [0, 0],
      'direction': 'right',
    }));

    expect(result.accepted, isFalse);
    expect(result.events, isEmpty);
    expect(
      engine.state.board.getMultiCellObject('moving')?.cells,
      [const Position(0, 0)],
    );
    expect(engine.state.actionCount, 0);
    expect(engine.state.turnCount, 0);
    expect(engine.undoDepth, 0);
  });

  test('successful moves translate cells and per-cell sprites', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(
        game,
        'translate',
        _singleBlockBoard(sprite: 'piece.png'),
      ),
    );

    final result = engine.executeTurn(GameAction('move', {
      'position': [0, 0],
      'direction': 'right',
    }));

    expect(result.accepted, isTrue);
    expect(
      engine.state.board.getMultiCellObject('moving')?.cells,
      [const Position(1, 0)],
    );
    expect(
      engine.state.board
          .getMultiCellObject('moving')
          ?.cellSprites[const Position(1, 0)],
      'piece.png',
    );
  });

  test('coverable objects can block selected roles only', () {
    final game = _game();
    final board = _singleBlockBoard(
      objectEntries: const [
        {
          'position': [1, 0],
          'kind': 'coverable_barrier',
        },
      ],
    );
    final ordinary = TurnEngine(
      game,
      _level(game, 'ordinary_cover', board),
    );
    expect(
      ordinary
          .executeTurn(GameAction('move', {
            'position': [0, 0],
            'direction': 'right',
          }))
          .accepted,
      isTrue,
    );

    final protected = TurnEngine(
      game,
      _level(
        game,
        'protected_cover',
        _singleBlockBoard(
          role: 'protected',
          objectEntries: const [
            {
              'position': [1, 0],
              'kind': 'coverable_barrier',
            },
          ],
        ),
      ),
    );
    expect(
      protected
          .executeTurn(GameAction('move', {
            'position': [0, 0],
            'direction': 'right',
          }))
          .accepted,
      isFalse,
    );
  });

  test('axis restrictions and valid ground are enforced', () {
    final game = _game();
    final vertical = TurnEngine(
      game,
      _level(
        game,
        'vertical_axis',
        _singleBlockBoard(axis: 'vertical', start: const [1, 0]),
      ),
    );
    expect(
      vertical
          .executeTurn(GameAction('move', {
            'position': [1, 0],
            'direction': 'right',
          }))
          .accepted,
      isFalse,
    );
    expect(
      vertical
          .executeTurn(GameAction('move', {
            'position': [1, 0],
            'direction': 'down',
          }))
          .accepted,
      isTrue,
    );

    final voidBlocked = TurnEngine(
      game,
      _level(
        game,
        'void_ground',
        _singleBlockBoard(
          groundEntries: const [
            {
              'position': [1, 0],
              'kind': 'void'
            },
          ],
        ),
      ),
    );
    expect(
      voidBlocked
          .executeTurn(GameAction('move', {
            'position': [0, 0],
            'direction': 'right',
          }))
          .accepted,
      isFalse,
    );
  });

  test('both-axis blocks reject diagonal and unknown directions', () {
    for (final direction in ['up_right', 'sideways']) {
      final game = _game();
      final engine = TurnEngine(
        game,
        _level(
          game,
          'invalid_direction_$direction',
          _singleBlockBoard(axis: 'both'),
        ),
      );

      final result = engine.executeTurn(GameAction('move', {
        'position': [0, 0],
        'direction': direction,
      }));

      expect(result.accepted, isFalse);
      expect(
        engine.state.board.getMultiCellObject('moving')?.cells,
        [const Position(0, 0)],
      );
    }
  });

  test('only configured escape roles can leave through exit cells', () {
    final game = _game(config: {
      'escapeRoles': ['escapee'],
    });
    final exitBoard = _singleBlockBoard(
      role: 'escapee',
      start: const [1, 0],
      size: const [2, 1],
      groundEntries: const [
        {
          'position': [1, 0],
          'kind': 'exit_floor'
        },
      ],
    );
    final escapee = TurnEngine(
      game,
      _level(game, 'escapee_exit', exitBoard),
    );
    expect(
      escapee
          .executeTurn(GameAction('move', {
            'position': [1, 0],
            'direction': 'right',
          }))
          .accepted,
      isTrue,
    );
    expect(escapee.state.board.multiCellObjects, isEmpty);
    expect(escapee.state.variables['escapedCount'], 1);

    final ordinary = TurnEngine(
      game,
      _level(
        game,
        'ordinary_exit',
        _singleBlockBoard(
          start: const [1, 0],
          size: const [2, 1],
          groundEntries: const [
            {
              'position': [1, 0],
              'kind': 'exit_floor'
            },
          ],
        ),
      ),
    );
    expect(
      ordinary
          .executeTurn(GameAction('move', {
            'position': [1, 0],
            'direction': 'right',
          }))
          .accepted,
      isFalse,
    );
  });

  test('level system overrides replace game-level movement constraints', () {
    final game = _game(config: {
      'validGroundTags': ['unreachable'],
    });
    final engine = TurnEngine(
      game,
      _level(
        game,
        'override',
        _singleBlockBoard(),
        systemOverrides: {
          'sliding': {
            'validGroundTags': ['walkable'],
          },
        },
      ),
    );

    expect(
      engine
          .executeTurn(GameAction('move', {
            'position': [0, 0],
            'direction': 'right',
          }))
          .accepted,
      isTrue,
    );
  });
}
