// Parity mirror of engines/python/test_transform_from_kind.py.
//
// Conditions cannot inspect a `$event` position, only effects can read one, so
// without this filter a rule keyed on an event transforms its cell blindly.
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _game(dynamic fromKind) {
  final effect = <String, dynamic>{
    'position': '\$event.position',
    'layer': 'ground',
    'toKind': 'void',
  };
  if (fromKind != null) effect['fromKind'] = fromKind;

  return GameDefinition.fromJson({
    'id': 'com.gridponder.test_transform_from_kind',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
    ],
    'entityKinds': {
      'empty': {'layer': 'ground', 'tags': ['walkable'], 'symbol': '.'},
      'cracked': {'layer': 'ground', 'tags': ['walkable'], 'symbol': 'x'},
      'rotten': {'layer': 'ground', 'tags': ['walkable'], 'symbol': 'r'},
      'void': {'layer': 'ground', 'tags': ['solid'], 'symbol': '#'},
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
      {'id': 'nav', 'type': 'avatar_navigation', 'config': <String, dynamic>{}},
    ],
    'rules': [
      {
        'id': 'give_way',
        'on': 'avatar_exited',
        'then': [
          {'transform': effect},
        ],
      },
    ],
  }, id: 'test_transform_from_kind');
}

Map<String, dynamic> _levelJson() => {
      'id': 'test_level',
      'board': {
        'size': [4, 1],
        'layers': {
          'ground': {
            'format': 'sparse',
            'entries': [
              {'position': [0, 0], 'kind': 'cracked'},
              {'position': [1, 0], 'kind': 'rotten'},
            ],
          },
        },
      },
      'state': {
        'avatar': {'enabled': true, 'position': [0, 0]},
      },
      'goals': <dynamic>[],
      'loseConditions': <dynamic>[],
    };

TurnEngine _engineFor(GameDefinition game) =>
    TurnEngine(game, LevelDefinition.fromJson(_levelJson(), game.layers));

List<String> _walkRight(TurnEngine engine, int steps) {
  for (var i = 0; i < steps; i++) {
    engine.executeTurn(GameAction('move', {'direction': 'right'}));
  }
  return [
    for (var x = 0; x < 4; x++)
      engine.state.board.getEntity('ground', Position(x, 0))!.kind,
  ];
}

void main() {
  test('an unfiltered transform takes every cell', () {
    // The behaviour before the filter existed, kept as the baseline.
    expect(_walkRight(_engineFor(_game(null)), 3),
        ['void', 'void', 'void', 'empty']);
  });

  test('fromKind spares the other kinds', () {
    expect(_walkRight(_engineFor(_game('cracked')), 3),
        ['void', 'rotten', 'empty', 'empty']);
  });

  test('fromKind accepts a list', () {
    expect(_walkRight(_engineFor(_game(['cracked', 'rotten'])), 3),
        ['void', 'void', 'empty', 'empty']);
  });

  test('a filtered-out transform emits nothing', () {
    // No match must mean no effect *and* no event, or cascades would fire.
    final engine = _engineFor(_game('cracked'));
    engine.executeTurn(GameAction('move', {'direction': 'right'}));
    final result = engine.executeTurn(GameAction('move', {'direction': 'right'}));
    expect(result.events.where((e) => e.type == 'cell_transformed'), isEmpty);
  });
}
