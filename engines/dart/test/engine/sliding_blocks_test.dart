import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _game({Map<String, dynamic> configOverrides = const {}}) =>
    GameDefinition.fromJson({
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
        'stopper': {'layer': 'structures', 'tags': [], 'symbol': 'X'},
        'key': {
          'layer': 'objects',
          'tags': ['collectible', 'key'],
          'symbol': 'K',
        },
        'gate_locked': {
          'layer': 'objects',
          'tags': ['solid', 'gate'],
          'symbol': 'L',
        },
        'gate_open': {'layer': 'objects', 'tags': [], 'symbol': 'O'},
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
            'coverableTags': ['gate'],
            'coverableBlockedRoles': ['escapee'],
            'lineOfSightCollect': [
              {
                'roles': ['escapee'],
                'layer': 'objects',
                'tags': ['key'],
                'variable': 'keysCollected',
                'remove': true,
              },
            ],
            'objectInteractions': [
              {
                'layer': 'objects',
                'scope': 'board',
                'targetKinds': ['gate_locked'],
                'requiredVariable': 'keysCollected',
                'toKind': 'gate_open',
              },
            ],
            ...configOverrides,
          },
        },
      ],
      'rules': [],
      'defaults': {
        'avatar': {'enabled': false},
      },
    }, id: 'sliding_blocks_test');

LevelDefinition _level(
  GameDefinition game,
  String id,
  Map<String, dynamic> board, {
  int keysCollected = 0,
  Map<String, dynamic>? systemOverrides,
}) =>
    LevelDefinition.fromJson({
      'id': id,
      'board': board,
      'state': {
        'variables': {'keysCollected': keysCollected},
        'avatar': {'enabled': false},
      },
      'goals': [],
      'rules': [],
      if (systemOverrides != null) 'systemOverrides': systemOverrides,
      'solution': {'goldPath': []},
    }, game.layers);

Map<String, dynamic> _transactionBoard() => {
      'size': [3, 2],
      'layers': {
        'ground': {'format': 'sparse', 'entries': []},
        'objects': {
          'format': 'sparse',
          'entries': [
            {
              'position': [1, 0],
              'kind': 'gate_locked'
            },
          ],
        },
      },
      'multiCellObjects': [
        {
          'id': 'moving',
          'kind': 'slider',
          'cells': [
            {
              'position': [0, 0]
            },
            {
              'position': [0, 1]
            },
          ],
          'params': {'axis': 'horizontal'},
        },
        {
          'id': 'collision',
          'kind': 'stopper',
          'cells': [
            {
              'position': [1, 1]
            },
          ],
          'params': {'axis': 'fixed'},
        },
      ],
    };

Map<String, dynamic> _coverableBoard({String? role}) => {
      'size': [3, 1],
      'layers': {
        'ground': {'format': 'sparse', 'entries': []},
        'objects': {
          'format': 'sparse',
          'entries': [
            {
              'position': [1, 0],
              'kind': 'gate_locked'
            },
          ],
        },
      },
      'multiCellObjects': [
        {
          'id': 'moving',
          'kind': 'slider',
          'cells': [
            {
              'position': [0, 0],
              'sprite': 'piece.png'
            },
          ],
          'params': {
            'axis': 'horizontal',
            if (role != null) 'role': role,
          },
        },
      ],
    };

Map<String, dynamic> _sightlineBoard() => {
      'size': [4, 4],
      'layers': {
        'ground': {'format': 'sparse', 'entries': []},
        'objects': {
          'format': 'sparse',
          'entries': [
            {
              'position': [0, 0],
              'kind': 'key'
            },
            {
              'position': [3, 0],
              'kind': 'gate_locked'
            },
          ],
        },
      },
      'multiCellObjects': [
        {
          'id': 'collector',
          'kind': 'slider',
          'cells': [
            {
              'position': [0, 3]
            },
          ],
          'params': {'axis': 'horizontal', 'role': 'escapee'},
        },
        {
          'id': 'key_cover',
          'kind': 'slider',
          'cells': [
            {
              'position': [0, 0]
            },
            {
              'position': [0, 1]
            },
          ],
          'params': {'axis': 'horizontal'},
        },
        {
          'id': 'setup',
          'kind': 'slider',
          'cells': [
            {
              'position': [3, 3]
            },
          ],
          'params': {'axis': 'vertical'},
        },
      ],
    };

Map<String, dynamic> _singleBlockBoard({
  String axis = 'horizontal',
  String? role,
  List<int> start = const [0, 0],
  List<Map<String, dynamic>> groundEntries = const [],
  List<Map<String, dynamic>> objectEntries = const [],
  List<Map<String, dynamic>> extraBlocks = const [],
  List<int> size = const [3, 2],
}) =>
    {
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
            {'position': start},
          ],
          'params': {
            'axis': axis,
            if (role != null) 'role': role,
          },
        },
        ...extraBlocks,
      ],
    };

void main() {
  test('vetoed action leaves state and history unchanged', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(game, 'transaction_veto', _transactionBoard(), keysCollected: 1),
    );

    final result = engine.executeTurn(GameAction('move', {
      'position': [0, 0],
      'direction': 'right',
    }));

    expect(result.accepted, isFalse);
    expect(result.events, isEmpty);
    expect(
      engine.state.board.getEntity('objects', const Position(1, 0))?.kind,
      'gate_locked',
    );
    expect(
      engine.state.board.getMultiCellObject('moving')?.cells,
      [const Position(0, 0), const Position(0, 1)],
    );
    expect(engine.state.actionCount, 0);
    expect(engine.state.turnCount, 0);
    expect(engine.undoDepth, 0);
  });

  test('ordinary blocks can overlap configured coverable objects', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(game, 'coverable', _coverableBoard()),
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
    expect(
      engine.state.board.getEntity('objects', const Position(1, 0))?.kind,
      'gate_locked',
    );
  });

  test('configured roles remain blocked by coverable objects', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(game, 'protected_role', _coverableBoard(role: 'escapee')),
    );

    final result = engine.executeTurn(GameAction('move', {
      'position': [0, 0],
      'direction': 'right',
    }));

    expect(result.accepted, isFalse);
    expect(
      engine.state.board.getMultiCellObject('moving')?.cells,
      [const Position(0, 0)],
    );
  });

  test('uncovering triggers sightline collection and board interaction', () {
    final game = _game();
    final engine = TurnEngine(
      game,
      _level(game, 'sightline', _sightlineBoard()),
    );

    final setup = engine.executeTurn(GameAction('move', {
      'position': [3, 3],
      'direction': 'up',
    }));
    expect(setup.accepted, isTrue);
    expect(engine.state.variables['keysCollected'], 0);
    expect(
      engine.state.board.getEntity('objects', const Position(0, 0))?.kind,
      'key',
    );

    final uncover = engine.executeTurn(GameAction('move', {
      'position': [0, 1],
      'direction': 'right',
    }));
    expect(uncover.accepted, isTrue);
    expect(engine.state.variables['keysCollected'], 1);
    expect(
      engine.state.board.getEntity('objects', const Position(0, 0)),
      isNull,
    );
    expect(
      engine.state.board.getEntity('objects', const Position(3, 0))?.kind,
      'gate_open',
    );
    final event = uncover.events.firstWhere(
      (event) => event.type == 'line_of_sight_collected',
    );
    expect(event.payload['collectorId'], 'collector');
    expect(event.payload['sourcePosition'], const Position(0, 3));
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
        _singleBlockBoard(groundEntries: const [
          {
            'position': [1, 0],
            'kind': 'void'
          },
        ]),
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

  test('only escapees can leave through tagged exits', () {
    final game = _game(configOverrides: {
      'lineOfSightCollect': const [],
      'revealOnUncovered': const [
        {
          'position': [1, 0],
          'layer': 'objects',
          'kind': 'key',
          'revealedVariable': 'exitRevealed',
        },
      ],
    });
    final board = _singleBlockBoard(
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
    final escapee = TurnEngine(game, _level(game, 'escapee_exit', board));
    final escaped = escapee.executeTurn(GameAction('move', {
      'position': [1, 0],
      'direction': 'right',
    }));
    expect(escaped.accepted, isTrue);
    expect(escapee.state.board.multiCellObjects, isEmpty);
    expect(escapee.state.variables['escapedCount'], 1);
    expect(
      escapee.state.board.getEntity('objects', const Position(1, 0))?.kind,
      'key',
    );
    expect(escapee.state.variables['exitRevealed'], isTrue);

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

  test('uncover and enter collection are independently configurable', () {
    final revealGame = _game(configOverrides: {
      'lineOfSightCollect': const [],
      'revealOnUncovered': const [
        {
          'position': [0, 0],
          'layer': 'objects',
          'kind': 'key',
          'revealedVariable': 'keyRevealed',
        },
      ],
    });
    final reveal = TurnEngine(
      revealGame,
      _level(
        revealGame,
        'reveal',
        _singleBlockBoard(size: const [3, 1]),
      ),
    );
    expect(
      reveal
          .executeTurn(GameAction('move', {
            'position': [0, 0],
            'direction': 'right',
          }))
          .accepted,
      isTrue,
    );
    expect(
      reveal.state.board.getEntity('objects', const Position(0, 0))?.kind,
      'key',
    );
    expect(reveal.state.variables['keyRevealed'], isTrue);

    final collectGame = _game(configOverrides: {
      'lineOfSightCollect': const [],
      'collectOnEnter': const [
        {
          'roles': ['escapee'],
          'layer': 'objects',
          'tags': ['key'],
          'variable': 'keysCollected',
        },
      ],
    });
    final collect = TurnEngine(
      collectGame,
      _level(
        collectGame,
        'collect',
        _singleBlockBoard(
          role: 'escapee',
          size: const [3, 1],
          objectEntries: const [
            {
              'position': [1, 0],
              'kind': 'key'
            },
          ],
        ),
      ),
    );
    expect(
      collect
          .executeTurn(GameAction('move', {
            'position': [0, 0],
            'direction': 'right',
          }))
          .accepted,
      isTrue,
    );
    expect(
        collect.state.board.getEntity('objects', const Position(1, 0)), isNull);
    expect(collect.state.variables['keysCollected'], 1);
  });

  test('level system overrides are applied', () {
    final game = _game(configOverrides: {
      'validGroundTags': const ['unreachable'],
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
