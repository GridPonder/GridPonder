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
      'ramp_right': {
        'layer': 'ground',
        'tags': ['solid', 'slope_right'],
        'symbol': '/',
      },
      'ramp_left': {
        'layer': 'ground',
        'tags': ['solid', 'slope_left'],
        'symbol': r'\',
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

// Two orphans in one column. Cutting (1,1) orphans the hull at (1,2) AND the
// pod at (1,4), which has no path to a root of its own. The pod is blocked by
// the deck immediately; the hull must come to rest on top of it, not through it.
final _stackedOrphans = <Map<String, dynamic>>[
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
    'position': [1, 4],
    'kind': 'pod'
  },
  ..._deck,
];

const _deflect = <String, dynamic>{
  'deflect': {'slope_left': 'left', 'slope_right': 'right'},
};

final _oneRamp = <Map<String, dynamic>>[
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
  {
    'position': [1, 4],
    'kind': 'ramp_right'
  },
  ..._deck,
];

final _cloggedRamp = <Map<String, dynamic>>[
  ..._oneRamp,
  {
    'position': [2, 3],
    'kind': 'wreck'
  },
];

final _straddle = <Map<String, dynamic>>[
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
  {
    'position': [1, 4],
    'kind': 'ramp_right'
  },
  {
    'position': [2, 4],
    'kind': 'wreck'
  },
  ..._deck,
];

final _opposingRamps = <Map<String, dynamic>>[
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
  {
    'position': [1, 4],
    'kind': 'ramp_right'
  },
  {
    'position': [2, 4],
    'kind': 'ramp_left'
  },
  ..._deck,
];

final _facingRamps = <Map<String, dynamic>>[
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
  {
    'position': [1, 4],
    'kind': 'ramp_right'
  },
  {
    'position': [2, 4],
    'kind': 'ramp_left'
  },
  ..._deck,
];

final _edgeRamp = <Map<String, dynamic>>[
  {
    'position': [4, 0],
    'kind': 'anchor'
  },
  {
    'position': [4, 1],
    'kind': 'hull'
  },
  {
    'position': [4, 2],
    'kind': 'pod'
  },
  {
    'position': [4, 4],
    'kind': 'ramp_right'
  },
  ..._deck,
];

void main() {
  test('a blocked component slides off a ramp and keeps falling', () {
    final game = _game(collapseConfig: _deflect);
    final engine =
        TurnEngine(game, _level(game, entries: _oneRamp, avatar: [1, 0]));

    engine.executeTurn(GameAction('cut', {
      'position': [1, 1]
    }));

    final board = engine.state.board;
    expect(
        board.getEntity('ground', const Position(2, 4))?.kind, 'pod_settled');
    expect(board.getEntity('ground', const Position(1, 3))?.kind, 'void');
  });

  test('a ramp with no runoff clogs and the component rests on it', () {
    final game = _game(collapseConfig: _deflect);
    final engine =
        TurnEngine(game, _level(game, entries: _cloggedRamp, avatar: [1, 0]));

    engine.executeTurn(GameAction('cut', {
      'position': [1, 1]
    }));

    expect(engine.state.board.getEntity('ground', const Position(1, 3))?.kind,
        'pod_settled');
  });

  test('a component blocked by ramp and flat ground rests', () {
    final game = _game(collapseConfig: _deflect);
    final engine =
        TurnEngine(game, _level(game, entries: _straddle, avatar: [1, 0]));

    engine.executeTurn(GameAction('cut', {
      'position': [1, 1]
    }));

    final board = engine.state.board;
    expect(board.getEntity('ground', const Position(1, 3))?.kind, 'wreck');
    expect(board.getEntity('ground', const Position(2, 3))?.kind, 'wreck');
  });

  test('ramps pulling opposite ways cancel', () {
    final game = _game(collapseConfig: _deflect);
    final engine =
        TurnEngine(game, _level(game, entries: _opposingRamps, avatar: [1, 0]));

    engine.executeTurn(GameAction('cut', {
      'position': [1, 1]
    }));

    final board = engine.state.board;
    expect(board.getEntity('ground', const Position(1, 3))?.kind, 'wreck');
    expect(board.getEntity('ground', const Position(2, 3))?.kind, 'wreck');
  });

  test('facing ramps do not oscillate', () {
    final game = _game(collapseConfig: _deflect);
    final engine =
        TurnEngine(game, _level(game, entries: _facingRamps, avatar: [1, 0]));

    engine.executeTurn(GameAction('cut', {
      'position': [1, 1]
    }));

    expect(engine.state.board.getEntity('ground', const Position(2, 3))?.kind,
        'pod_settled');
  });

  test('a sideways step never leaves the board', () {
    final game = _game(collapseConfig: _deflect);
    final engine =
        TurnEngine(game, _level(game, entries: _edgeRamp, avatar: [4, 0]));

    engine.executeTurn(GameAction('cut', {
      'position': [4, 1]
    }));

    expect(engine.state.board.getEntity('ground', const Position(4, 3))?.kind,
        'pod_settled');
  });

  test('deflect defaults to off', () {
    final game = _game();
    final engine =
        TurnEngine(game, _level(game, entries: _oneRamp, avatar: [1, 0]));

    engine.executeTurn(GameAction('cut', {
      'position': [1, 1]
    }));

    expect(engine.state.board.getEntity('ground', const Position(1, 3))?.kind,
        'pod_settled');
  });

  test('a falling component rests on one that landed first', () {
    final game = _game();
    final engine = TurnEngine(
        game, _level(game, entries: _stackedOrphans, avatar: [1, 0]));

    engine.executeTurn(GameAction('cut', {
      'position': [1, 1]
    }));

    final board = engine.state.board;
    // The pod stops on the deck; the hull stops on the pod. Neither is lost.
    expect(
        board.getEntity('ground', const Position(1, 4))?.kind, 'pod_settled');
    expect(board.getEntity('ground', const Position(1, 3))?.kind, 'wreck');
  });

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
