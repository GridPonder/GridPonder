import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _game(List<String>? validGroundTags) {
  return GameDefinition.fromJson({
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'void'},
    ],
    'entityKinds': {
      'void': {'layer': 'ground', 'tags': <String>[], 'symbol': ' '},
      'hull': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': 'H',
      },
      'wreck': {
        'layer': 'ground',
        'tags': ['solid'],
        'symbol': 'w',
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
        'id': 'nav',
        'type': 'avatar_navigation',
        'config': <String, dynamic>{
          if (validGroundTags != null) 'validGroundTags': validGroundTags,
        },
      },
    ],
  }, id: 'ground_tags_test');
}

// 3x1 board:  H w H  — the avatar starts on the left hull plate.
LevelDefinition _level(GameDefinition game) {
  return LevelDefinition.fromJson({
    'id': 'ground_tags',
    'board': {
      'size': [3, 1],
      'layers': {
        'ground': {
          'format': 'sparse',
          'entries': [
            {
              'position': [0, 0],
              'kind': 'hull'
            },
            {
              'position': [1, 0],
              'kind': 'wreck'
            },
            {
              'position': [2, 0],
              'kind': 'hull'
            },
          ],
        },
      },
    },
    'state': {
      'avatar': {
        'enabled': true,
        'position': [0, 0]
      }
    },
    'goals': <Map<String, dynamic>>[],
    'rules': <Map<String, dynamic>>[],
    'solution': {'goldPath': <Map<String, dynamic>>[]},
  }, game.layers);
}

void main() {
  test('move onto untagged ground is rejected', () {
    final game = _game(const ['walkable']);
    final engine = TurnEngine(game, _level(game));

    engine.executeTurn(GameAction('move', {'direction': 'right'}));

    // wreck is not walkable — the avatar stays put.
    expect(engine.state.avatar.position, const Position(0, 0));
  });

  test('move onto tagged ground is allowed', () {
    final game = _game(const ['walkable']);
    final engine = TurnEngine(game, _level(game));
    engine.state.avatar =
        engine.state.avatar.copyWith(position: const Position(1, 0));

    engine.executeTurn(GameAction('move', {'direction': 'right'}));

    // hull at (2,0) is walkable — the move succeeds.
    expect(engine.state.avatar.position, const Position(2, 0));
  });

  test('absent config preserves existing behaviour', () {
    final game = _game(null);
    final engine = TurnEngine(game, _level(game));

    engine.executeTurn(GameAction('move', {'direction': 'right'}));

    // No validGroundTags: wreck is non-void ground with nothing solid on the
    // objects layer, so the move succeeds exactly as it does today.
    expect(engine.state.avatar.position, const Position(1, 0));
  });
}
