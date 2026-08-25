// Parity mirror of engines/python/test_push_blocking_layers.py.
//
// Only the objects and ground layers were ever consulted, so a pack that keeps
// its NPCs on `actors` had crates pushed straight through them. Pairs with
// `blockingTags` the same way `sliding_blocks` and `line_of_sight` do.
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _game(Map<String, dynamic> config) =>
    GameDefinition.fromJson({
      'id': 'com.gridponder.test_push_blocking_layers',
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
        {'id': 'objects', 'occupancy': 'zero_or_one'},
        {'id': 'actors', 'occupancy': 'zero_or_one'},
      ],
      'entityKinds': {
        'floor': {'layer': 'ground', 'tags': ['walkable'], 'symbol': '.'},
        // `solid` too, or navigation walks onto it instead of delegating.
        'crate': {
          'layer': 'objects',
          'tags': ['pushable', 'solid'],
          'symbol': 'c',
        },
        'guard': {'layer': 'actors', 'tags': ['npc', 'solid'], 'symbol': 'G'},
        'ghost': {'layer': 'actors', 'tags': ['npc'], 'symbol': 'g'},
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
        {
          'id': 'nav',
          'type': 'avatar_navigation',
          'config': {'solidHandling': 'delegate'},
        },
        {'id': 'push', 'type': 'push_objects', 'config': config},
      ],
      'rules': <dynamic>[],
    }, id: 'test_push_blocking_layers');

/// A row of five: avatar, crate, then whatever is standing in the way.
Map<String, dynamic> _levelJson({
  String? actorKind,
  int actorX = 2,
  bool secondCrate = false,
}) =>
    {
      'id': 'test_level',
      'board': {
        'size': [5, 1],
        'layers': {
          'objects': {
            'format': 'sparse',
            'entries': [
              {'position': [1, 0], 'kind': 'crate'},
              if (secondCrate) {'position': [2, 0], 'kind': 'crate'},
            ],
          },
          'actors': {
            'format': 'sparse',
            'entries': [
              if (actorKind != null) {'position': [actorX, 0], 'kind': actorKind},
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

/// X of the (first) crate after one push, or null if it left the board.
int? _pushRight(GameDefinition game, Map<String, dynamic> level) {
  final engine = TurnEngine(game, LevelDefinition.fromJson(level, game.layers));
  engine.executeTurn(GameAction('move', {'direction': 'right'}));
  for (var x = 0; x < 5; x++) {
    final entity = engine.state.board.getEntity('objects', Position(x, 0));
    if (entity?.kind == 'crate') return x;
  }
  return null;
}

void main() {
  test('without the field a crate goes through an actor', () {
    // The behaviour before the field existed, kept as the baseline.
    expect(
        _pushRight(_game(<String, dynamic>{}), _levelJson(actorKind: 'guard')),
        2);
  });

  test('a solid actor blocks the push', () {
    final game = _game({'blockingLayers': ['actors']});
    expect(_pushRight(game, _levelJson(actorKind: 'guard')), 1);
  });

  test('an untagged actor does not block', () {
    // `blockingTags` defaults to ["solid"], as in the sibling systems.
    final game = _game({'blockingLayers': ['actors']});
    expect(_pushRight(game, _levelJson(actorKind: 'ghost')), 2);
  });

  test('empty blockingTags means any entity blocks', () {
    final game = _game({
      'blockingLayers': ['actors'],
      'blockingTags': <dynamic>[],
    });
    expect(_pushRight(game, _levelJson(actorKind: 'ghost')), 1);
  });

  test('an empty cell on a blocking layer is no obstacle', () {
    final game = _game({'blockingLayers': ['actors']});
    expect(_pushRight(game, _levelJson()), 2);
  });

  test('listing objects is a no-op', () {
    // The push logic owns that layer; a generic check would break chainPush.
    final game = _game({
      'blockingLayers': ['objects', 'actors'],
      'chainPush': true,
    });
    expect(_pushRight(game, _levelJson(secondCrate: true)), 2);
  });

  test('the chain destination is checked too', () {
    final game = _game({
      'blockingLayers': ['actors'],
      'chainPush': true,
    });
    // The lead crate would land on the guard, so nothing moves.
    expect(
        _pushRight(game,
            _levelJson(actorKind: 'guard', actorX: 3, secondCrate: true)),
        1);
  });
}
