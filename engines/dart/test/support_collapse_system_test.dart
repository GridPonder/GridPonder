import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _game({Map<String, dynamic> collapseConfig = const {}}) {
  return GameDefinition.fromJson({
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'void'},
    ],
    'entityKinds': {
      'void': {'layer': 'ground', 'tags': <String>[], 'symbol': ' '},
      'anchor': {
        'layer': 'ground',
        'tags': ['solid', 'walkable', 'support_root'],
        'symbol': 'A',
      },
      'hull': {
        'layer': 'ground',
        'tags': ['solid', 'walkable', 'supported', 'severable'],
        'symbol': 'H',
      },
      'pod': {
        'layer': 'ground',
        'tags': ['solid', 'walkable', 'supported', 'severable', 'cargo'],
        'symbol': 'P',
      },
      'wreck': {
        'layer': 'ground',
        'tags': ['solid'],
        'symbol': 'w',
      },
      'pod_settled': {
        'layer': 'ground',
        'tags': ['solid', 'cargo'],
        'symbol': 'p',
      },
      'deck': {
        'layer': 'ground',
        'tags': ['solid'],
        'symbol': '=',
      },
    },
    'actions': [
      {
        'id': 'cut',
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
        'id': 'collapse',
        'type': 'support_collapse',
        'config': {
          'layer': 'ground',
          'severAction': 'cut',
          'severableTags': ['severable'],
          'rootTags': ['support_root'],
          'memberTags': ['supported'],
          'restLayers': ['ground'],
          'restTags': ['solid'],
          'settleTransform': {'hull': 'wreck', 'pod': 'pod_settled'},
          'carryAvatar': true,
          'avatarFellVariable': 'wrecked',
          ...collapseConfig,
        },
      },
    ],
    'defaults': {'maxCascadeDepth': 3},
  }, id: 'support_collapse_test');
}

LevelDefinition _level(
  GameDefinition game, {
  required List<Map<String, dynamic>> entries,
  required List<int> avatar,
}) {
  return LevelDefinition.fromJson({
    'id': 'collapse_test',
    'board': {
      'size': [5, 6],
      'layers': {
        'ground': {'format': 'sparse', 'entries': entries},
      },
    },
    'state': {
      'variables': {'wrecked': 0},
      'avatar': {'enabled': true, 'position': avatar},
    },
    'goals': <Map<String, dynamic>>[],
    'rules': <Map<String, dynamic>>[],
    'solution': {'goldPath': <Map<String, dynamic>>[]},
  }, game.layers);
}

const _deck = <Map<String, dynamic>>[
  {
    'position': [0, 5],
    'kind': 'deck'
  },
  {
    'position': [1, 5],
    'kind': 'deck'
  },
  {
    'position': [2, 5],
    'kind': 'deck'
  },
  {
    'position': [3, 5],
    'kind': 'deck'
  },
  {
    'position': [4, 5],
    'kind': 'deck'
  },
];

// 5 wide x 6 tall (x right, y down):
//   y=0:  A A . . .        anchor bar
//   y=1:  . H . . .        hull hanging under the right anchor cell
//   y=2:  . P . . .        pod under that hull
//   y=5:  = = = = =        deck
final _hanging = <Map<String, dynamic>>[
  {
    'position': [0, 0],
    'kind': 'anchor'
  },
  {
    'position': [1, 0],
    'kind': 'anchor'
  },
  {
    'position': [1, 1],
    'kind': 'hull'
  },
  {
    'position': [1, 2],
    'kind': 'pod'
  },
  ..._deck,
];

// An L: hull(1,1) hull(1,2) hull(2,2) hanging from anchor(1,0).
final _lShape = <Map<String, dynamic>>[
  {
    'position': [1, 0],
    'kind': 'anchor'
  },
  {
    'position': [1, 1],
    'kind': 'hull'
  },
  {
    'position': [1, 2],
    'kind': 'hull'
  },
  {
    'position': [2, 2],
    'kind': 'hull'
  },
  ..._deck,
];

final _hangingWithDebris = <Map<String, dynamic>>[
  ..._hanging,
  {
    'position': [1, 4],
    'kind': 'wreck'
  },
];

// Two anchors both holding the same hull run.
final _twoAnchors = <Map<String, dynamic>>[
  {
    'position': [0, 0],
    'kind': 'anchor'
  },
  {
    'position': [2, 0],
    'kind': 'anchor'
  },
  {
    'position': [0, 1],
    'kind': 'hull'
  },
  {
    'position': [1, 1],
    'kind': 'hull'
  },
  {
    'position': [2, 1],
    'kind': 'hull'
  },
  ..._deck,
];

// No deck under column 3 — an orphan there falls out of the world.
final _noDeck = <Map<String, dynamic>>[
  {
    'position': [3, 0],
    'kind': 'anchor'
  },
  {
    'position': [3, 1],
    'kind': 'hull'
  },
  {
    'position': [3, 2],
    'kind': 'pod'
  },
];

void main() {
  test('severing the keystone drops the limb rigidly', () {
    final game = _game();
    final engine =
        TurnEngine(game, _level(game, entries: _hanging, avatar: [1, 0]));

    final result = engine.executeTurn(GameAction('cut', {'direction': 'down'}));

    final board = engine.state.board;
    expect(board.getEntity('ground', const Position(1, 1))?.kind, 'void');
    expect(board.getEntity('ground', const Position(1, 2))?.kind, 'void');
    expect(
        board.getEntity('ground', const Position(1, 4))?.kind, 'pod_settled');
    final types = result.events.map((e) => e.type).toList();
    expect(types, contains('cell_cleared'));
    expect(types, contains('object_settled'));
  });

  test('rigid component keeps its shape', () {
    final game = _game();
    final engine =
        TurnEngine(game, _level(game, entries: _lShape, avatar: [1, 0]));

    engine.executeTurn(GameAction('cut', {'direction': 'down'}));

    final board = engine.state.board;
    expect(board.getEntity('ground', const Position(1, 4))?.kind, 'wreck');
    expect(board.getEntity('ground', const Position(2, 4))?.kind, 'wreck');
    expect(board.getEntity('ground', const Position(1, 2))?.kind, 'void');
  });

  test('component rests on previously landed debris', () {
    final game = _game();
    final engine = TurnEngine(
        game, _level(game, entries: _hangingWithDebris, avatar: [1, 0]));

    engine.executeTurn(GameAction('cut', {'direction': 'down'}));

    expect(engine.state.board.getEntity('ground', const Position(1, 3))?.kind,
        'pod_settled');
  });

  test('cells still connected to a root do not fall', () {
    final game = _game();
    final engine =
        TurnEngine(game, _level(game, entries: _twoAnchors, avatar: [0, 0]));

    engine.executeTurn(GameAction('cut', {'direction': 'down'}));

    final board = engine.state.board;
    expect(board.getEntity('ground', const Position(0, 1))?.kind, 'void');
    expect(board.getEntity('ground', const Position(1, 1))?.kind, 'hull');
    expect(board.getEntity('ground', const Position(2, 1))?.kind, 'hull');
  });

  test('avatar rides its own component down and sets the variable', () {
    final game = _game();
    final engine =
        TurnEngine(game, _level(game, entries: _hanging, avatar: [1, 2]));

    engine.executeTurn(GameAction('cut', {'direction': 'up'}));

    expect(engine.state.variables['wrecked'], 1);
    expect(engine.state.avatar.position, const Position(1, 4));
  });

  test('component falling off the board is destroyed', () {
    final game = _game();
    final engine =
        TurnEngine(game, _level(game, entries: _noDeck, avatar: [3, 0]));

    engine.executeTurn(GameAction('cut', {'direction': 'down'}));

    final board = engine.state.board;
    for (var y = 0; y < 6; y++) {
      expect(board.getEntity('ground', Position(3, y))?.kind,
          y == 0 ? 'anchor' : 'void');
    }
  });

  test('cutting a non-severable cell is vetoed', () {
    final game = _game();
    final engine =
        TurnEngine(game, _level(game, entries: _hanging, avatar: [0, 0]));

    final result =
        engine.executeTurn(GameAction('cut', {'direction': 'right'}));

    // A vetoed action is rejected outright — the turn does not count as a move.
    expect(result.accepted, isFalse);
    expect(engine.state.board.getEntity('ground', const Position(1, 0))?.kind,
        'anchor');
  });

  test('sever target can be named by position', () {
    final game = _game();
    final engine =
        TurnEngine(game, _level(game, entries: _hanging, avatar: [1, 0]));

    engine.executeTurn(GameAction('cut', {
      'position': [1, 1]
    }));

    final board = engine.state.board;
    expect(board.getEntity('ground', const Position(1, 1))?.kind, 'void');
    expect(
        board.getEntity('ground', const Position(1, 4))?.kind, 'pod_settled');
  });

  test('severing a non-adjacent position is vetoed', () {
    final game = _game();
    final engine =
        TurnEngine(game, _level(game, entries: _hanging, avatar: [1, 0]));

    final result = engine.executeTurn(GameAction('cut', {
      'position': [1, 2]
    }));

    expect(result.accepted, isFalse);
    expect(engine.state.board.getEntity('ground', const Position(1, 2))?.kind,
        'pod');
  });

  test('cutting empty air is vetoed', () {
    final game = _game();
    final engine =
        TurnEngine(game, _level(game, entries: _hanging, avatar: [0, 0]));

    final result = engine.executeTurn(GameAction('cut', {'direction': 'down'}));

    expect(result.accepted, isFalse);
    expect(engine.state.board.getEntity('ground', const Position(1, 1))?.kind,
        'hull');
  });
}
