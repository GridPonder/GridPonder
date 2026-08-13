/// previewTurn — a dry run must answer "what would this do?" and change nothing.
///
/// Kept in lockstep with engines/python/test_turn_preview.py: the two engines
/// must agree on what a preview reports and on when an action is refused.
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _game() {
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
      'exit': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': 'E',
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
        'config': {
          'validGroundTags': ['walkable'],
        },
      },
    ],
  }, id: 'turn_preview_test');
}

// 4x1 board:  H H E H  — the avatar starts at the left end. Reaching the exit
// wins, and a walkable cell remains past it, so an action taken after the win
// is refused because the level is over, not because it is illegal.
LevelDefinition _level(GameDefinition game) {
  return LevelDefinition.fromJson({
    'id': 'turn_preview',
    'board': {
      'size': [4, 1],
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
              'kind': 'hull'
            },
            {
              'position': [2, 0],
              'kind': 'exit'
            },
            {
              'position': [3, 0],
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
    'goals': [
      {
        'id': 'reach_exit',
        'type': 'reach_target',
        'config': {'targetKind': 'exit'},
      }
    ],
    'rules': <Map<String, dynamic>>[],
    'solution': {'goldPath': <Map<String, dynamic>>[]},
  }, game.layers);
}

GameAction _right() => GameAction('move', {'direction': 'right'});

void _walkToExit(TurnEngine engine) {
  engine.executeTurn(_right());
  engine.executeTurn(_right());
}

/// Events reduced to what both engines can be compared on.
List<String> _summarise(List<GameEvent> events) =>
    [for (final e in events) '${e.type}@${e.position}'];

void main() {
  test('preview reports what the turn would do', () {
    final game = _game();
    final engine = TurnEngine(game, _level(game));

    final result = engine.previewTurn(_right());

    expect(result.accepted, isTrue);
    final entered = result.events.where((e) => e.type == 'avatar_entered');
    expect(entered.map((e) => e.position), [const Position(1, 0)]);
  });

  test('preview commits nothing', () {
    final game = _game();
    final engine = TurnEngine(game, _level(game));

    engine.previewTurn(_right());

    // Position, both counters and the undo stack are exactly as they were.
    expect(engine.state.avatar.position, const Position(0, 0));
    expect(engine.state.actionCount, 0);
    expect(engine.state.turnCount, 0);
    expect(engine.undoDepth, 0);
  });

  test('preview matches the turn it predicts', () {
    final game = _game();
    final engine = TurnEngine(game, _level(game));

    final predicted = engine.previewTurn(_right());
    final actual = engine.executeTurn(_right());

    expect(predicted.accepted, actual.accepted);
    expect(_summarise(predicted.events), _summarise(actual.events));
  });

  test('a won level refuses further actions', () {
    final game = _game();
    final engine = TurnEngine(game, _level(game));
    _walkToExit(engine);
    expect(engine.isWon, isTrue);

    final result = engine.executeTurn(_right());

    // (3,0) is walkable, so only the win can be refusing this.
    expect(result.accepted, isFalse);
    expect(engine.state.avatar.position, const Position(2, 0));
    expect(engine.state.actionCount, 2);
    expect(engine.state.turnCount, 2);
  });

  test('preview on a won level is refused', () {
    final game = _game();
    final engine = TurnEngine(game, _level(game));
    _walkToExit(engine);

    final result = engine.previewTurn(_right());

    expect(result.accepted, isFalse);
    expect(result.events, isEmpty);
  });
}
