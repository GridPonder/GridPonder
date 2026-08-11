// Parity mirror of engines/python/test_follower_npcs.py — cases for the
// `follower_npcs` system that a gold path cannot express, because they end in a
// loss or assert on internal state.
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _makeGame(
  Map<String, dynamic> behavior, {
  Map<String, dynamic>? navConfig,
  String? contactVariable,
}) {
  final npcConfig = <String, dynamic>{
    'behaviors': {'hunt': behavior},
  };
  if (contactVariable != null) {
    npcConfig['contactVariable'] = contactVariable;
  }

  final data = {
    'id': 'com.gridponder.test_follower_npcs',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
      {'id': 'objects', 'occupancy': 'zero_or_one'},
      {'id': 'actors', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'empty': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': '.',
      },
      'flag': {
        'layer': 'objects',
        'tags': ['goal'],
        'symbol': 'F',
      },
      'watcher': {
        'layer': 'actors',
        'tags': ['npc', 'solid'],
        'symbol': 'W',
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
        'id': 'navigation',
        'type': 'avatar_navigation',
        'config': navConfig ?? <String, dynamic>{},
      },
      {'id': 'npcs', 'type': 'follower_npcs', 'config': npcConfig},
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_follower_npcs');
}

Map<String, dynamic> _levelJson({
  required List<int> avatar,
  required List<int> watcher,
  String contactVariable = 'caught',
  int width = 5,
}) {
  return {
    'id': 'test_level',
    'board': {
      'size': [width, 3],
      'layers': {
        'actors': {
          'format': 'sparse',
          'entries': [
            {'position': watcher, 'kind': 'watcher', 'behavior': 'hunt'},
          ],
        },
      },
    },
    'state': {
      'avatar': {'enabled': true, 'position': avatar},
    },
    'goals': <dynamic>[],
    'loseConditions': [
      {
        'type': 'variable_threshold',
        'config': {
          'variable': contactVariable,
          'target': 1,
          'comparison': 'gte',
        },
      },
    ],
  };
}

TurnEngine _engineFor(GameDefinition game, Map<String, dynamic> levelJson) {
  final level = LevelDefinition.fromJson(levelJson, game.layers);
  return TurnEngine(game, level);
}

GameAction _move(String direction) => GameAction('move', {'direction': direction});

void main() {
  group('follower_npcs lethal contact', () {
    test('stepping onto the avatar loses the level', () {
      final game = _makeGame({
        'type': 'toward_avatar',
        'requiresLineOfSight': true,
        'lethalContact': true,
      });
      final engine = _engineFor(
        game,
        _levelJson(avatar: [1, 1], watcher: [3, 1]),
      );

      // Avatar steps to (2,1), adjacent to the watcher on a clear row. The
      // watcher then steps onto the avatar instead of refusing the move.
      final result = engine.executeTurn(_move('right'));

      final caught =
          result.events.where((e) => e.type == 'avatar_caught').toList();
      expect(caught, hasLength(1));
      expect(caught.first['npcKind'], 'watcher');
      expect(engine.state.variables['caught'], 1);
      expect(result.isLost, isTrue);
      expect(result.loseReason, 'variable_threshold:caught');
    });

    test('contact is refused without lethalContact', () {
      final game = _makeGame({
        'type': 'toward_avatar',
        'requiresLineOfSight': true,
      });
      final engine = _engineFor(
        game,
        _levelJson(avatar: [1, 1], watcher: [3, 1]),
      );

      final result = engine.executeTurn(_move('right'));

      expect(result.events.any((e) => e.type == 'avatar_caught'), isFalse);
      // The watcher's only distance-reducing step is the avatar's cell, so it
      // should not move at all.
      expect(result.events.any((e) => e.type == 'npc_moved'), isFalse);
      expect(engine.state.variables.containsKey('caught'), isFalse);
      expect(result.isLost, isFalse);
    });

    test('the contact variable name is configurable', () {
      final game = _makeGame(
        {'type': 'toward_avatar', 'lethalContact': true},
        contactVariable: 'doom',
      );
      final engine = _engineFor(
        game,
        _levelJson(avatar: [1, 1], watcher: [3, 1], contactVariable: 'doom'),
      );

      final result = engine.executeTurn(_move('right'));

      expect(engine.state.variables['doom'], 1);
      expect(result.loseReason, 'variable_threshold:doom');
    });
  });

  group('avatar_navigation solidLayers', () {
    test('a solid NPC blocks the avatar when actors is listed', () {
      final game = _makeGame(
        {'type': 'toward_avatar', 'requiresLineOfSight': true},
        navConfig: {
          'solidLayers': ['objects', 'actors'],
        },
      );
      final engine = _engineFor(
        game,
        _levelJson(avatar: [1, 1], watcher: [2, 1]),
      );

      // The turn is still spent — `accepted` only goes false for an unknown
      // action or an explicit veto, not for a blocked move.
      final result = engine.executeTurn(_move('right'));

      expect(engine.state.avatar.position!.x, 1);
      expect(result.events.any((e) => e.type == 'avatar_entered'), isFalse);
    });

    test('an NPC does not block the avatar by default', () {
      final game = _makeGame({
        'type': 'toward_avatar',
        'requiresLineOfSight': true,
      });
      final engine = _engineFor(
        game,
        _levelJson(avatar: [1, 1], watcher: [2, 1]),
      );

      final result = engine.executeTurn(_move('right'));

      expect(result.accepted, isTrue);
      expect(engine.state.avatar.position!.x, 2);
    });
  });

  test('a blocked move still advances the turn', () {
    // Load-bearing for level design: walking into an obstacle is a usable wait
    // action, so a level cannot force the player to stall by moving.
    final game = _makeGame({
      'type': 'toward_avatar',
      'requiresLineOfSight': true,
    });
    final engine = _engineFor(
      game,
      _levelJson(avatar: [0, 1], watcher: [3, 1]),
    );

    final result = engine.executeTurn(_move('left')); // into the board edge

    expect(engine.state.avatar.position!.x, 0);
    expect(
      result.events.where((e) => e.type == 'npc_moved'),
      hasLength(1),
      reason: 'the watcher should still have acted',
    );
    expect(engine.state.turnCount, 1);
  });
}
