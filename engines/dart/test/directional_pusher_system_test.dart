// Parity mirror of engines/python/test_directional_pusher.py — the
// `directional_pusher` system (docs/dsl/04_systems.md §2.27).
//
// Board used throughout (7x3), pusher `>` at (1, 1) facing right, so its only
// trigger cell is (2, 1).
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _makeGame() {
  final data = {
    'id': 'com.gridponder.test_directional_pusher',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
      {'id': 'objects', 'occupancy': 'zero_or_one'},
      {'id': 'actors', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'empty': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': '.',
      },
      'pusher': {
        'layer': 'objects',
        'tags': ['pusher', 'solid'],
        'symbol': '>',
      },
      'crate': {'layer': 'objects', 'tags': <String>[], 'symbol': 'c'},
      'hazard': {
        'layer': 'actors',
        'tags': ['npc', 'solid'],
        'symbol': 'h',
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
      {'id': 'navigation', 'type': 'avatar_navigation', 'config': {}},
      {
        'id': 'pushers',
        'type': 'directional_pusher',
        'config': {
          'condition': {
            'variable': {'name': 'load', 'op': 'eq', 'value': 0},
          },
          'crashLayers': ['actors'],
          'crashVariable': 'caught',
        },
      },
      {
        'id': 'hazards',
        'type': 'follower_npcs',
        'config': {
          'contactVariable': 'caught',
          'behaviors': {
            'sweep': {'type': 'patrol', 'lethalContact': true},
          },
        },
      },
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_directional_pusher');
}

Map<String, dynamic> _level(
  (int, int) avatar, {
  List<Map<String, dynamic>> extraObjects = const [],
  int load = 0,
  List<Map<String, dynamic>> actors = const [],
}) {
  return {
    'id': 'test_level',
    'board': {
      'size': [7, 3],
      'layers': {
        'objects': {
          'format': 'sparse',
          'entries': [
            {
              'position': [1, 1],
              'kind': 'pusher',
              'direction': 'right',
            },
            ...extraObjects,
          ],
        },
        'actors': {'format': 'sparse', 'entries': actors},
      },
    },
    'state': {
      'avatar': {
        'enabled': true,
        'position': [avatar.$1, avatar.$2],
      },
      'variables': {'load': load, 'caught': 0},
    },
    'goals': <dynamic>[],
    'loseConditions': <dynamic>[],
  };
}

(TurnEngine, TurnResult) _move(Map<String, dynamic> levelJson, String dir) {
  final game = _makeGame();
  final level = LevelDefinition.fromJson(levelJson, game.layers);
  final engine = TurnEngine(game, level);
  final result = engine.executeTurn(GameAction('move', {'direction': dir}));
  return (engine, result);
}

List<GameEvent> _pushed(TurnResult result) =>
    result.events.where((e) => e.type == 'avatar_pushed').toList();

void main() {
  test('front cell slides to the board edge', () {
    final (engine, result) = _move(_level((2, 0)), 'down');
    expect(result.accepted, isTrue);
    expect(engine.state.avatar.position, const Position(6, 1));
    expect(engine.state.avatar.facing, Direction.right);
    final pushed = _pushed(result);
    expect(pushed, hasLength(1));
    expect(pushed.single.payload['fromPosition'], const Position(2, 1));
    expect(pushed.single.payload['pusherPosition'], const Position(1, 1));
    expect(pushed.single.payload['distance'], 4);
    final entered = result.events
        .where((e) => e.type == 'avatar_entered')
        .map((e) => e.position)
        .toList();
    expect(entered, const [
      Position(2, 1),
      Position(3, 1),
      Position(4, 1),
      Position(5, 1),
      Position(6, 1),
    ]);
  });

  test('push costs exactly one action', () {
    final (engine, _) = _move(_level((2, 0)), 'down');
    expect(engine.state.actionCount, 1);
  });

  test('cell behind the pusher does nothing', () {
    final (engine, result) = _move(_level((0, 0)), 'down');
    expect(engine.state.avatar.position, const Position(0, 1));
    expect(_pushed(result), isEmpty);
  });

  test('same row but not adjacent does nothing', () {
    final (engine, result) = _move(_level((4, 0)), 'down');
    expect(engine.state.avatar.position, const Position(4, 1));
    expect(_pushed(result), isEmpty);
  });

  test('side of the pusher does nothing', () {
    final (engine, result) = _move(_level((0, 0)), 'right');
    expect(engine.state.avatar.position, const Position(1, 0));
    expect(_pushed(result), isEmpty);
  });

  test('pusher tile itself is solid', () {
    final (engine, _) = _move(_level((1, 0)), 'down');
    expect(engine.state.avatar.position, const Position(1, 0));
  });

  test('condition false disables the push', () {
    final (engine, result) = _move(_level((2, 0), load: 1), 'down');
    expect(engine.state.avatar.position, const Position(2, 1));
    expect(_pushed(result), isEmpty);
  });

  test('stops one cell short of a stop-layer entity', () {
    final (engine, _) = _move(
        _level((2, 0), extraObjects: [
          {
            'position': [5, 1],
            'kind': 'crate',
          },
        ]),
        'down');
    expect(engine.state.avatar.position, const Position(4, 1));
  });

  test('blocked immediately emits no push', () {
    final (engine, result) = _move(
        _level((2, 0), extraObjects: [
          {
            'position': [3, 1],
            'kind': 'crate',
          },
        ]),
        'down');
    expect(engine.state.avatar.position, const Position(2, 1));
    expect(_pushed(result), isEmpty);
  });

  test('slide does not chain into another pusher', () {
    final (engine, result) = _move(
        _level((2, 0), extraObjects: [
          {
            'position': [6, 0],
            'kind': 'pusher',
            'direction': 'down',
          },
        ]),
        'down');
    expect(engine.state.avatar.position, const Position(6, 1));
    expect(_pushed(result), hasLength(1));
  });

  test('standing still on the trigger cell does nothing', () {
    final (engine, result) = _move(_level((2, 1)), 'left');
    expect(engine.state.avatar.position, const Position(2, 1));
    expect(_pushed(result), isEmpty);
  });

  test('sliding into a crash-layer entity is a crash', () {
    final (engine, result) = _move(
        _level((2, 0), actors: [
          {
            'position': [4, 1],
            'kind': 'hazard',
          },
        ]),
        'down');
    expect(engine.state.avatar.position, const Position(4, 1));
    expect(engine.state.variables['caught'], 1);
    final caught =
        result.events.where((e) => e.type == 'avatar_caught').toList();
    expect(caught, hasLength(1));
    expect(caught.single.position, const Position(4, 1));
  });

  test('hazard leaving the landing cell is not a crash', () {
    final (engine, result) = _move(
        _level((2, 0), actors: [
          {
            'position': [6, 1],
            'kind': 'hazard',
            'behavior': 'sweep',
            'facing': 'up',
          },
        ]),
        'down');
    expect(engine.state.avatar.position, const Position(6, 1));
    expect(engine.state.variables['caught'], 0);
    expect(result.events.where((e) => e.type == 'avatar_caught'), isEmpty);
  });

  test('hazard arriving on the landing cell is a crash', () {
    final (engine, result) = _move(
        _level((2, 0), actors: [
          {
            'position': [6, 0],
            'kind': 'hazard',
            'behavior': 'sweep',
            'facing': 'down',
          },
        ]),
        'down');
    expect(engine.state.avatar.position, const Position(6, 1));
    expect(engine.state.variables['caught'], 1);
    expect(result.events.where((e) => e.type == 'avatar_caught'), hasLength(1));
  });

  test('hazard arriving mid-slide stops the slide in a crash', () {
    final (engine, _) = _move(
        _level((2, 0), actors: [
          {
            'position': [4, 0],
            'kind': 'hazard',
            'behavior': 'sweep',
            'facing': 'down',
          },
        ]),
        'down');
    expect(engine.state.avatar.position, const Position(4, 1));
    expect(engine.state.variables['caught'], 1);
  });
}
