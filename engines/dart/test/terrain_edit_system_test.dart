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

/// A second layer with `zero_or_one` occupancy and no `default`, so an
/// untouched cell's `getEntity` returns null rather than an "empty" entity —
/// unlike `ground` in `_makeGame`, which is `exactly_one`.
GameDefinition _makeZeroOrOneGame() {
  final data = {
    'id': 'com.gridponder.test_terrain_edit_zero_or_one',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
      {'id': 'markers', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'empty': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': '.',
      },
      'marker': {
        'layer': 'markers',
        'tags': <String>[],
        'symbol': 'M',
      },
    },
    'actions': [
      {
        'id': 'place_marker',
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
          'action': 'place_marker',
          'layer': 'markers',
          'kind': 'marker',
        },
      },
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_terrain_edit_zero_or_one');
}

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

    test(
        'fromKind is the empty string, not null, for a previously-empty '
        'zero_or_one cell', () {
      // On a zero_or_one layer, getEntity returns null for an untouched
      // cell — not an "empty" entity. The emitted cell_transformed event
      // must still carry '' (not null) as fromKind, matching the Python
      // engine's payload.
      final engine = _engineFor(_makeZeroOrOneGame(), _makeLevel(budget: 1));
      final result = engine.executeTurn(GameAction('place_marker', {
        'position': [2, 0]
      }));
      final transformed =
          result.events.where((e) => e.type == 'cell_transformed').toList();
      expect(transformed.length, 1);
      expect(transformed[0]['fromKind'], equals(''));
      expect(transformed[0]['toKind'], equals('marker'));
    });
  });
}
