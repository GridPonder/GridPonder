import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

final Map<String, dynamic> pounceSystem = {
  'id': 'pounce',
  'type': 'pounce',
  'config': {
    'hunterRoles': ['bad'],
    'preyRoles': ['good'],
    'variable': 'stolen',
  },
};

GameDefinition _game(
    {bool absorb = false,
    bool pounce = false,
    bool step = false,
    bool blocked = false}) {
  return GameDefinition.fromJson({
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
      {'id': 'objects', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'floor': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': '.'
      },
      'zone': {
        'layer': 'ground',
        'tags': ['walkable', 'target'],
        'symbol': 'T',
        'animations': {
          'eat': {
            'frames': ['a.png', 'b.png'],
            'duration': 400,
            'mode': 'once'
          },
        },
      },
      'zone_fed': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': 'F'
      },
      'box': {
        'layer': 'structures',
        'tags': ['sliding_block'],
        'symbol': 'G'
      },
      'block': {
        'layer': 'structures',
        'tags': ['sliding_block'],
        'symbol': 'S'
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
          'pushableRoles': ['good', 'bad'],
          'pushDirections': ['left', 'right'],
          if (blocked) 'blockedGroundTags': ['target'],
        },
      },
      if (pounce && step) pounceSystem,
      {
        'id': 'gravity',
        'type': 'gravity',
        'config': {
          'fallRoles': ['good', 'bad'],
          if (step) 'stepsPerPass': 1,
          if (absorb)
            'absorb': [
              {
                'role': 'good',
                'groundTag': 'target',
                'toGroundKind': 'zone_fed',
                'animation': 'eat',
                'variable': 'fed',
              },
            ],
          'groundTagVariables': [
            {'role': 'good', 'groundTag': 'target', 'variable': 'onTarget'},
          ],
        },
      },
      if (pounce && !step) pounceSystem,
    ],
    'rules': <Map<String, dynamic>>[],
    'defaults': {
      'avatar': {'enabled': false},
      'maxCascadeDepth': step ? 12 : 4,
    },
  }, id: 'gravity_test');
}

Map<String, dynamic> _obj(
    String id, String kind, List<List<int>> cells, String? role, String axis) {
  return {
    'id': id,
    'kind': kind,
    'cells': [
      for (final c in cells) {'position': c}
    ],
    'params': {'axis': axis, if (role != null) 'role': role},
  };
}

TurnEngine _engine(List<Map<String, dynamic>> objects,
    {bool absorb = false,
    bool pounce = false,
    bool step = false,
    bool blocked = false}) {
  final game =
      _game(absorb: absorb, pounce: pounce, step: step, blocked: blocked);
  final level = LevelDefinition.fromJson({
    'id': 'gravity_level',
    'board': {
      'size': [5, 4],
      'layers': {
        'ground': {
          'format': 'sparse',
          'entries': [
            {
              'position': [3, 3],
              'kind': 'zone'
            }
          ],
        },
        'objects': {'format': 'sparse', 'entries': <Map<String, dynamic>>[]},
      },
      'multiCellObjects': objects,
    },
    'state': {
      'variables': {'onTarget': 0, 'fed': 0, 'stolen': 0},
      'avatar': {'enabled': false},
    },
    'goals': <Map<String, dynamic>>[],
    'rules': <Map<String, dynamic>>[],
    'solution': {'goldPath': <Map<String, dynamic>>[]},
  }, game.layers);
  return TurnEngine(game, level);
}

List<Position> _cells(TurnEngine engine, String id) =>
    engine.state.board.multiCellObjects
        .firstWhere((o) => o.id == id)
        .cells
        .toList();

bool _move(TurnEngine engine, List<int> pos, String dir) => engine
    .executeTurn(GameAction('move', {'position': pos, 'direction': dir}))
    .accepted;

Map<String, dynamic> _ledge(List<List<int>> cells) =>
    _obj('ledge', 'block', cells, null, 'both');
Map<String, dynamic> _pusher(List<int> cell) =>
    _obj('pusher', 'block', [cell], null, 'both');

void main() {
  test('box falls at load', () {
    final engine = _engine([
      _obj(
          'g',
          'box',
          [
            [1, 0]
          ],
          'good',
          'fixed')
    ]);
    expect(_cells(engine, 'g'), [const Position(1, 3)]);
  });

  test('box rests on a block', () {
    final engine = _engine([
      _obj(
          'g',
          'box',
          [
            [1, 0]
          ],
          'good',
          'fixed'),
      _ledge([
        [0, 2],
        [1, 2]
      ]),
    ]);
    expect(_cells(engine, 'g'), [const Position(1, 1)]);
  });

  test('lowering a block lowers the box with it', () {
    final engine = _engine([
      _obj(
          'g',
          'box',
          [
            [1, 0]
          ],
          'good',
          'fixed'),
      _ledge([
        [0, 2],
        [1, 2]
      ]),
    ]);
    expect(_move(engine, [1, 2], 'down'), isTrue);
    expect(_cells(engine, 'g'), [const Position(1, 2)]);
  });

  test('sliding a block out from under drops the box', () {
    final engine = _engine([
      _obj(
          'g',
          'box',
          [
            [1, 0]
          ],
          'good',
          'fixed'),
      _ledge([
        [0, 2],
        [1, 2]
      ]),
    ]);
    expect(_move(engine, [0, 2], 'right'), isTrue);
    expect(_move(engine, [1, 2], 'right'), isTrue);
    expect(_cells(engine, 'g'), [const Position(1, 3)]);
  });

  test('sideways push moves then drops the box onto the target', () {
    final engine = _engine([
      _obj(
          'g',
          'box',
          [
            [1, 1]
          ],
          'good',
          'fixed'),
      _ledge([
        [0, 2],
        [1, 2],
        [2, 2]
      ]),
      _pusher([0, 1]),
    ]);
    expect(_move(engine, [0, 1], 'right'), isTrue);
    expect(_cells(engine, 'g'), [const Position(2, 1)]);
    expect(engine.state.variables['onTarget'], 0);

    expect(_move(engine, [1, 1], 'right'), isTrue);
    expect(_cells(engine, 'pusher'), [const Position(2, 1)]);
    expect(_cells(engine, 'g'), [const Position(3, 3)]);
    expect(engine.state.variables['onTarget'], 1);
  });

  test('a block cannot move vertically into a box', () {
    final engine = _engine([
      _obj(
          'g',
          'box',
          [
            [1, 1]
          ],
          'good',
          'fixed'),
      _ledge([
        [1, 2]
      ]),
      _pusher([1, 0]),
    ]);
    expect(_move(engine, [1, 0], 'down'), isFalse);
    expect(_move(engine, [1, 2], 'up'), isFalse);
  });

  test('pushing a box into the wall is refused', () {
    final engine = _engine([
      _obj(
          'g',
          'box',
          [
            [4, 1]
          ],
          'good',
          'fixed'),
      _ledge([
        [4, 2]
      ]),
      _pusher([3, 1]),
    ]);
    expect(_move(engine, [3, 1], 'right'), isFalse);
    expect(_cells(engine, 'g'), [const Position(4, 1)]);
  });

  test('a pushed box never pushes another box', () {
    final engine = _engine([
      _obj(
          'g',
          'box',
          [
            [1, 1]
          ],
          'good',
          'fixed'),
      _obj(
          'r',
          'box',
          [
            [2, 1]
          ],
          'bad',
          'fixed'),
      _ledge([
        [0, 2],
        [1, 2],
        [2, 2]
      ]),
      _pusher([0, 1]),
    ]);
    expect(_move(engine, [0, 1], 'right'), isFalse);
  });

  test('a box cannot be dragged directly', () {
    final engine = _engine([
      _obj(
          'g',
          'box',
          [
            [1, 0]
          ],
          'good',
          'fixed')
    ]);
    expect(_move(engine, [1, 3], 'left'), isFalse);
  });

  test('an L-shaped block pushes a box in its row', () {
    final engine = _engine([
      _obj(
          'g',
          'box',
          [
            [2, 2]
          ],
          'good',
          'fixed'),
      _ledge([
        [0, 3],
        [1, 3],
        [2, 3]
      ]),
      _obj(
          'ell',
          'block',
          [
            [0, 1],
            [0, 2],
            [1, 2]
          ],
          null,
          'both'),
    ]);
    expect(_move(engine, [0, 2], 'right'), isTrue);
    expect(_cells(engine, 'g'), [const Position(3, 3)]);
    expect(engine.state.variables['onTarget'], 1);
  });

  test('absorb consumes the box, changes the ground and plays the animation',
      () {
    final engine = _engine([
      _obj(
          'g',
          'box',
          [
            [1, 1]
          ],
          'good',
          'fixed'),
      _ledge([
        [0, 2],
        [1, 2],
        [2, 2]
      ]),
      _pusher([0, 1]),
    ], absorb: true);
    expect(_move(engine, [0, 1], 'right'), isTrue);
    final result = engine.executeTurn(const GameAction('move', {
      'position': [1, 1],
      'direction': 'right'
    }));

    expect(result.accepted, isTrue);
    expect(
        engine.state.board.multiCellObjects.any((o) => o.id == 'g'), isFalse);
    expect(engine.state.board.getEntity('ground', const Position(3, 3))?.kind,
        'zone_fed');
    expect(engine.state.variables['fed'], 1);
    expect(result.events.map((e) => e.type),
        contains('multi_cell_object_absorbed'));
    final removed = result.events.where((e) => e.type == 'object_removed');
    expect(removed.map((e) => [e.payload['kind'], e.payload['animation']]), [
      ['zone', 'eat']
    ]);
  });

  test('absorb is off without config', () {
    final engine = _engine([
      _obj(
          'g',
          'box',
          [
            [1, 1]
          ],
          'good',
          'fixed'),
      _ledge([
        [0, 2],
        [1, 2],
        [2, 2]
      ]),
      _pusher([0, 1]),
    ]);
    _move(engine, [0, 1], 'right');
    _move(engine, [1, 1], 'right');
    expect(engine.state.board.multiCellObjects.any((o) => o.id == 'g'), isTrue);
  });

  group('pounce', () {
    bool gone(TurnEngine e, String id) =>
        !e.state.board.multiCellObjects.any((o) => o.id == id);

    test('a hunter runs down a clear row and eats the box', () {
      final engine = _engine([
        _obj(
            'g',
            'box',
            [
              [1, 3]
            ],
            'good',
            'fixed'),
        _obj(
            'r',
            'box',
            [
              [4, 3]
            ],
            'bad',
            'fixed'),
        _pusher([0, 0]),
      ], pounce: true);
      expect(_move(engine, [0, 0], 'right'), isTrue);
      expect(gone(engine, 'g'), isTrue);
      expect(_cells(engine, 'r'), [const Position(1, 3)]);
      expect(engine.state.variables['stolen'], 1);
    });

    test('a block in the way stops the hunter', () {
      final engine = _engine([
        _obj(
            'g',
            'box',
            [
              [1, 3]
            ],
            'good',
            'fixed'),
        _obj(
            'r',
            'box',
            [
              [4, 3]
            ],
            'bad',
            'fixed'),
        _obj(
            'wall',
            'block',
            [
              [2, 3]
            ],
            null,
            'both'),
        _pusher([0, 0]),
      ], pounce: true);
      _move(engine, [0, 0], 'right');
      expect(gone(engine, 'g'), isFalse);
      expect(engine.state.variables['stolen'], 0);
    });

    test('moving the blocker away opens the line', () {
      final engine = _engine([
        _obj(
            'g',
            'box',
            [
              [1, 3]
            ],
            'good',
            'fixed'),
        _obj(
            'r',
            'box',
            [
              [4, 3]
            ],
            'bad',
            'fixed'),
        _obj(
            'wall',
            'block',
            [
              [2, 3]
            ],
            null,
            'both'),
      ], pounce: true);
      final result = engine.executeTurn(const GameAction('move', {
        'position': [2, 3],
        'direction': 'up'
      }));
      expect(result.accepted, isTrue);
      expect(gone(engine, 'g'), isTrue);
      expect(engine.state.variables['stolen'], 1);
      expect(result.events.map((e) => e.type),
          contains('multi_cell_object_captured'));
    });

    test('a hunter to the left also pounces', () {
      final engine = _engine([
        _obj(
            'g',
            'box',
            [
              [3, 3]
            ],
            'good',
            'fixed'),
        _obj(
            'r',
            'box',
            [
              [0, 3]
            ],
            'bad',
            'fixed'),
        _pusher([0, 0]),
      ], pounce: true);
      _move(engine, [0, 0], 'right');
      expect(_cells(engine, 'r'), [const Position(3, 3)]);
    });

    test('a different row is safe', () {
      final engine = _engine([
        _obj(
            'g',
            'box',
            [
              [1, 3]
            ],
            'good',
            'fixed'),
        _obj(
            'r',
            'box',
            [
              [4, 1]
            ],
            'bad',
            'fixed'),
        _ledge([
          [4, 2]
        ]),
        _pusher([0, 0]),
      ], pounce: true);
      _move(engine, [0, 0], 'right');
      expect(engine.state.variables['stolen'], 0);
    });

    test('the nearest prey is eaten first, then the next in line', () {
      final engine = _engine([
        _obj(
            'near',
            'box',
            [
              [2, 3]
            ],
            'good',
            'fixed'),
        _obj(
            'far',
            'box',
            [
              [0, 3]
            ],
            'good',
            'fixed'),
        _obj(
            'r',
            'box',
            [
              [4, 3]
            ],
            'bad',
            'fixed'),
        _pusher([0, 0]),
      ], pounce: true);
      _move(engine, [0, 0], 'right');
      expect(engine.state.variables['stolen'], 2);
      expect(_cells(engine, 'r'), [const Position(0, 3)]);
    });
  });

  group('step-by-step falling', () {
    TurnEngine dropPastHunter({required bool step, required bool wall}) {
      final engine = _engine([
        _obj(
            'g',
            'box',
            [
              [1, 0]
            ],
            'good',
            'fixed'),
        _obj(
            's',
            'block',
            [
              [1, 1]
            ],
            null,
            'both'),
        _obj(
            'r',
            'box',
            [
              [4, 2]
            ],
            'bad',
            'fixed'),
        _obj(
            'post',
            'block',
            [
              [4, 3]
            ],
            null,
            'both'),
        if (wall)
          _obj(
              'wall',
              'block',
              [
                [3, 2]
              ],
              null,
              'both'),
      ], pounce: true, step: step);
      expect(_move(engine, [1, 1], 'right'), isTrue);
      return engine;
    }

    test('full settle only looks at the landing row', () {
      final engine = dropPastHunter(step: false, wall: false);
      expect(_cells(engine, 'g'), [const Position(1, 3)]);
      expect(engine.state.variables['stolen'], 0);
    });

    test('step mode catches the cheese in transit', () {
      final engine = dropPastHunter(step: true, wall: false);
      expect(
          engine.state.board.multiCellObjects.any((o) => o.id == 'g'), isFalse);
      expect(engine.state.variables['stolen'], 1);
      expect(_cells(engine, 'r').first.y, 3); // ran to row 2, then fell
    });

    test('a block in the row lets the cheese fall safely', () {
      final engine = dropPastHunter(step: true, wall: true);
      expect(_cells(engine, 'g'), [const Position(1, 3)]);
      expect(engine.state.variables['stolen'], 0);
    });

    test('step mode still absorbs once at rest, one cell per pass', () {
      final engine = _engine([
        _obj(
            'g',
            'box',
            [
              [3, 0]
            ],
            'good',
            'fixed'),
        _obj(
            's',
            'block',
            [
              [3, 1]
            ],
            null,
            'both'),
      ], absorb: true, step: true);
      final result = engine.executeTurn(const GameAction('move', {
        'position': [3, 1],
        'direction': 'left'
      }));
      expect(result.accepted, isTrue);
      expect(
          engine.state.board.multiCellObjects.any((o) => o.id == 'g'), isFalse);
      expect(engine.state.variables['fed'], 1);
      expect(engine.state.board.getEntity('ground', const Position(3, 3))?.kind,
          'zone_fed');
      final moves = result.events
          .where((e) =>
              e.type == 'multi_cell_object_moved' && e.payload['id'] == 'g')
          .toList();
      expect(moves.length, 3);
    });
  });

  group('blocked ground', () {
    test('a block cannot enter the target tile', () {
      final engine = _engine([
        _obj(
            'blk',
            'block',
            [
              [2, 3]
            ],
            null,
            'both')
      ], blocked: true);
      expect(_move(engine, [2, 3], 'right'), isFalse);
      expect(_cells(engine, 'blk'), [const Position(2, 3)]);
    });

    test('by default blocks may still cover it', () {
      final engine = _engine([
        _obj(
            'blk',
            'block',
            [
              [2, 3]
            ],
            null,
            'both')
      ]);
      expect(_move(engine, [2, 3], 'right'), isTrue);
    });

    test('a pushed box may still be pushed onto the tile', () {
      final engine = _engine([
        _obj(
            'g',
            'box',
            [
              [2, 3]
            ],
            'good',
            'fixed'),
        _obj(
            'pusher',
            'block',
            [
              [1, 3]
            ],
            null,
            'both'),
      ], blocked: true);
      expect(_move(engine, [1, 3], 'right'), isTrue);
      expect(_cells(engine, 'g'), [const Position(3, 3)]);
      expect(engine.state.variables['onTarget'], 1);
      expect(_move(engine, [2, 3], 'right'), isFalse);
    });
  });
}
