// Parity mirror of engines/python/test_claim_overwrite.py — claim.overwrite
// policy: never / always / tagged.
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _makeGame(Map<String, dynamic>? overwrite) {
  final claim = <String, dynamic>{
    'layer': 'territory',
    'map': {'alpha': 'terr_alpha', 'beta': 'terr_beta'},
  };
  if (overwrite != null) claim['overwrite'] = overwrite;

  final data = {
    'id': 'com.gridponder.test_claim_overwrite',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
      {'id': 'actors', 'occupancy': 'zero_or_one'},
      {'id': 'territory', 'occupancy': 'zero_or_one'},
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
      'contested': {
        'layer': 'ground',
        'tags': ['walkable', 'contested'],
        'symbol': 'C',
      },
      'alpha': {
        'layer': 'actors',
        'tags': ['actor'],
        'symbol': 'A',
      },
      'beta': {
        'layer': 'actors',
        'tags': ['actor'],
        'symbol': 'B',
      },
      'terr_alpha': {
        'layer': 'territory',
        'tags': ['territory'],
        'symbol': 'a',
      },
      'terr_beta': {
        'layer': 'territory',
        'tags': ['territory'],
        'symbol': 'b',
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
      {
        'id': 'movement',
        'type': 'coupled_actors',
        'config': {'claim': claim},
      },
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_claim_overwrite');
}

Map<String, dynamic> _level({
  List<Map<String, dynamic>> ground = const [],
  List<Map<String, dynamic>> territory = const [],
  List<Map<String, dynamic>> actors = const [],
}) {
  return {
    'id': 'lvl',
    'board': {
      'size': [4, 1],
      'layers': {
        'ground': {'format': 'sparse', 'entries': ground},
        'actors': {'format': 'sparse', 'entries': actors},
        'territory': {'format': 'sparse', 'entries': territory},
      },
    },
    'state': {},
    'goals': [],
    'loseConditions': [],
  };
}

TurnEngine _engineFor(GameDefinition game, Map<String, dynamic> levelJson) {
  final level = LevelDefinition.fromJson(levelJson, game.layers);
  return TurnEngine(game, level);
}

String? _ownerAt(TurnEngine engine, int x, int y) =>
    engine.state.board.getEntity('territory', Position(x, y))?.kind;

GameAction _moveRight() => GameAction('move', {'direction': 'right'});

void main() {
  group('claim.overwrite', () {
    test('never does not repaint an owned cell (transit)', () {
      final engine = _engineFor(
        _makeGame(null),
        _level(
          territory: [
            {
              'position': [1, 0],
              'kind': 'terr_beta'
            }
          ],
          actors: [
            {
              'position': [0, 0],
              'kind': 'alpha'
            }
          ],
        ),
      );

      engine.executeTurn(_moveRight());

      expect(_ownerAt(engine, 1, 0), equals('terr_beta'),
          reason: 'transit must not repaint');
    });

    test('always repaints any owned cell', () {
      final engine = _engineFor(
        _makeGame({'mode': 'always'}),
        _level(
          territory: [
            {
              'position': [1, 0],
              'kind': 'terr_beta'
            }
          ],
          actors: [
            {
              'position': [0, 0],
              'kind': 'alpha'
            }
          ],
        ),
      );

      engine.executeTurn(_moveRight());

      expect(_ownerAt(engine, 1, 0), equals('terr_alpha'),
          reason: 'always must repaint');
    });

    test('tagged repaints only tagged ground', () {
      // Tagged ground is stolen on entry; untagged owned ground is transited.
      final engine = _engineFor(
        _makeGame({'mode': 'tagged', 'tag': 'contested'}),
        _level(
          ground: [
            {
              'position': [1, 0],
              'kind': 'contested'
            }
          ],
          territory: [
            {
              'position': [1, 0],
              'kind': 'terr_beta'
            },
            {
              'position': [2, 0],
              'kind': 'terr_beta'
            },
          ],
          actors: [
            {
              'position': [0, 0],
              'kind': 'alpha'
            }
          ],
        ),
      );

      engine.executeTurn(_moveRight());
      expect(_ownerAt(engine, 1, 0), equals('terr_alpha'),
          reason: 'tagged cell must be stolen on entry');

      engine.executeTurn(_moveRight());
      expect(_ownerAt(engine, 2, 0), equals('terr_beta'),
          reason: 'plain owned cell must transit unchanged');
    });

    test('re-entering own cell emits no claim event', () {
      final engine = _engineFor(
        _makeGame({'mode': 'always'}),
        _level(
          territory: [
            {
              'position': [1, 0],
              'kind': 'terr_alpha'
            }
          ],
          actors: [
            {
              'position': [0, 0],
              'kind': 'alpha'
            }
          ],
        ),
      );

      final result = engine.executeTurn(_moveRight());
      final claimed =
          result.events.where((e) => e.type == 'cell_claimed').toList();

      expect(claimed, isEmpty,
          reason: 'no cell_claimed when re-entering your own land');
    });
  });
}
