// Parity mirror of engines/python/test_overlay_exchange.py.
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

const _pairs = [
  ['ink_red', 'held_red'],
  ['ink_blue', 'held_blue'],
  [null, 'slot_empty'],
];

GameDefinition _makeGame({List<dynamic> pairs = _pairs}) {
  Map<String, dynamic> kind(String layer, String symbol,
          [List<String> tags = const []]) =>
      {'layer': layer, 'tags': tags, 'symbol': symbol};
  final data = {
    'id': 'com.gridponder.test_overlay_exchange',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
      {'id': 'ink', 'occupancy': 'zero_or_one'},
      {'id': 'held', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'empty': kind('ground', '.'),
      'void': kind('ground', '#'),
      'ink_red': kind('ink', 'r'),
      'ink_blue': kind('ink', 'b'),
      'held_red': kind('held', 'R', ['carried']),
      'held_blue': kind('held', 'B', ['carried']),
      'slot_empty': kind('held', 'o'),
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
      {'id': 'press', 'params': <String, dynamic>{}},
    ],
    'systems': [
      {
        'id': 'cursor',
        'type': 'overlay_cursor',
        'config': {
          'moveAction': 'move',
          'size': [2, 2],
          'carryLayers': ['held'],
        },
      },
      {
        'id': 'stamp',
        'type': 'region_transform',
        'config': {
          'operations': {
            'press': {
              'type': 'exchange',
              'action': 'press',
              'layers': ['ink', 'held'],
              'pairs': pairs,
            },
          },
        },
      },
    ],
    'defaults': {
      'avatar': {'enabled': false},
    },
  };
  return GameDefinition.fromJson(data, id: 'test_overlay_exchange');
}

Map<String, dynamic> _level(
  Map<(int, int), String> ink,
  Map<(int, int), String> held, {
  (int, int) overlay = (0, 0),
  List<(int, int)> voids = const [],
  List<dynamic> goals = const [],
}) {
  List<dynamic> entries(Map<(int, int), String> m) => [
        for (final e in m.entries)
          {
            'position': [e.key.$1, e.key.$2],
            'kind': e.value,
          },
      ];
  return {
    'id': 't',
    'board': {
      'size': [4, 3],
      'layers': {
        'ground': {
          'format': 'sparse',
          'entries': [
            for (final p in voids)
              {
                'position': [p.$1, p.$2],
                'kind': 'void',
              },
          ],
        },
        'ink': {'format': 'sparse', 'entries': entries(ink)},
        'held': {'format': 'sparse', 'entries': entries(held)},
      },
    },
    'state': {
      'avatar': {'enabled': false},
      'overlay': {
        'position': [overlay.$1, overlay.$2],
        'size': [2, 2],
      },
    },
    'goals': goals,
  };
}

/// The four held-layer cells of a 2x2 overlay at (x, y), empty by default.
Map<(int, int), String> _slots(
    {int x = 0, int y = 0, String? a, String? b, String? c, String? d}) {
  return {
    (x, y): a ?? 'slot_empty',
    (x + 1, y): b ?? 'slot_empty',
    (x, y + 1): c ?? 'slot_empty',
    (x + 1, y + 1): d ?? 'slot_empty',
  };
}

TurnEngine _engineFor(GameDefinition game, Map<String, dynamic> levelJson) =>
    TurnEngine(game, LevelDefinition.fromJson(levelJson, game.layers));

String? _kind(TurnEngine engine, String layer, int x, int y) =>
    engine.state.board.getEntity(layer, Position(x, y))?.kind;

TurnResult _press(TurnEngine engine) =>
    engine.executeTurn(const GameAction('press', {}));

TurnResult _move(TurnEngine engine, String direction) =>
    engine.executeTurn(GameAction('move', {'direction': direction}));

/// Everything the tests below care about, as one comparable value.
String _snapshot(TurnEngine engine) {
  final s = engine.state;
  final cells = <String>[];
  for (final layer in ['ink', 'held']) {
    for (int y = 0; y < s.board.height; y++) {
      for (int x = 0; x < s.board.width; x++) {
        cells.add(_kind(engine, layer, x, y) ?? '-');
      }
    }
  }
  return '${s.overlay!.x},${s.overlay!.y}|${cells.join(',')}';
}

void main() {
  group('overlay_cursor carryLayers', () {
    test('the held layer rides with the overlay', () {
      final engine = _engineFor(
          _makeGame(), _level({(0, 0): 'ink_red'}, _slots(a: 'held_blue')));
      _move(engine, 'right');
      expect((engine.state.overlay!.x, engine.state.overlay!.y), (1, 0));
      expect(_kind(engine, 'held', 1, 0), 'held_blue');
      expect(_kind(engine, 'held', 2, 1), 'slot_empty');
      expect(_kind(engine, 'held', 0, 0), isNull);
      expect(_kind(engine, 'held', 0, 1), isNull);
      // Moving never touches the layer underneath.
      expect(_kind(engine, 'ink', 0, 0), 'ink_red');
    });

    test('a blocked move keeps everything in place', () {
      final engine = _engineFor(_makeGame(), _level({}, _slots(d: 'held_red')));
      _move(engine, 'left');
      _move(engine, 'up');
      expect((engine.state.overlay!.x, engine.state.overlay!.y), (0, 0));
      expect(_kind(engine, 'held', 1, 1), 'held_red');
    });
  });

  group('region_transform exchange', () {
    test('all four cells exchange at once', () {
      final engine = _engineFor(
        _makeGame(),
        _level(
          {(0, 0): 'ink_red', (1, 1): 'ink_blue', (1, 0): 'ink_red'},
          _slots(b: 'held_blue', c: 'held_red'),
        ),
      );
      final result = _press(engine);
      // a: red lifted; b: red <-> blue swapped; c: red dropped; d: blue lifted.
      expect(_kind(engine, 'held', 0, 0), 'held_red');
      expect(_kind(engine, 'ink', 0, 0), isNull);
      expect(_kind(engine, 'ink', 1, 0), 'ink_blue');
      expect(_kind(engine, 'held', 1, 0), 'held_red');
      expect(_kind(engine, 'ink', 0, 1), 'ink_red');
      expect(_kind(engine, 'held', 0, 1), 'slot_empty');
      expect(_kind(engine, 'held', 1, 1), 'held_blue');
      expect(_kind(engine, 'ink', 1, 1), isNull);
      final modes = {
        for (final e in result.events.where((e) => e.type == 'cell_exchanged'))
          (e.position!.x, e.position!.y): e['mode'],
      };
      expect(modes, {
        (0, 0): 'lift',
        (1, 0): 'swap',
        (0, 1): 'drop',
        (1, 1): 'lift',
      });
    });

    test('empty on empty changes nothing and says nothing', () {
      final engine = _engineFor(_makeGame(), _level({}, _slots()));
      final result = _press(engine);
      expect(result.events.where((e) => e.type == 'cell_exchanged'), isEmpty);
      for (final (x, y) in [(0, 0), (1, 0), (0, 1), (1, 1)]) {
        expect(_kind(engine, 'held', x, y), 'slot_empty');
        expect(_kind(engine, 'ink', x, y), isNull);
      }
    });

    test('pressing twice restores', () {
      final engine = _engineFor(
        _makeGame(),
        _level({(0, 0): 'ink_red', (1, 1): 'ink_blue'}, _slots(b: 'held_red')),
      );
      final before = _snapshot(engine);
      _press(engine);
      expect(_snapshot(engine), isNot(before));
      _press(engine);
      expect(_snapshot(engine), before);
    });

    test('carry then deposit', () {
      final engine =
          _engineFor(_makeGame(), _level({(0, 0): 'ink_red'}, _slots()));
      _press(engine);
      _move(engine, 'right');
      _move(engine, 'right');
      _press(engine);
      expect(_kind(engine, 'ink', 0, 0), isNull);
      expect(_kind(engine, 'ink', 2, 0), 'ink_red');
      expect(_kind(engine, 'held', 2, 0), 'slot_empty');
    });

    test('undo restores the cursor and the held layer', () {
      final engine =
          _engineFor(_makeGame(), _level({(0, 0): 'ink_red'}, _slots()));
      final before = _snapshot(engine);
      _press(engine);
      _move(engine, 'right');
      engine.undo();
      engine.undo();
      expect(_snapshot(engine), before);
    });

    test('unpaired kinds cross unchanged', () {
      final engine = _engineFor(
          _makeGame(pairs: const []), _level({(0, 0): 'ink_red'}, {}));
      _press(engine);
      expect(_kind(engine, 'held', 0, 0), 'ink_red');
      expect(_kind(engine, 'ink', 0, 0), isNull);
    });

    test('void cells do not exchange', () {
      final engine = _engineFor(
        _makeGame(),
        _level({(1, 0): 'ink_red'}, _slots(a: 'held_blue'), voids: [(0, 0)]),
      );
      _press(engine);
      expect(_kind(engine, 'held', 0, 0), 'held_blue');
      expect(_kind(engine, 'held', 1, 0), 'held_red');
    });

    test('the win needs an empty cursor', () {
      final goals = [
        {
          'id': 'match',
          'type': 'board_match',
          'config': {
            'matchMode': 'exact',
            'targetLayers': {
              'ink': [
                [null, 'ink_red', null, null],
                [null, null, null, null],
                [null, null, null, null],
              ],
            },
          },
        },
        {
          'id': 'empty',
          'type': 'all_cleared',
          'config': {'tag': 'carried'},
        },
      ];
      var engine = _engineFor(
        _makeGame(),
        _level({(1, 0): 'ink_red'}, _slots(x: 2, y: 1, d: 'held_red'),
            overlay: (2, 1), goals: goals),
      );
      _move(engine, 'up');
      expect(engine.isWon, isFalse);
      engine = _engineFor(
          _makeGame(), _level({}, _slots(a: 'held_red'), goals: goals));
      _move(engine, 'right');
      expect(engine.isWon, isFalse);
      _press(engine);
      expect(engine.isWon, isTrue);
    });
  });
}
