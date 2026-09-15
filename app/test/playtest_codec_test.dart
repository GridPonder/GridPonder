import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:gridponder_app/src/services/playtest_codec.dart';
import 'package:gridponder_engine/engine.dart';

Board _board({
  Map<Position, EntityInstance> objects = const {},
  List<MultiCellObjectInstance> mcos = const [],
}) {
  final layer = BoardLayer.empty(5, 3);
  for (final e in objects.entries) {
    layer.setAt(e.key, e.value);
  }
  return Board(
    width: 5,
    height: 3,
    layers: {'ground': BoardLayer.empty(5, 3, 'floor'), 'objects': layer},
    multiCellObjects: [for (final m in mcos) m.copy()],
  );
}

Map<String, dynamic> _delta(Board before, Board after) {
  final bd = boardDelta(BoardSnapshot.of(before), BoardSnapshot.of(after));
  return bd.isEmpty ? {} : jsonDecode(bd) as Map<String, dynamic>;
}

Map<String, dynamic> _level() => {
  'id': 'l1',
  'title': 'First',
  'guide': 'Push the box.',
  'metadata': {'difficulty': 3},
  'board': {
    'size': [5, 3],
    'layers': {
      'objects': [
        {
          'position': [1, 1],
          'kind': 'box_fragment',
          'sides': ['n'],
        },
      ],
    },
  },
  'state': {
    'avatar': {
      'position': [0, 0],
    },
  },
  'goals': [
    {'type': 'reach_exit'},
  ],
  'rules': <dynamic>[],
  'systemOverrides': {
    'push': {'chainPush': false},
  },
  'solution': {
    'goldPath': [
      {'action': 'move', 'direction': 'right'},
    ],
  },
};

Map<String, dynamic> _game() => {
  'layers': [
    {'id': 'objects'},
  ],
  'systems': [
    {'id': 'push', 'type': 'push_objects'},
  ],
  'rules': <dynamic>[],
  'ui': {'showGuide': true},
  'levelSequence': [
    {'type': 'level', 'ref': 'l1'},
  ],
  'goalDescriptions': {'reach_exit': 'Reach the exit'},
};

void main() {
  group('canonicalJson', () {
    test('sorts map keys at every depth', () {
      expect(
        canonicalJson({
          'b': 1,
          'a': {'y': 2, 'x': 3},
        }),
        '{"a":{"x":3,"y":2},"b":1}',
      );
    });
  });

  group('fnv1a32', () {
    test('matches the reference vectors', () {
      expect(fnv1a32(''), '811c9dc5');
      expect(fnv1a32('a'), 'e40c292c');
      expect(fnv1a32('foobar'), 'bf9cf968');
    });
  });

  group('levelRevision', () {
    final base = levelRevision(_level(), _game());

    test('ignores presentation-only keys', () {
      final level = _level()
        ..['title'] = 'Renamed'
        ..['guide'] = 'Different words.'
        ..['metadata'] = {'difficulty': 9};
      final game = _game()
        ..['ui'] = {'showGuide': false}
        ..['levelSequence'] = <dynamic>[]
        ..['goalDescriptions'] = <String, dynamic>{};
      expect(levelRevision(level, game), base);
    });

    test('does not depend on key order', () {
      final reordered = Map<String, dynamic>.fromEntries(
        _level().entries.toList().reversed,
      );
      expect(levelRevision(reordered, _game()), base);
    });

    test('changes with every behaviour-relevant part of the level', () {
      final edits = <String, void Function(Map<String, dynamic>)>{
        'entity params': (l) =>
            ((l['board']['layers']['objects'] as List)[0] as Map)['sides'] = [
              'n',
              'e',
            ],
        'goals': (l) => l['goals'] = [
          {'type': 'clear_board'},
        ],
        'rules': (l) => l['rules'] = [
          {'on': 'turn_ended'},
        ],
        'system overrides': (l) =>
            (l['systemOverrides'] as Map)['push'] = {'chainPush': true},
        'gold-path actions': (l) =>
            ((l['solution']['goldPath'] as List)[0] as Map)['direction'] =
                'left',
        'initial state': (l) => l['state'] = {
          'avatar': {
            'position': [1, 0],
          },
        },
      };
      for (final entry in edits.entries) {
        final level = _level();
        entry.value(level);
        expect(levelRevision(level, _game()), isNot(base), reason: entry.key);
      }
    });

    test('changes when the game definition changes', () {
      final game = _game()
        ..['systems'] = [
          {
            'id': 'push',
            'type': 'push_objects',
            'config': {'chainPush': true},
          },
        ];
      expect(levelRevision(_level(), game), isNot(base));
    });
  });

  group('boardDelta', () {
    test('is empty when nothing changed', () {
      final board = _board(
        objects: {const Position(1, 1): EntityInstance('rock')},
      );
      expect(boardDelta(BoardSnapshot.of(board), BoardSnapshot.of(board)), '');
    });

    test('reports moves, arrivals and vacated cells per layer', () {
      final before = _board(
        objects: {const Position(1, 1): EntityInstance('rock')},
      );
      final after = _board(
        objects: {const Position(2, 1): EntityInstance('rock')},
      );
      expect(_delta(before, after), {
        'cells': {
          'objects': {'1.1': null, '2.1': 'rock'},
        },
      });
    });

    test('reports a param-only change, with sorted params', () {
      final before = _board(
        objects: {
          const Position(1, 1): EntityInstance('box_fragment', {
            'sides': ['n'],
          }),
        },
      );
      final after = _board(
        objects: {
          const Position(1, 1): EntityInstance('box_fragment', {
            'z': 1,
            'sides': ['n', 'e'],
          }),
        },
      );
      final bd = boardDelta(BoardSnapshot.of(before), BoardSnapshot.of(after));
      expect(
        bd,
        '{"cells":{"objects":{"1.1":["box_fragment",{"sides":["n","e"],"z":1}]}}}',
      );
    });

    test('catches params edited in place after the snapshot', () {
      final board = _board(
        objects: {
          const Position(1, 1): EntityInstance('guard', {'facing': 'left'}),
        },
      );
      final before = BoardSnapshot.of(board);
      board.layers['objects']!.getAt(const Position(1, 1))!.params['facing'] =
          'right';
      expect(jsonDecode(boardDelta(before, BoardSnapshot.of(board))), {
        'cells': {
          'objects': {
            '1.1': [
              'guard',
              {'facing': 'right'},
            ],
          },
        },
      });
    });

    test('reports multi-cell objects that move, grow or vanish', () {
      MultiCellObjectInstance block(List<Position> cells) =>
          MultiCellObjectInstance(
            id: 'blk',
            kind: 'elastic_block',
            cells: cells,
          );
      final before = _board(
        mcos: [
          block([const Position(0, 0), const Position(1, 0)]),
        ],
      );
      final grown = _board(
        mcos: [
          block([
            const Position(0, 0),
            const Position(1, 0),
            const Position(2, 0),
          ]),
        ],
      );
      expect(_delta(before, grown), {
        'objects': {
          'blk': [
            'elastic_block',
            ['0.0', '1.0', '2.0'],
            <String, dynamic>{},
          ],
        },
      });
      expect(_delta(before, _board()), {
        'objects': {'blk': null},
      });
    });
  });
}
