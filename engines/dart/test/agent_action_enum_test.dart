// Parity mirror of engines/python/test_action_enum.py: the Dart runner must
// offer exactly the action list the Python runner offers (same candidates,
// same order, same "effectful" probe), named and anonymous.
import 'package:gridponder_engine/engine.dart';
import 'package:gridponder_engine/src/agent/py_format.dart';
import 'package:test/test.dart';

TurnEngine _engine(Map<String, dynamic> game, Map<String, dynamic> level) {
  final g = GameDefinition.fromJson(game, id: 'test_action_enum');
  return TurnEngine(g, LevelDefinition.fromJson(level, g.layers));
}

List<Map<String, dynamic>> _json(List<GameAction> actions) =>
    actions.map((a) => a.toJson()).toList();

/// Same scenario as the Python probe test: a 3x1 corridor, void on the left.
Map<String, dynamic> _navGame() => {
      'id': 'nav',
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
      ],
      'entityKinds': {
        'empty': {
          'layer': 'ground',
          'tags': ['walkable'],
          'symbol': '.'
        },
        'void': {
          'layer': 'ground',
          'tags': ['solid'],
          'symbol': '#'
        },
      },
      'actions': [
        {
          'id': 'move',
          'params': {
            'direction': {
              'type': 'direction',
              'values': ['left', 'right'],
            },
          },
        },
        {'id': 'unused'},
      ],
      'systems': [
        {
          'id': 'nav',
          'type': 'avatar_navigation',
          'config': {'moveAction': 'move', 'solidHandling': 'block'},
        },
      ],
    };

Map<String, dynamic> _navLevel() => {
      'id': 'l',
      'board': {
        'size': [3, 1],
        'layers': {
          'ground': [
            ['void', 'empty', 'empty'],
          ],
        },
      },
      'state': {
        'avatar': {
          'enabled': true,
          'position': [1, 0],
        },
      },
      'goals': [],
    };

/// Two selectable pieces over a wall row; `tap_cell` takes a position.
Map<String, dynamic> _selectGame() => {
      'id': 'select',
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
        {'id': 'actors', 'occupancy': 'zero_or_one'},
      ],
      'entityKinds': {
        'empty': {
          'layer': 'ground',
          'tags': ['walkable'],
          'symbol': '.'
        },
        'wall': {
          'layer': 'ground',
          'tags': ['solid'],
          'symbol': '#'
        },
        'wei': {
          'layer': 'actors',
          'tags': ['actor'],
          'symbol': 'W'
        },
        'shu': {
          'layer': 'actors',
          'tags': ['actor'],
          'symbol': 'S'
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
        {
          'id': 'tap_cell',
          'params': {
            'position': {'type': 'position'},
          },
        },
      ],
      'systems': [
        {'id': 'individual', 'type': 'individual_actors', 'config': {}},
      ],
    };

Map<String, dynamic> _selectLevel() => {
      'id': 'l',
      'board': {
        'size': [3, 2],
        'layers': {
          'ground': [
            ['empty', 'empty', 'empty'],
            ['wall', 'wall', 'wall'],
          ],
          'actors': {
            'format': 'sparse',
            'entries': [
              {
                'position': [0, 0],
                'kind': 'wei'
              },
              {
                'position': [2, 0],
                'kind': 'shu'
              },
            ],
          },
        },
      },
      'state': {
        'avatar': {'enabled': false},
      },
      'goals': [],
    };

void main() {
  test('engine probe filters vetoed and no-effect actions', () {
    final engine = _engine(_navGame(), _navLevel());
    final actions = AgentObservation.enumerateActions(engine.game, engine.state,
        engine: engine);
    expect(_json(actions), [
      {'action': 'move', 'direction': 'right'},
    ]);
    // The probe never touches the live state.
    expect(engine.state.avatar.position, const Position(1, 0));
    expect(engine.undoDepth, 0);
    expect(engine.state.actionCount, 0);
  });

  test('position params enumerate every cell in row-major order', () {
    final engine = _engine(_selectGame(), _selectLevel());
    final actions =
        AgentObservation.enumerateActions(engine.game, engine.state);
    expect(_json(actions), [
      {'action': 'move', 'direction': 'up'},
      {'action': 'move', 'direction': 'down'},
      {'action': 'move', 'direction': 'left'},
      {'action': 'move', 'direction': 'right'},
      for (final p in [
        [0, 0],
        [1, 0],
        [2, 0],
        [0, 1],
        [1, 1],
        [2, 1],
      ])
        {'action': 'tap_cell', 'position': p},
    ]);
  });

  test('probed position actions match the Python enumerator', () {
    // Expected lists produced by engines/python/action_enum.py on the same
    // scenario.
    final engine = _engine(_selectGame(), _selectLevel());
    expect(
        _json(AgentObservation.enumerateActions(engine.game, engine.state,
            engine: engine)),
        [
          {
            'action': 'tap_cell',
            'position': [0, 0]
          },
          {
            'action': 'tap_cell',
            'position': [2, 0]
          },
        ]);

    expect(
        engine
            .executeTurn(const GameAction('tap_cell', {
              'position': [0, 0]
            }))
            .accepted,
        isTrue);
    final keyBefore = AgentObservation.stateKey(engine.state, engine.game);
    expect(
        _json(AgentObservation.enumerateActions(engine.game, engine.state,
            engine: engine)),
        [
          {'action': 'move', 'direction': 'up'},
          {'action': 'move', 'direction': 'down'},
          {'action': 'move', 'direction': 'left'},
          {'action': 'move', 'direction': 'right'},
          {
            'action': 'tap_cell',
            'position': [0, 0]
          },
          {
            'action': 'tap_cell',
            'position': [2, 0]
          },
        ]);
    expect(AgentObservation.stateKey(engine.state, engine.game), keyBefore);
    expect(engine.undoDepth, 1);
  });

  test('observation built with an engine offers the probed list', () {
    final engine = _engine(_selectGame(), _selectLevel());
    final obs = AgentObservation.build(engine.game, engine.level, engine.state,
        engine: engine);
    expect(obs.validActions.map((a) => a.actionId).toSet(), {'tap_cell'});
    expect(obs.validActions, hasLength(2));
  });

  test('anon labels sort by Python json.dumps(sort_keys=True)', () {
    final map = buildAnonReverseMap(const [
      GameAction('tap_cell', {
        'position': [1, 0]
      }),
      GameAction('move', {'direction': 'up'}),
      GameAction('press'),
    ]);
    expect(map.map((k, v) => MapEntry(k, pyJsonDumps(v.toJson()))), {
      'a1': '{"action": "move", "direction": "up"}',
      'a2': '{"action": "press"}',
      'a3': '{"action": "tap_cell", "position": [1, 0]}',
    });
  });

  group('py_format', () {
    test('pyJsonDumps matches json.dumps(sort_keys=True)', () {
      expect(
          pyJsonDumps({
            'z': 1,
            'a': [true, null, 1.0, 'é'],
            'm': {'b': 'x"y', 'a': 2}
          }),
          '{"a": [true, null, 1.0, "\\u00e9"], "m": {"a": 2, "b": "x\\"y"}, "z": 1}');
    });

    test('pyStr matches Python str()', () {
      expect(pyStr('left'), 'left');
      expect(pyStr(3), '3');
      expect(pyStr(2.0), '2.0');
      expect(pyStr(true), 'True');
      expect(pyStr(null), 'None');
      expect(
          pyStr([
            1,
            'a',
            [2, 3]
          ]),
          "[1, 'a', [2, 3]]");
      expect(pyStr({'k': 'v', 'n': false}), "{'k': 'v', 'n': False}");
      expect(pyStr(["it's"]), '["it\'s"]');
    });
  });
}
