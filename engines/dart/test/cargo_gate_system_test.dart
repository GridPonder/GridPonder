// Parity mirror of engines/python/test_cargo_gate.py — the `cargo_gate`
// system (docs/dsl/04_systems.md §2.28).
//
// A 6x1 corridor; the avatar starts at x=2 facing a gate cell at x=3. Its
// cargo is seeded directly into the trailing_body system's segment list,
// straight behind it, since building it up through pickups isn't the point.
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _makeGame() {
  final data = {
    'id': 'com.gridponder.test_cargo_gate',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
      {'id': 'tail', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'floor': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': '.',
      },
      'colored_road': {
        'layer': 'ground',
        'tags': ['walkable', 'cargo_gate'],
        'symbol': 'c',
      },
      'seg': {
        'layer': 'tail',
        'tags': ['solid'],
        'symbol': 's',
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
        'id': 'gates',
        'type': 'cargo_gate',
        'config': {'cargoSystem': 'trail', 'maxCargo': 1},
      },
      {
        'id': 'navigation',
        'type': 'avatar_navigation',
        'config': {
          'solidLayers': ['tail'],
        },
      },
      {
        'id': 'trail',
        'type': 'trailing_body',
        'config': {
          'moverTag': 'avatar',
          'bodyLayer': 'tail',
          'segmentKindTemplate': 'seg',
        },
      },
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_cargo_gate');
}

TurnEngine _engine(String? gateColor, List<String> cargo) {
  final game = _makeGame();
  final levelJson = {
    'id': 'test_level',
    'board': {
      'size': [6, 1],
      'layers': {
        'ground': {
          'format': 'sparse',
          'entries': [
            if (gateColor != null)
              {
                'position': [3, 0],
                'kind': 'colored_road',
                'color': gateColor,
              },
          ],
        },
      },
    },
    'state': {
      'avatar': {
        'enabled': true,
        'position': [2, 0],
      },
    },
    'goals': <dynamic>[],
    'loseConditions': <dynamic>[],
  };
  final engine =
      TurnEngine(game, LevelDefinition.fromJson(levelJson, game.layers));
  engine.state.variables['_trailingBody_trail_segments'] = [
    for (var i = 0; i < cargo.length; i++)
      {
        'position': [1 - i, 0],
        'color': cargo[i],
      },
  ];
  return engine;
}

TurnResult _stepRight(TurnEngine engine) =>
    engine.executeTurn(GameAction('move', {'direction': 'right'}));

void main() {
  test('empty truck enters any gate', () {
    final engine = _engine('blue', []);
    expect(_stepRight(engine).accepted, isTrue);
    expect(engine.state.avatar.position, const Position(3, 0));
  });

  test('single matching car enters', () {
    final engine = _engine('red', ['red']);
    expect(_stepRight(engine).accepted, isTrue);
    expect(engine.state.avatar.position, const Position(3, 0));
  });

  test('single other color is refused without spending the turn', () {
    final engine = _engine('blue', ['red']);
    final result = _stepRight(engine);
    expect(result.accepted, isFalse);
    expect(engine.state.avatar.position, const Position(2, 0));
    expect(engine.state.actionCount, 0);
    final blocked =
        result.events.where((e) => e.type == 'cell_blocked').toList();
    expect(blocked, isNotEmpty);
    expect(blocked.first.position, const Position(3, 0));
  });

  test('two cars are refused even when both match', () {
    final engine = _engine('red', ['red', 'red']);
    expect(_stepRight(engine).accepted, isFalse);
    expect(engine.state.avatar.position, const Position(2, 0));
  });

  test('plain road ignores cargo', () {
    final engine = _engine(null, ['red', 'blue']);
    expect(_stepRight(engine).accepted, isTrue);
    expect(engine.state.avatar.position, const Position(3, 0));
  });
}
