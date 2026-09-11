// Parity mirror of engines/python/test_balance_regions.py — behavioural cases
// for the `balance_regions` system.
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

const _group = <String, dynamic>{
  'pans': [
    {
      'name': 'west',
      'groundTags': ['pan_west'],
    },
    {
      'name': 'east',
      'groundTags': ['pan_east'],
    },
  ],
  'weights': {'carriage': 1},
  'avatarWeight': 1,
  'stateVariable': 'attitude',
  'leaves': [
    {
      'marker': 'hinge_west',
      'solidWhen': ['west'],
      'solidKind': 'leaf_plate',
    },
    {
      'marker': 'hinge_level',
      'solidWhen': ['level'],
      'solidKind': 'leaf_plate',
    },
  ],
  'fallVariable': 'fell',
};

GameDefinition _makeGame({Map<String, dynamic>? group}) {
  final data = {
    'id': 'com.gridponder.test_balance_regions',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'void'},
      {'id': 'objects', 'occupancy': 'zero_or_one'},
      {'id': 'actors', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'void': {'layer': 'ground', 'tags': <String>[], 'symbol': ' '},
      'deck': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': '.',
      },
      'deck_west': {
        'layer': 'ground',
        'tags': ['walkable', 'pan_west'],
        'symbol': 'w',
      },
      'deck_east': {
        'layer': 'ground',
        'tags': ['walkable', 'pan_east'],
        'symbol': 'e',
      },
      'leaf_plate': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': '=',
      },
      'hinge_west': {'layer': 'objects', 'tags': <String>[], 'symbol': '1'},
      'hinge_level': {'layer': 'objects', 'tags': <String>[], 'symbol': '2'},
      'carriage': {
        'layer': 'actors',
        'tags': ['npc', 'solid'],
        'symbol': 'C',
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
      {'id': 'wait', 'params': <String, dynamic>{}},
    ],
    'systems': [
      {
        'id': 'walk',
        'type': 'avatar_navigation',
        'config': {
          'solidHandling': 'block',
          'groundLayer': 'ground',
          'validGroundTags': ['walkable'],
          'solidLayers': ['objects', 'actors'],
        },
      },
      {
        'id': 'balance',
        'type': 'balance_regions',
        'config': {
          'groups': {'hall': group ?? _group},
        },
      },
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_balance_regions');
}

Map<String, dynamic> _makeLevel(
  List<List<String>> ground,
  List<int> avatar, {
  List<List<dynamic>> objects = const [],
  List<List<dynamic>> actors = const [],
  List<Map<String, dynamic>> lose = const [],
}) =>
    {
      'id': 'test_level',
      'board': {
        'size': [ground[0].length, ground.length],
        'layers': {
          'ground': ground,
          'objects': {
            'format': 'sparse',
            'entries': [
              for (final o in objects)
                {
                  'position': [o[0], o[1]],
                  'kind': o[2],
                }
            ],
          },
          'actors': {
            'format': 'sparse',
            'entries': [
              for (final a in actors)
                {
                  'position': [a[0], a[1]],
                  'kind': a[2],
                }
            ],
          },
        },
      },
      'state': {
        'avatar': {'enabled': true, 'position': avatar, 'facing': 'right'},
        'variables': {'fell': 0},
      },
      'goals': <dynamic>[],
      'loseConditions': lose,
    };

TurnEngine _engineFor(GameDefinition game, Map<String, dynamic> levelJson) =>
    TurnEngine(game, LevelDefinition.fromJson(levelJson, game.layers));

GameAction _move(String dir) => GameAction('move', {'direction': dir});

const _w = 'deck_west';
const _e = 'deck_east';
const _n = 'deck';

void main() {
  group('balance_regions', () {
    test('the avatar alone tips its own pan', () {
      final engine = _engineFor(
          _makeGame(),
          _makeLevel([
            [_w, _w, _n, _e, _e]
          ], [
            0,
            0
          ]));
      expect(engine.state.variables['attitude'], -1);
    });

    test('opposite pans balance', () {
      final engine = _engineFor(
          _makeGame(),
          _makeLevel([
            [_w, _w, _n, _e, _e]
          ], [
            0,
            0
          ], actors: [
            [4, 0, 'carriage']
          ]));
      expect(engine.state.variables['attitude'], 0);
    });

    test('neutral floor weighs nothing', () {
      final engine = _engineFor(
          _makeGame(),
          _makeLevel([
            [_w, _w, _n, _e, _e]
          ], [
            2,
            0
          ]));
      expect(engine.state.variables['attitude'], 0);
    });

    test('the attitude follows the avatar across the pivot', () {
      final engine = _engineFor(
          _makeGame(),
          _makeLevel([
            [_w, _w, _n, _e, _e]
          ], [
            1,
            0
          ]));
      expect(engine.state.variables['attitude'], -1);
      engine.executeTurn(_move('right'));
      expect(engine.state.variables['attitude'], 0);
      engine.executeTurn(_move('right'));
      expect(engine.state.variables['attitude'], 1);
    });

    test('a leaf is solid only in its attitude', () {
      final engine = _engineFor(
          _makeGame(),
          _makeLevel([
            [_w, _n, _e, 'void']
          ], [
            0,
            0
          ], objects: [
            [3, 0, 'hinge_west']
          ]));
      expect(engine.state.board.getEntity('ground', const Position(3, 0))?.kind,
          'leaf_plate');
      engine.executeTurn(_move('right'));
      expect(engine.state.board.getEntity('ground', const Position(3, 0))?.kind,
          'void');
    });

    test('a leaf swap emits cell_transformed', () {
      final engine = _engineFor(
          _makeGame(),
          _makeLevel([
            [_w, _n, _e, 'void']
          ], [
            0,
            0
          ], objects: [
            [3, 0, 'hinge_west']
          ]));
      final result = engine.executeTurn(_move('right'));
      final swaps =
          result.events.where((e) => e.type == 'cell_transformed').toList();
      expect(swaps.length, 1);
      expect(swaps.first['fromKind'], 'leaf_plate');
      expect(swaps.first['toKind'], 'void');
    });

    test('load settle corrects a board authored in the wrong state', () {
      final engine = _engineFor(
          _makeGame(),
          _makeLevel([
            [_w, _n, _e, 'leaf_plate']
          ], [
            1,
            0
          ], objects: [
            [3, 0, 'hinge_west']
          ]));
      expect(engine.state.board.getEntity('ground', const Position(3, 0))?.kind,
          'void');
    });

    test('the avatar cannot walk onto an open leaf', () {
      final engine = _engineFor(
          _makeGame(),
          _makeLevel([
            [_w, _n, _e, 'void']
          ], [
            2,
            0
          ], objects: [
            [3, 0, 'hinge_west']
          ]));
      final before = engine.state.avatar.position;
      engine.executeTurn(_move('right'));
      expect(engine.state.avatar.position, before);
    });

    test('a machine on a closing leaf is destroyed', () {
      final engine = _engineFor(
          _makeGame(),
          _makeLevel([
            [_w, _n, _e, 'leaf_plate']
          ], [
            0,
            0
          ], objects: [
            [3, 0, 'hinge_west']
          ], actors: [
            [3, 0, 'carriage']
          ]));
      expect(engine.state.board.getEntity('actors', const Position(3, 0)),
          isNotNull);
      final result = engine.executeTurn(_move('right'));
      expect(
          engine.state.board.getEntity('actors', const Position(3, 0)), isNull);
      final falls =
          result.events.where((e) => e.type == 'entity_fell').toList();
      expect(falls.length, 1);
      expect(falls.first['kind'], 'carriage');
    });

    test('the avatar on a closing leaf increments fell and loses', () {
      final engine = _engineFor(
          _makeGame(),
          _makeLevel([
            [_w, _n, _e, 'leaf_plate']
          ], [
            3,
            0
          ], objects: [
            [3, 0, 'hinge_level']
          ], actors: [
            [0, 0, 'carriage']
          ], lose: [
            {
              'type': 'variable_threshold',
              'config': {'variable': 'fell', 'target': 1, 'comparison': 'gte'},
            }
          ]));
      expect(engine.state.variables['fell'], 1);
      final result = engine.executeTurn(GameAction('wait', const {}));
      expect(result.isLost, isTrue);
    });

    test('inert without groups', () {
      final engine = _engineFor(
          _makeGame(group: const <String, dynamic>{}),
          _makeLevel([
            [_w, _w, _n, _e, _e]
          ], [
            0,
            0
          ]));
      expect(engine.state.variables.containsKey('attitude'), isFalse);
    });
  });
}
