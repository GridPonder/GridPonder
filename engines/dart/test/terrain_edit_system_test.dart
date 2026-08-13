// Parity mirror of engines/python/test_terrain_edit.py.
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _makeGame() {
  final data = {
    'id': 'com.gridponder.test_terrain_edit',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
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
    },
    'actions': [
      {
        'id': 'place_wall',
        'params': {
          'position': {'type': 'position'},
        },
      },
      {
        'id': 'other_action',
        'params': {
          'position': {'type': 'position'},
        },
      },
    ],
    'systems': [
      {
        'id': 'edit',
        'type': 'terrain_edit',
        'config': {
          'action': 'place_wall',
          'layer': 'ground',
          'kind': 'wall',
          'fromKind': 'empty',
          'budgetVariable': 'walls',
        },
      },
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_terrain_edit');
}

Map<String, dynamic> _makeLevel({int budget = 1}) => {
      'id': 'test_level',
      'board': {
        'size': [4, 1],
        'layers': {
          'ground': {'format': 'sparse', 'entries': <dynamic>[]},
        },
      },
      'state': {
        'variables': {'walls': budget},
      },
      'goals': <dynamic>[],
      'loseConditions': <dynamic>[],
    };

TurnEngine _engineFor(GameDefinition game, Map<String, dynamic> levelJson) {
  final level = LevelDefinition.fromJson(levelJson, game.layers);
  return TurnEngine(game, level);
}

String? _kindAt(TurnEngine engine, int x, int y) =>
    engine.state.board.getEntity('ground', Position(x, y))?.kind;

GameAction _placeAt(int x, int y) => GameAction('place_wall', {
      'position': [x, y]
    });

void main() {
  group('terrain_edit', () {
    test('places a wall and spends budget', () {
      final engine = _engineFor(_makeGame(), _makeLevel(budget: 1));
      final result = engine.executeTurn(_placeAt(2, 0));
      expect(_kindAt(engine, 2, 0), 'wall');
      expect(engine.state.variables['walls'], 0);
      expect(result.events.any((e) => e.type == 'cell_transformed'), isTrue);
    });

    test('refuses when the budget is exhausted', () {
      final engine = _engineFor(_makeGame(), _makeLevel(budget: 0));
      engine.executeTurn(_placeAt(2, 0));
      expect(_kindAt(engine, 2, 0), 'empty');
    });

    test('refuses when fromKind does not match', () {
      final engine = _engineFor(_makeGame(), _makeLevel(budget: 2));
      engine.executeTurn(_placeAt(2, 0));
      engine.executeTurn(_placeAt(2, 0));
      expect(engine.state.variables['walls'], 1);
    });

    test('ignores an out-of-bounds edit', () {
      final engine = _engineFor(_makeGame(), _makeLevel(budget: 1));
      engine.executeTurn(_placeAt(99, 0));
      expect(engine.state.variables['walls'], 1);
    });

    test('ignores other actions', () {
      final engine = _engineFor(_makeGame(), _makeLevel(budget: 1));
      engine.executeTurn(GameAction('other_action', {
        'position': [2, 0]
      }));
      expect(_kindAt(engine, 2, 0), 'empty');
      expect(engine.state.variables['walls'], 1);
    });

    test('refuses a non-numeric position', () {
      final engine = _engineFor(_makeGame(), _makeLevel(budget: 1));
      engine.executeTurn(GameAction('place_wall', {
        'position': ['a', 0]
      }));
      expect(_kindAt(engine, 2, 0), 'empty');
      expect(engine.state.variables['walls'], 1);
    });

    test('refuses a malformed position', () {
      final engine = _engineFor(_makeGame(), _makeLevel(budget: 1));
      // Missing position key.
      engine.executeTurn(GameAction('place_wall', {}));
      expect(engine.state.variables['walls'], 1);
      // One-element list.
      engine.executeTurn(GameAction('place_wall', {
        'position': [2]
      }));
      expect(engine.state.variables['walls'], 1);
    });

    test('refuses a non-finite position', () {
      final engine = _engineFor(_makeGame(), _makeLevel(budget: 1));
      engine.executeTurn(GameAction('place_wall', {
        'position': [double.infinity, 0]
      }));
      expect(_kindAt(engine, 2, 0), 'empty');
      expect(engine.state.variables['walls'], 1);
      engine.executeTurn(GameAction('place_wall', {
        'position': [double.nan, 0]
      }));
      expect(engine.state.variables['walls'], 1);
    });
  });
}
