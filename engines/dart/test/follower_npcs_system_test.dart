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

GameAction _move(String direction) =>
    GameAction('move', {'direction': direction});

// -- shafts (linked machines) ------------------------------------------------
//
// The fixtures above take a single behavior and a 5x3 board; trains need two
// behaviors, a system-level config key and room for two separate tracks, so
// these are a second pair rather than a rewrite of the first. Parity mirror of
// engines/python/test_follower_npcs.py.

GameDefinition _shaftGame({
  Map<String, dynamic>? behaviors,
  Map<String, dynamic>? configExtra,
}) {
  final npcConfig = <String, dynamic>{
    'npcTags': ['npc'],
    'contactVariable': 'crushed',
    'behaviors': behaviors ??
        {
          'walker': {
            'type': 'patrol',
            'lethalContact': false,
            'solidBlocking': true,
          },
        },
  };
  npcConfig.addAll(configExtra ?? const <String, dynamic>{});

  final data = {
    'id': 'com.gridponder.test_follower_shaft',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
      {'id': 'actors', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'empty': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': '.',
      },
      'void': {
        'layer': 'ground',
        'tags': <String>[],
        'symbol': ' ',
      },
      'machine': {
        'layer': 'actors',
        'tags': ['npc', 'solid'],
        'symbol': 'M',
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
        'config': <String, dynamic>{},
      },
      {'id': 'machines', 'type': 'follower_npcs', 'config': npcConfig},
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_follower_shaft');
}

/// 8x5 board. Machines are (x, y, behavior, facing, shaft?) records.
///
/// The avatar parks at (0, 4) and spends beats by walking into the bottom edge:
/// a blocked move is still a beat, which is how the other patrol tests here
/// advance the world too.
Map<String, dynamic> _shaftLevelJson(
  List<(int, int, String, String, String?)> machines, {
  List<(int, int)> walls = const [],
}) {
  final entries = <Map<String, dynamic>>[];
  for (final m in machines) {
    final entry = <String, dynamic>{
      'position': [m.$1, m.$2],
      'kind': 'machine',
      'behavior': m.$3,
      'facing': m.$4,
    };
    if (m.$5 != null) entry['shaft'] = m.$5;
    entries.add(entry);
  }
  return {
    'id': 'test_level',
    'board': {
      'size': [8, 5],
      'layers': {
        'ground': {
          'format': 'sparse',
          'entries': [
            for (final w in walls)
              {
                'position': [w.$1, w.$2],
                'kind': 'void',
              },
          ],
        },
        'actors': {'format': 'sparse', 'entries': entries},
      },
    },
    'state': {
      'avatar': {
        'enabled': true,
        'position': [0, 4],
      },
    },
    'goals': <dynamic>[],
    'loseConditions': [
      {
        'type': 'variable_threshold',
        'config': {'variable': 'crushed', 'target': 1, 'comparison': 'gte'},
      },
    ],
  };
}

/// Spend one beat without moving: the bottom edge blocks the avatar.
void _beat(TurnEngine engine) => engine.executeTurn(_move('down'));

List<(int, int)> _machinePositions(TurnEngine engine) {
  final out = [
    for (final e in engine.state.board.layers['actors']!.entries())
      (e.key.x, e.key.y),
  ]..sort((a, b) => a.$1 == b.$1 ? a.$2.compareTo(b.$2) : a.$1.compareTo(b.$1));
  return out;
}

String _facingAt(TurnEngine engine, int x, int y) => engine.state.board
    .getEntity('actors', Position(x, y))!
    .param('facing')
    .toString();

void _expectRejects(
  GameDefinition game,
  Map<String, dynamic> levelJson,
  String word,
) {
  expect(
    () => _engineFor(game, levelJson),
    throwsA(
      isA<ArgumentError>()
          .having((e) => e.toString(), 'message', contains(word)),
    ),
  );
}

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
          'faceOnBlockedMove': true,
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
      // Opted in, so facing turns and the blocked move registers for the player.
      expect(engine.state.avatar.facing.toJson(), 'right');
    });

    test('a blocked move leaves facing alone by default', () {
      // `facing` is part of state identity, so turning on a refused move makes
      // it a fresh search node instead of a no-op. Packs pay that on request.
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
      engine.executeTurn(_move('down')); // settle facing away
      expect(engine.state.avatar.facing.toJson(), 'down');
      engine.executeTurn(_move('up')); // back to the start cell
      final positionBefore = engine.state.avatar.position;

      engine.executeTurn(_move('right')); // into the watcher

      // Nothing about the avatar changed, which is what lets the solver treat
      // the turn as a no-op. (The state-identity key itself is Python-side, so
      // test_follower_npcs.py asserts on it directly.)
      expect(engine.state.avatar.facing.toJson(), 'up');
      expect(engine.state.avatar.position, positionBefore);
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

  test('the gaze param tracks sight', () {
    // A render hint, but it must be exact: it names the direction of the avatar
    // while the NPC can see it, and 'rest' the moment sight is lost.
    final game = _makeGame({
      'type': 'toward_avatar',
      'requiresLineOfSight': true,
      'gazeParam': 'gaze',
    });
    final engine = _engineFor(
      game,
      _levelJson(avatar: [0, 1], watcher: [3, 1]),
    );

    String? watcherGaze() {
      for (final entry in engine.state.board.layers['actors']!.entries()) {
        if (entry.value.kind == 'watcher') {
          return entry.value.param('gaze') as String?;
        }
      }
      return null;
    }

    engine.executeTurn(_move('right')); // avatar to (1,1)
    expect(watcherGaze(), 'left');

    engine.executeTurn(_move('up')); // leaves row 1
    expect(watcherGaze(), 'rest');

    engine.executeTurn(_move('down')); // back onto row 1
    expect(watcherGaze(), 'left');
  });

  test('sight is published as an event', () {
    // Seeing the avatar must reach rules, not stay inside the system. Other
    // packs react to being seen through the standalone line_of_sight system; a
    // game whose watcher is a follower_npcs NPC could not, because the same
    // geometric test was computed here and thrown away.
    final game = _makeGame({
      'type': 'toward_avatar',
      'requiresLineOfSight': true,
    });
    final engine = _engineFor(
      game,
      _levelJson(avatar: [0, 1], watcher: [3, 1]),
    );

    List<GameEvent> sightings(TurnResult result) =>
        result.events.where((e) => e.type == 'line_of_sight_detected').toList();

    final seen = sightings(engine.executeTurn(_move('right')));
    expect(seen, hasLength(1));
    expect(seen.first.payload['kind'], 'avatar');
    expect(seen.first.payload['sourceKind'], 'watcher');
    expect(seen.first.payload['position'], engine.state.avatar.position);
    expect(seen.first.payload['sourcePosition'],
        isNot(equals(seen.first.payload['position'])));

    // Out of the line, nothing is reported.
    expect(sightings(engine.executeTurn(_move('up'))), isEmpty);
  });

  test('the sightline is reported from where the NPC lands', () {
    // The beam is drawn on the board the turn ends with. A chaser steps along
    // the very line it just traced, so reporting the cell it looked from leaves
    // the drawn beam trailing one segment behind the monster. The shortened
    // line is a sub-segment of the same unobstructed sightline, so it is no
    // less true.
    final game = _makeGame({
      'type': 'toward_avatar',
      'requiresLineOfSight': true,
    });
    final engine = _engineFor(
      game,
      _levelJson(avatar: [0, 1], watcher: [3, 1]),
    );
    final result = engine.executeTurn(_move('right'));

    final seen =
        result.events.where((e) => e.type == 'line_of_sight_detected').toList();
    final moved = result.events.where((e) => e.type == 'npc_moved').toList();
    expect(seen, hasLength(1));
    expect(moved, hasLength(1));
    expect(seen.first.payload['sourcePosition'],
        moved.first.payload['toPosition']);
    expect(seen.first.payload['sourcePosition'],
        isNot(equals(moved.first.payload['fromPosition'])));
    // The id still names the cell it started from, so the events correlate.
    expect(seen.first.payload['sourceId'], moved.first.payload['npcId']);
  });

  test('a still NPC reports from where it stands', () {
    final game = _makeGame({
      'type': 'toward_avatar',
      'requiresLineOfSight': true,
      'frequency': 2,
    });
    final engine = _engineFor(
      game,
      _levelJson(avatar: [0, 1], watcher: [3, 1]),
    );
    // Turn one is the acting turn (the counter starts at zero); turn two is the
    // one the gate skips. Bump the edge so the avatar holds still for both.
    engine.executeTurn(_move('left'));
    final resting = _watcherPosition(engine);
    final result = engine.executeTurn(_move('left'));

    final seen =
        result.events.where((e) => e.type == 'line_of_sight_detected').toList();
    expect(result.events.where((e) => e.type == 'npc_moved'), isEmpty);
    // Sight is still reported on a skipped turn: it saw, it just did not act.
    expect(seen, hasLength(1));
    expect(seen.first.payload['sourcePosition'], resting);
  });

  test('a patrol never reports a sightline', () {
    // A behavior that never tests a line must not claim to have seen one.
    final game = _makeGame({'type': 'patrol'});
    final engine = _engineFor(
      game,
      _levelJson(avatar: [0, 1], watcher: [3, 1]),
    );
    final result = engine.executeTurn(_move('right'));
    expect(
      result.events.where((e) => e.type == 'line_of_sight_detected'),
      isEmpty,
    );
  });

  test('rules receive npc events', () {
    // `npc_moved` is documented as rule-triggerable, so a rule must see it.
    final game = _makeGame({
      'type': 'toward_avatar',
      'requiresLineOfSight': true,
    });
    final levelJson = _levelJson(avatar: [0, 1], watcher: [3, 1]);
    (levelJson['board'] as Map<String, dynamic>)['layers'] = {
      ...(levelJson['board'] as Map<String, dynamic>)['layers']
          as Map<String, dynamic>,
      'objects': {
        'format': 'sparse',
        'entries': [
          {
            'position': [4, 2],
            'kind': 'flag'
          },
        ],
      },
    };
    levelJson['rules'] = [
      {
        'id': 'clear_flag_when_watcher_walks',
        'on': 'npc_moved',
        'then': [
          {
            'destroy': {
              'position': [4, 2],
              'layer': 'objects'
            },
          },
        ],
      },
    ];
    final engine = _engineFor(game, levelJson);

    expect(engine.state.board.getEntity('objects', Position(4, 2)), isNotNull);

    final result = engine.executeTurn(_move('right'));

    expect(result.events.any((e) => e.type == 'npc_moved'), isTrue);
    expect(
      engine.state.board.getEntity('objects', Position(4, 2)),
      isNull,
      reason:
          'the rule never fired, so NPC events are still invisible to rules',
    );
  });

  test('NPC moves produce actor-layer entity motion', () {
    final game = _makeGame({
      'type': 'toward_avatar',
      'requiresLineOfSight': true,
    });
    final engine = _engineFor(
      game,
      _levelJson(avatar: [0, 1], watcher: [3, 1]),
    );

    final result = engine.executeTurn(_move('right'));
    final animations =
        result.animations.where((step) => step.type == 'entity_move').toList();

    expect(animations, hasLength(1));
    expect(animations.single.entityKind, 'watcher');
    expect(animations.single.extra['layer'], 'actors');
    expect(animations.single.extra['from'], [3, 1]);
    expect(animations.single.position, const Position(2, 1));
    expect(animations.single.durationMs, 130);
  });

  group('lethalContact governs every behavior', () {
    GameDefinition patrolGame({required bool lethal}) {
      final data = {
        'id': 'com.gridponder.test_follower_npcs_patrol',
        'layers': [
          {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
          {'id': 'actors', 'occupancy': 'zero_or_one'},
        ],
        'entityKinds': {
          'empty': {
            'layer': 'ground',
            'tags': ['walkable'],
            'symbol': '.',
          },
          'sentry': {
            'layer': 'actors',
            'tags': ['npc'],
            'symbol': 'S',
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
          {'id': 'navigation', 'type': 'avatar_navigation', 'config': {}},
          {
            'id': 'npcs',
            'type': 'follower_npcs',
            'config': {
              'behaviors': {
                'march': {'type': 'patrol', 'lethalContact': lethal},
              },
            },
          },
        ],
      };
      return GameDefinition.fromJson(data, id: 'test_follower_npcs_patrol');
    }

    Map<String, dynamic> patrolLevel() => {
          'id': 'test_level',
          'board': {
            'size': [5, 1],
            'layers': {
              'actors': {
                'format': 'sparse',
                'entries': [
                  {
                    'position': [2, 0],
                    'kind': 'sentry',
                    'behavior': 'march',
                    'facing': 'left',
                  },
                ],
              },
            },
          },
          'state': {
            'avatar': {
              'enabled': true,
              'position': [0, 0]
            },
          },
          'goals': <dynamic>[],
          'loseConditions': [
            {
              'type': 'variable_threshold',
              'config': {
                'variable': 'caught',
                'target': 1,
                'comparison': 'gte',
              },
            },
          ],
        };

    int? sentryX(TurnEngine engine) {
      for (final entry in engine.state.board.layers['actors']!.entries()) {
        if (entry.value.kind == 'sentry') return entry.key.x;
      }
      return null;
    }

    test('a patrol kills on contact when it opts in', () {
      final engine = _engineFor(patrolGame(lethal: true), patrolLevel());

      engine.executeTurn(_move('up')); // blocked; avatar holds (0,0)
      expect(sentryX(engine), 1);

      final result = engine.executeTurn(_move('up'));

      expect(result.events.any((e) => e.type == 'avatar_caught'), isTrue);
      expect(result.isLost, isTrue);
      expect(result.loseReason, 'variable_threshold:caught');
    });

    test('a harmless patrol bounces off the avatar', () {
      final engine = _engineFor(patrolGame(lethal: false), patrolLevel());

      engine.executeTurn(_move('up'));
      expect(sentryX(engine), 1);

      final result = engine.executeTurn(_move('up'));

      expect(result.isLost, isFalse);
      expect(result.events.any((e) => e.type == 'avatar_caught'), isFalse);
      // The avatar blocks it, so patrol reverses instead of walking through.
      expect(sentryX(engine), 2);
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

  group('follower_npcs shafts', () {
    test('unshafted board is unchanged by the shaft feature', () {
      // Guard for Firebreak and Blind Spot: no shaft params -> today's path.
      // (4,0) faces a wall at (5,0) and reverses; (1,2) is clear and walks on,
      // entirely unaffected by the other machine's wall.
      final engine = _engineFor(
        _shaftGame(),
        _shaftLevelJson(
          [(4, 0, 'walker', 'right', null), (1, 2, 'walker', 'right', null)],
          walls: [(5, 0)],
        ),
      );

      _beat(engine);

      expect(_machinePositions(engine), [(2, 2), (3, 0)]);
      expect(_facingAt(engine, 3, 0), 'left');
      expect(_facingAt(engine, 2, 2), 'right');
    });

    test('shafted pair steps in lockstep', () {
      final engine = _engineFor(
        _shaftGame(),
        _shaftLevelJson([
          (1, 0, 'walker', 'right', 'a'),
          (1, 2, 'walker', 'right', 'a'),
        ]),
      );

      _beat(engine);

      expect(_machinePositions(engine), [(2, 0), (2, 2)]);
    });

    test('blocking one member reverses the whole train', () {
      // The remote turn: (1,2)'s own path is clear all the way to the east
      // edge. It reverses anyway, because the shaft carries (4,0)'s wall to it.
      final engine = _engineFor(
        _shaftGame(),
        _shaftLevelJson(
          [(4, 0, 'walker', 'right', 'a'), (1, 2, 'walker', 'right', 'a')],
          walls: [(5, 0)],
        ),
      );

      _beat(engine);

      expect(_machinePositions(engine), [(0, 2), (3, 0)]);
      expect(_facingAt(engine, 3, 0), 'left');
      expect(_facingAt(engine, 0, 2), 'left');
    });

    test('train blocked both ways freezes and keeps facings', () {
      final engine = _engineFor(
        _shaftGame(),
        _shaftLevelJson(
          [(4, 0, 'walker', 'right', 'a'), (1, 2, 'walker', 'right', 'a')],
          walls: [(5, 0), (3, 0)],
        ),
      );

      _beat(engine);

      expect(_machinePositions(engine), [(1, 2), (4, 0)]);
      expect(_facingAt(engine, 4, 0), 'right');
      expect(_facingAt(engine, 1, 2), 'right');
    });

    test("load settle records each train's size", () {
      final engine = _engineFor(
        _shaftGame(configExtra: {'shaftSeizeOnLoss': true}),
        _shaftLevelJson([
          (1, 0, 'walker', 'right', 'a'),
          (1, 2, 'walker', 'right', 'a'),
          (6, 3, 'walker', 'up', 'b'),
        ]),
      );

      expect(engine.state.variables['shaft_a_size'], 2);
      expect(engine.state.variables['shaft_b_size'], 1);
    });

    test('train seizes permanently when a member is destroyed', () {
      final engine = _engineFor(
        _shaftGame(configExtra: {'shaftSeizeOnLoss': true}),
        _shaftLevelJson([
          (1, 0, 'walker', 'right', 'a'),
          (1, 2, 'walker', 'right', 'a'),
        ]),
      );

      _beat(engine);
      expect(_machinePositions(engine), [(2, 0), (2, 2)]);

      // Something else removes one member — a leaf opening under it, in the
      // pack.
      engine.state.board.setEntity('actors', const Position(2, 0), null);

      for (var i = 0; i < 4; i++) {
        _beat(engine);
      }
      expect(
        _machinePositions(engine),
        [(2, 2)],
        reason: 'survivor must be frozen forever',
      );
    });

    test('seizure is off by default', () {
      final engine = _engineFor(
        _shaftGame(),
        _shaftLevelJson([
          (1, 0, 'walker', 'right', 'a'),
          (1, 2, 'walker', 'right', 'a'),
        ]),
      );

      engine.state.board.setEntity('actors', const Position(1, 0), null);
      _beat(engine);

      expect(
        _machinePositions(engine),
        [(2, 2)],
        reason: 'survivor keeps running',
      );
    });

    test('seizure flag is read strictly', () {
      // Matches the `cycle` precedent in coupled_actors: only true enables it.
      final engine = _engineFor(
        _shaftGame(configExtra: {'shaftSeizeOnLoss': 1}),
        _shaftLevelJson([
          (1, 0, 'walker', 'right', 'a'),
          (1, 2, 'walker', 'right', 'a'),
        ]),
      );

      engine.state.board.setEntity('actors', const Position(1, 0), null);
      _beat(engine);

      expect(_machinePositions(engine), [(2, 2)]);
    });

    // -- ratio shafts (geared trains) -----------------------------------------
    //
    // A train may mix frequencies. Each member runs on its own beat; only the
    // members whose gate opens are probed and step, but a reversal turns the
    // WHOLE train, because facing is train-level state. Parity mirror of the
    // ratio tests in engines/python/test_follower_npcs.py.
    //
    // turnCount starts at 0 and is read BEFORE it increments, so a frequency-2
    // member is active on the 1st, 3rd, 5th beat and idle on the 2nd and 4th.

    const geared = {
      'walker': {
        'type': 'patrol',
        'lethalContact': false,
        'solidBlocking': true,
      },
      'slow': {
        'type': 'patrol',
        'lethalContact': false,
        'solidBlocking': true,
        'frequency': 2,
      },
    };

    test('mixed frequency train loads', () {
      // The whole point of the arc: a geared train is no longer rejected.
      _engineFor(
        _shaftGame(behaviors: geared),
        _shaftLevelJson([
          (1, 0, 'walker', 'right', 'a'),
          (1, 2, 'slow', 'right', 'a'),
        ]),
      );
    });

    test('geared members step at their own rates', () {
      final engine = _engineFor(
        _shaftGame(behaviors: geared),
        _shaftLevelJson([
          (1, 0, 'walker', 'right', 'a'),
          (1, 2, 'slow', 'right', 'a'),
        ]),
      );

      _beat(engine);
      expect(_machinePositions(engine), [(2, 0), (2, 2)]);

      // The slow member is off-beat and stays put; the fast one walks on alone.
      _beat(engine);
      expect(_machinePositions(engine), [(2, 2), (3, 0)]);

      _beat(engine);
      expect(_machinePositions(engine), [(3, 2), (4, 0)]);
    });

    test('reversal turns the member that did not step', () {
      // The arc's core fact: an off-beat member turns without moving.
      // Beat 2 (turnCount 1): only the fast member is active. It faces the wall
      // at (5,0), so the train reverses — and the slow member at (2,2), which
      // took no step at all this beat, is now facing left.
      final engine = _engineFor(
        _shaftGame(behaviors: geared),
        _shaftLevelJson(
          [(3, 0, 'walker', 'right', 'a'), (1, 2, 'slow', 'right', 'a')],
          walls: [(5, 0)],
        ),
      );

      _beat(engine);
      expect(_machinePositions(engine), [(2, 2), (4, 0)]);

      _beat(engine);
      expect(_machinePositions(engine), [(2, 2), (3, 0)]);
      expect(_facingAt(engine, 3, 0), 'left');
      expect(_facingAt(engine, 2, 2), 'left');
    });

    test('the slow wheel steers the fast one', () {
      // A geared train: the member you cannot reach turns
      // the member you can, on a beat the fast one had every reason to walk on.
      final engine = _engineFor(
        _shaftGame(behaviors: geared),
        _shaftLevelJson(
          [(1, 0, 'walker', 'right', 'a'), (3, 2, 'slow', 'right', 'a')],
          walls: [(5, 2)],
        ),
      );

      _beat(engine); // turnCount 0: both step east
      expect(_machinePositions(engine), [(2, 0), (4, 2)]);

      _beat(engine); // turnCount 1: fast alone, clear road
      expect(_machinePositions(engine), [(3, 0), (4, 2)]);

      _beat(engine); // turnCount 2: slow hits (5,2) and drags the fast one back
      expect(_machinePositions(engine), [(2, 0), (3, 2)]);
      expect(_facingAt(engine, 2, 0), 'left');
      expect(_facingAt(engine, 3, 2), 'left');
    });

    test('all members off beat is a noop not a freeze', () {
      // An empty active set must emit nothing and turn nothing. Both members
      // are frequency 2, so turnCount 1 has no active member at all.
      final engine = _engineFor(
        _shaftGame(behaviors: geared),
        _shaftLevelJson([
          (1, 0, 'slow', 'right', 'a'),
          (1, 2, 'slow', 'right', 'a'),
        ]),
      );

      _beat(engine);
      expect(_machinePositions(engine), [(2, 0), (2, 2)]);

      // Facings must survive untouched: a no-op is not a blocked train.
      _beat(engine);
      expect(_machinePositions(engine), [(2, 0), (2, 2)]);
      expect(_facingAt(engine, 2, 0), 'right');
      expect(_facingAt(engine, 2, 2), 'right');
    });

    test('same frequency train is unchanged', () {
      // Regression guard: an ungeared train still moves in lockstep at its own
      // rate, on exactly the beats it did before the ratio change.
      final engine = _engineFor(
        _shaftGame(behaviors: geared),
        _shaftLevelJson([
          (1, 0, 'slow', 'right', 'a'),
          (1, 2, 'slow', 'right', 'a'),
        ]),
      );

      _beat(engine);
      expect(_machinePositions(engine), [(2, 0), (2, 2)]);
      _beat(engine);
      expect(_machinePositions(engine), [(2, 0), (2, 2)]);
      _beat(engine);
      expect(_machinePositions(engine), [(3, 0), (3, 2)]);
    });

    test('zero frequency member is rejected', () {
      _expectRejects(
        _shaftGame(
          behaviors: {
            'walker': {
              'type': 'patrol',
              'lethalContact': false,
              'solidBlocking': true,
            },
            'stuck': {
              'type': 'patrol',
              'lethalContact': false,
              'solidBlocking': true,
              'frequency': 0,
            },
          },
        ),
        _shaftLevelJson([
          (1, 0, 'walker', 'right', 'a'),
          (1, 2, 'stuck', 'right', 'a'),
        ]),
        'positive integer',
      );
    });

    test('members crossing tracks never share a cell', () {
      // (2,0) walks east along row 0; (4,2) walks north up column 4. On the
      // second beat both want (4,0). Before this was fixed they both got it,
      // the second write erased the first, and the train silently lost a member
      // — which then read as a seizure, because the size recorded at load no
      // longer matched. Both machines must still be on the board.
      final engine = _engineFor(
        _shaftGame(),
        _shaftLevelJson([
          (2, 0, 'walker', 'right', 'a'),
          (4, 2, 'walker', 'up', 'a'),
        ]),
      );

      for (var i = 0; i < 3; i++) {
        _beat(engine);
        expect(_machinePositions(engine), hasLength(2));
      }
    });

    test('non patrol member is rejected at load', () {
      _expectRejects(
        _shaftGame(
          behaviors: {
            'walker': {'type': 'patrol', 'lethalContact': false},
            'ringer': {'type': 'clockwise', 'lethalContact': false},
          },
        ),
        _shaftLevelJson([
          (1, 0, 'walker', 'right', 'a'),
          (1, 2, 'ringer', 'right', 'a'),
        ]),
        'patrol',
      );
    });

    test('members sharing a traversal line are rejected at load', () {
      // Self-blocking would make lockstep meaningless: the train jams at t=0.
      _expectRejects(
        _shaftGame(),
        _shaftLevelJson([
          (1, 0, 'walker', 'right', 'a'),
          (4, 0, 'walker', 'right', 'a'),
        ]),
        'traversal',
      );
    });
  });
}

Position? _watcherPosition(TurnEngine engine) {
  for (final entry in engine.state.board.layers['actors']!.entries()) {
    if (entry.value.kind == 'watcher') return entry.key;
  }
  return null;
}
