// Parity mirror of engines/python/test_coupled_actors.py — behavioural cases
// for the `coupled_actors` system (movement + territory claiming).
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

// ---------------------------------------------------------------------------
// Movement fixtures (no territory layer, no `claim` config)
// ---------------------------------------------------------------------------

GameDefinition _makeGame() {
  final data = {
    'id': 'com.gridponder.test_coupled_actors',
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
      'wall': {
        'layer': 'ground',
        'tags': ['solid'],
        'symbol': '#',
      },
      'wei': {
        'layer': 'actors',
        'tags': ['actor'],
        'symbol': 'W',
      },
      'shu': {
        'layer': 'actors',
        'tags': ['actor'],
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
      {'id': 'movement', 'type': 'coupled_actors', 'config': {}},
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_coupled_actors');
}

/// actors: list of [x, y, kind]; walls: list of [x, y] ground wall cells.
Map<String, dynamic> _makeLevel({
  required List<List<dynamic>> actors,
  List<List<int>> walls = const [],
  int width = 6,
}) {
  return {
    'id': 'test_level',
    'board': {
      'size': [width, 1],
      'layers': {
        'ground': {
          'format': 'sparse',
          'entries': [
            for (final w in walls)
              {
                'position': [w[0], w[1]],
                'kind': 'wall'
              }
          ],
        },
        'actors': {
          'format': 'sparse',
          'entries': [
            for (final a in actors)
              {
                'position': [a[0], a[1]],
                'kind': a[2]
              }
          ],
        },
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

Position? _actorPos(TurnEngine engine, String kind) {
  for (final entry in engine.state.board.layers['actors']!.entries()) {
    if (entry.value.kind == kind) return entry.key;
  }
  return null;
}

List<GameEvent> _actorEvents(TurnResult result) =>
    result.events.where((e) => e.type.startsWith('actor_')).toList();

// ---------------------------------------------------------------------------
// Claiming fixtures (territory layer + `claim` system config)
// ---------------------------------------------------------------------------

GameDefinition _makeClaimGame() {
  final data = {
    'id': 'com.gridponder.test_coupled_actors_claim',
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
      'wei': {
        'layer': 'actors',
        'tags': ['actor'],
        'symbol': 'W',
      },
      'shu': {
        'layer': 'actors',
        'tags': ['actor'],
        'symbol': 'S',
      },
      'terr_wei': {
        'layer': 'territory',
        'tags': ['territory'],
        'symbol': '1',
      },
      'terr_shu': {
        'layer': 'territory',
        'tags': ['territory'],
        'symbol': '2',
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
        'config': {
          'claim': {
            'layer': 'territory',
            'map': {'wei': 'terr_wei', 'shu': 'terr_shu'},
          },
        },
      },
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_coupled_actors_claim');
}

Map<String, dynamic> _makeClaimLevel({
  required List<List<dynamic>> actors,
  List<List<int>> walls = const [],
  List<List<dynamic>> territory = const [],
  int width = 6,
}) {
  final level = _makeLevel(actors: actors, walls: walls, width: width);
  (level['board'] as Map<String, dynamic>)['layers']['territory'] = {
    'format': 'sparse',
    'entries': [
      for (final t in territory)
        {
          'position': [t[0], t[1]],
          'kind': t[2]
        }
    ],
  };
  return level;
}

String? _territoryKind(TurnEngine engine, Position pos) =>
    engine.state.board.getEntity('territory', pos)?.kind;

List<GameEvent> _claimEvents(TurnResult result) =>
    result.events.where((e) => e.type == 'cell_claimed').toList();

GameAction _moveRight() => GameAction('move', {'direction': 'right'});

// ---------------------------------------------------------------------------
// tape-driven stepping
// ---------------------------------------------------------------------------

/// [cycle] is intentionally `dynamic`, not `bool`: the tape config is JSON,
/// so tests probing a non-boolean value (e.g. `cycle: 1`, a JSON typo) need
/// to be able to pass one through unchanged.
GameDefinition _makeTapedGame(
  List<String> program, {
  dynamic cycle = false,
  String? indexVariable,
}) {
  final tape = <String, dynamic>{'program': program, 'cycle': cycle};
  if (indexVariable != null) tape['indexVariable'] = indexVariable;
  final data = {
    'id': 'com.gridponder.test_coupled_actors_tape',
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
      {'id': 'step', 'params': <String, dynamic>{}},
    ],
    'systems': [
      {
        'id': 'movement',
        'type': 'coupled_actors',
        'config': {
          'tape': tape,
        },
      },
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_coupled_actors_tape');
}

void _tapeTests() {
  group('tape-driven stepping', () {
    test('the tape direction overrides the action direction', () {
      final engine = _engineFor(
        _makeTapedGame(['right']),
        _makeLevel(actors: [
          [0, 0, 'wei']
        ]),
      );
      engine.executeTurn(GameAction('move', {'direction': 'left'}));
      expect(_actorPos(engine, 'wei'), const Position(1, 0));
      expect(engine.state.variables['tapeIndex'], 1);
    });

    test('the tape advances on a param-less action', () {
      final engine = _engineFor(
        _makeTapedGame(['right', 'right']),
        _makeLevel(actors: [
          [0, 0, 'wei']
        ]),
      );
      engine.executeTurn(GameAction('step'));
      engine.executeTurn(GameAction('step'));
      expect(_actorPos(engine, 'wei'), const Position(2, 0));
      expect(engine.state.variables['tapeIndex'], 2);
    });

    test('a finite tape stops when exhausted', () {
      final engine = _engineFor(
        _makeTapedGame(['right']),
        _makeLevel(actors: [
          [0, 0, 'wei']
        ]),
      );
      engine.executeTurn(GameAction('step'));
      engine.executeTurn(GameAction('step'));
      expect(_actorPos(engine, 'wei'), const Position(1, 0));
      expect(engine.state.variables['tapeIndex'], 1);
    });

    test('a cyclic tape wraps and keeps the index bounded', () {
      final engine = _engineFor(
        _makeTapedGame(['right', 'left'], cycle: true),
        _makeLevel(actors: [
          [0, 0, 'wei']
        ]),
      );
      for (var i = 0; i < 5; i++) {
        engine.executeTurn(GameAction('step'));
      }
      expect(_actorPos(engine, 'wei'), const Position(1, 0));
      expect(engine.state.variables['tapeIndex'], 1);
    });

    test('a negative tape index clamps to zero', () {
      // A negative stored index (e.g. left behind by a rewind rule using
      // increment_variable with a negative amount) must clamp to 0 rather
      // than reaching `program[-1]`, which throws a RangeError in Dart —
      // Python's negative indexing would otherwise silently wrap instead, so
      // both engines must agree on clamping.
      final engine = _engineFor(
        _makeTapedGame(['right', 'down', 'left']),
        _makeLevel(actors: [
          [2, 0, 'wei']
        ]),
      );
      engine.state.variables['tapeIndex'] = -1;
      engine.executeTurn(GameAction('step'));
      expect(_actorPos(engine, 'wei'), const Position(3, 0),
          reason: "a negative stored index must clamp to 0 (program[0] == "
              "'right')");
      expect(engine.state.variables['tapeIndex'], 1);
    });

    test('a non-boolean cycle value does not cycle', () {
      // "cycle": 1 is an ordinary JSON typo for true, not the real thing —
      // the tape must treat only the boolean true as cycling, so a
      // truthy-but-not-true value halts the tape exactly like cycle: false
      // would.
      final engine = _engineFor(
        _makeTapedGame(['right'], cycle: 1),
        _makeLevel(actors: [
          [0, 0, 'wei']
        ]),
      );
      engine.executeTurn(GameAction('step'));
      engine.executeTurn(GameAction('step'));
      expect(_actorPos(engine, 'wei'), const Position(1, 0),
          reason: 'a non-boolean cycle value must not cycle — the tape '
              'should have stopped after the first step');
      expect(engine.state.variables['tapeIndex'], 1);
    });

    test('the tape honours a custom index variable name', () {
      // Multi-machine packs need a distinct indexVariable per tape; the
      // default "tapeIndex" name must not be hardcoded anywhere on the read
      // or write path.
      final engine = _engineFor(
        _makeTapedGame(['right', 'right'], indexVariable: 'beltIndex'),
        _makeLevel(actors: [
          [0, 0, 'wei']
        ]),
      );
      engine.executeTurn(GameAction('step'));
      expect(engine.state.variables.containsKey('tapeIndex'), isFalse,
          reason: 'a custom indexVariable must not also write the default '
              'name');
      expect(engine.state.variables['beltIndex'], 1);
      engine.executeTurn(GameAction('step'));
      expect(_actorPos(engine, 'wei'), const Position(2, 0));
      expect(engine.state.variables['beltIndex'], 2);
    });
  });
}

// ---------------------------------------------------------------------------
// directionTransforms (DSL 0.8) — per-actor direction mapping
// ---------------------------------------------------------------------------

/// A fresh GameDefinition whose `movement` system carries `directionTransforms`.
/// Built per-call so tests can't leak config into each other.
GameDefinition _makeGameWithTransforms(Map<String, String> transforms) {
  final data = {
    'id': 'com.gridponder.test_coupled_actors',
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
      'wall': {
        'layer': 'ground',
        'tags': ['solid'],
        'symbol': '#',
      },
      'wei': {
        'layer': 'actors',
        'tags': ['actor'],
        'symbol': 'W',
      },
      'shu': {
        'layer': 'actors',
        'tags': ['actor'],
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
      {
        'id': 'movement',
        'type': 'coupled_actors',
        'config': {'directionTransforms': transforms},
      },
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_coupled_actors');
}

// ---------------------------------------------------------------------------
// Excavation fixtures (`excavate` system config)
// ---------------------------------------------------------------------------

const _defaultExcavate = {
  'diggableTag': 'diggable',
  'clearedKind': 'empty',
  'backfillKind': 'rubble',
};

/// A coupled_actors game whose ground has three solid kinds: `rock` is
/// diggable, `rubble` (the spoil) and `bedrock` are not. Pass null for a game
/// with no excavate block at all.
GameDefinition _makeExcavateGame(Map<String, dynamic>? excavate) {
  final data = {
    'id': 'com.gridponder.test_excavate',
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
      'rock': {
        'layer': 'ground',
        'tags': ['solid', 'diggable'],
        'symbol': '#',
      },
      'rubble': {
        'layer': 'ground',
        'tags': ['solid'],
        'symbol': '%',
      },
      'bedrock': {
        'layer': 'ground',
        'tags': ['solid'],
        'symbol': 'X',
      },
      'wei': {
        'layer': 'actors',
        'tags': ['actor'],
        'symbol': 'W',
      },
      'shu': {
        'layer': 'actors',
        'tags': ['actor'],
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
      {
        'id': 'movement',
        'type': 'coupled_actors',
        'config': excavate == null ? {} : {'excavate': excavate},
      },
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_excavate');
}

/// actors: list of [x, y, kind]; ground: list of [x, y, kind] for non-default
/// cells.
Map<String, dynamic> _makeTerrainLevel({
  required List<List<dynamic>> actors,
  List<List<dynamic>> ground = const [],
  int width = 6,
}) {
  return {
    'id': 'test_level',
    'board': {
      'size': [width, 1],
      'layers': {
        'ground': {
          'format': 'sparse',
          'entries': [
            for (final g in ground)
              {
                'position': [g[0], g[1]],
                'kind': g[2],
              }
          ],
        },
        'actors': {
          'format': 'sparse',
          'entries': [
            for (final a in actors)
              {
                'position': [a[0], a[1]],
                'kind': a[2],
              }
          ],
        },
      },
    },
    'state': {},
    'goals': [],
    'loseConditions': [],
  };
}

String? _groundKind(TurnEngine engine, Position pos) =>
    engine.state.board.getEntity('ground', pos)?.kind;

List<GameEvent> _transformEvents(TurnResult result) =>
    result.events.where((e) => e.type == 'cell_transformed').toList();

/// Parity mirror of the excavation cases in
/// engines/python/test_coupled_actors.py.
void _excavateTests() {
  group('coupled_actors — excavate', () {
    test('cuts rock and backfills the vacated cell behind a lone excavator',
        () {
      final engine = _engineFor(
        _makeExcavateGame(_defaultExcavate),
        _makeTerrainLevel(actors: [
          [1, 0, 'wei']
        ], ground: [
          [2, 0, 'rock']
        ]),
      );

      final result = engine.executeTurn(_moveRight());

      expect(result.accepted, isTrue);
      expect(_actorPos(engine, 'wei'), equals(const Position(2, 0)),
          reason: 'wei should take the cell it cut');
      expect(_groundKind(engine, const Position(2, 0)), equals('empty'),
          reason: 'the cut cell should be cleared');
      expect(_groundKind(engine, const Position(1, 0)), equals('rubble'),
          reason: 'the vacated cell should be backfilled');

      final events = _transformEvents(result);
      expect(events.length, 2, reason: 'expected a cut and a backfill event');
      expect(events[0].payload['position'], equals(const Position(2, 0)));
      expect(events[0].payload['fromKind'], equals('rock'));
      expect(events[0].payload['toKind'], equals('empty'));
      expect(events[1].payload['position'], equals(const Position(1, 0)));
      expect(events[1].payload['toKind'], equals('rubble'));
    });

    test('a trailing partner hauls the spoil out and the corridor stays open',
        () {
      final engine = _engineFor(
        _makeExcavateGame(_defaultExcavate),
        _makeTerrainLevel(actors: [
          [1, 0, 'wei'],
          [2, 0, 'shu']
        ], ground: [
          [3, 0, 'rock']
        ]),
      );

      final result = engine.executeTurn(_moveRight());

      expect(_actorPos(engine, 'shu'), equals(const Position(3, 0)),
          reason: 'shu (front) should cut and advance');
      expect(_actorPos(engine, 'wei'), equals(const Position(2, 0)),
          reason: "wei should train into shu's vacated cell");
      expect(_groundKind(engine, const Position(2, 0)), equals('empty'),
          reason: 'wei ended the turn there, so the spoil is hauled out');
      expect(_transformEvents(result).length, 1,
          reason: 'only the cut should transform a cell');

      final hauled =
          result.events.where((e) => e.type == 'spoil_hauled').toList();
      expect(hauled.length, 1,
          reason: 'the skipped backfill must announce itself');
      expect(hauled.single.payload['position'], equals(const Position(2, 0)));
      expect(hauled.single.payload['layer'], equals('ground'));
    });

    test('backfill and haul are mutually exclusive', () {
      // Exactly one of the two must fire per pending cell — a game reacting to
      // both would double-count the same excavation.
      for (final (actors, expectHaul) in [
        (
          [
            [1, 0, 'wei'],
            [2, 0, 'shu']
          ],
          true
        ), // trained: hauled
        (
          [
            [0, 0, 'wei'],
            [2, 0, 'shu']
          ],
          false
        ), // spread: backfilled
      ]) {
        final engine = _engineFor(
          _makeExcavateGame(_defaultExcavate),
          _makeTerrainLevel(actors: actors, ground: [
            [3, 0, 'rock']
          ]),
        );
        final result = engine.executeTurn(_moveRight());
        final hauled = result.events.where((e) => e.type == 'spoil_hauled');
        final filled = _transformEvents(result)
            .where((e) => e.payload['toKind'] == 'rubble');
        expect(hauled.isNotEmpty, expectHaul, reason: 'haul for $actors');
        expect(filled.isNotEmpty, !expectHaul, reason: 'backfill for $actors');
      }
    });

    test('a partner one cell too far back does not haul', () {
      final engine = _engineFor(
        _makeExcavateGame(_defaultExcavate),
        _makeTerrainLevel(actors: [
          [0, 0, 'wei'],
          [2, 0, 'shu']
        ], ground: [
          [3, 0, 'rock']
        ]),
      );

      engine.executeTurn(_moveRight());

      expect(_actorPos(engine, 'wei'), equals(const Position(1, 0)),
          reason: 'wei moves, but only to (1,0)');
      expect(_groundKind(engine, const Position(2, 0)), equals('rubble'),
          reason: 'nobody ended on (2,0), so it backfills');
    });

    test('spoil is not diggable once placed, so a solo tunnel is one-way', () {
      final engine = _engineFor(
        _makeExcavateGame(_defaultExcavate),
        _makeTerrainLevel(actors: [
          [1, 0, 'wei']
        ], ground: [
          [2, 0, 'rock']
        ]),
      );

      engine.executeTurn(_moveRight());
      final result = engine.executeTurn(GameAction('move', {
        'direction': 'left',
      }));

      expect(_actorPos(engine, 'wei'), equals(const Position(2, 0)),
          reason: 'wei must be blocked by its own spoil');
      expect(_transformEvents(result), isEmpty,
          reason: 'a blocked actor must not transform anything');
      expect(_actorEvents(result).map((e) => e.type).toList(),
          equals(['actor_blocked']));
    });

    test('an undiggable solid still blocks', () {
      final engine = _engineFor(
        _makeExcavateGame(_defaultExcavate),
        _makeTerrainLevel(actors: [
          [1, 0, 'wei']
        ], ground: [
          [2, 0, 'bedrock']
        ]),
      );

      final result = engine.executeTurn(_moveRight());

      expect(_actorPos(engine, 'wei'), equals(const Position(1, 0)),
          reason: 'bedrock must block');
      expect(_transformEvents(result), isEmpty,
          reason: 'bedrock must not be transformed');
    });

    test('an ordinary move never backfills', () {
      final engine = _engineFor(
        _makeExcavateGame(_defaultExcavate),
        _makeTerrainLevel(actors: [
          [1, 0, 'wei']
        ]),
      );

      final result = engine.executeTurn(_moveRight());

      expect(_actorPos(engine, 'wei'), equals(const Position(2, 0)));
      expect(_groundKind(engine, const Position(1, 0)), equals('empty'),
          reason: 'an ordinary move must leave the vacated cell open');
      expect(_transformEvents(result), isEmpty);
    });

    test('without an excavate block, diggable rock still blocks', () {
      final engine = _engineFor(
        _makeExcavateGame(null),
        _makeTerrainLevel(actors: [
          [1, 0, 'wei']
        ], ground: [
          [2, 0, 'rock']
        ]),
      );

      engine.executeTurn(_moveRight());

      expect(_actorPos(engine, 'wei'), equals(const Position(1, 0)),
          reason: 'excavation is opt-in per game; the tag alone does nothing');
    });

    test('an excavate block without clearedKind is inert', () {
      // Tolerance contract: both engines must treat a malformed block as
      // absent rather than each inventing their own fallback.
      final engine = _engineFor(
        _makeExcavateGame({
          'diggableTag': 'diggable',
          'backfillKind': 'rubble',
        }),
        _makeTerrainLevel(actors: [
          [1, 0, 'wei']
        ], ground: [
          [2, 0, 'rock']
        ]),
      );

      final result = engine.executeTurn(_moveRight());

      expect(_actorPos(engine, 'wei'), equals(const Position(1, 0)),
          reason: 'a malformed excavate block must be inert');
      expect(_transformEvents(result), isEmpty);
    });

    test('an omitted backfillKind leaves an open corridor', () {
      final engine = _engineFor(
        _makeExcavateGame({
          'diggableTag': 'diggable',
          'clearedKind': 'empty',
        }),
        _makeTerrainLevel(actors: [
          [1, 0, 'wei']
        ], ground: [
          [2, 0, 'rock']
        ]),
      );

      final result = engine.executeTurn(_moveRight());

      expect(_actorPos(engine, 'wei'), equals(const Position(2, 0)));
      expect(_groundKind(engine, const Position(1, 0)), equals('empty'),
          reason: 'no backfillKind means no spoil');
      expect(_transformEvents(result).length, 1,
          reason: 'only the cut should fire');
    });
  });
}

void main() {
  _tapeTests();
  _excavateTests();

  group('coupled_actors — directionTransforms', () {
    test('identity transforms match legacy order (compatibility guarantee)',
        () {
      // An explicit all-identity config must behave exactly like no config at
      // all — one bucket, unchanged front-first sort.
      final results = <Map<String, Position?>>[];
      for (final game in [
        _makeGame(),
        _makeGameWithTransforms({'wei': 'identity', 'shu': 'identity'}),
      ]) {
        final engine = _engineFor(
            game,
            _makeLevel(actors: [
              [1, 0, 'wei'],
              [2, 0, 'shu'],
            ]));
        engine.executeTurn(_moveRight());
        results.add({
          'wei': _actorPos(engine, 'wei'),
          'shu': _actorPos(engine, 'shu'),
        });
      }

      expect(results[0]['wei'], equals(results[1]['wei']),
          reason: 'identity transforms diverged from legacy behaviour (wei)');
      expect(results[0]['shu'], equals(results[1]['shu']),
          reason: 'identity transforms diverged from legacy behaviour (shu)');
    });

    test('invert moves actor opposite', () {
      // Starts are 1 and 4 so the two never contend for the same destination —
      // they converge to 2 and 3, staying distinct.
      final game = _makeGameWithTransforms({'shu': 'invert'});
      final engine = _engineFor(
          game,
          _makeLevel(actors: [
            [1, 0, 'wei'],
            [4, 0, 'shu'],
          ]));

      engine.executeTurn(_moveRight());

      expect(_actorPos(engine, 'wei'), equals(const Position(2, 0)),
          reason: 'wei should step right to (2,0)');
      expect(_actorPos(engine, 'shu'), equals(const Position(3, 0)),
          reason: 'shu (inverted) should step left to (3,0)');
    });

    test('mutual swap blocks both actors', () {
      // wei at 2 moving right, shu at 3 inverted moving left. Each targets the
      // other's occupied cell, so both stay put — falls out of the live
      // `occupied` set, no special case needed.
      final game = _makeGameWithTransforms({'shu': 'invert'});
      final engine = _engineFor(
          game,
          _makeLevel(actors: [
            [2, 0, 'wei'],
            [3, 0, 'shu'],
          ]));

      engine.executeTurn(_moveRight());

      expect(_actorPos(engine, 'wei'), equals(const Position(2, 0)),
          reason: 'wei must stay at (2,0) in a mutual swap');
      expect(_actorPos(engine, 'shu'), equals(const Position(3, 0)),
          reason: 'shu must stay at (3,0) in a mutual swap');
    });
  });

  group('coupled_actors — movement', () {
    test('open move shifts and trains both actors', () {
      final game = _makeGame();
      final level = _makeLevel(actors: [
        [1, 0, 'wei'],
        [2, 0, 'shu'],
      ]);
      final engine = _engineFor(game, level);

      final result = engine.executeTurn(_moveRight());

      expect(result.accepted, isTrue, reason: 'move action should be accepted');
      expect(_actorPos(engine, 'shu'), equals(const Position(3, 0)),
          reason: 'shu (front) should shift to (3,0)');
      expect(_actorPos(engine, 'wei'), equals(const Position(2, 0)),
          reason: "wei (trailing) should train into shu's vacated cell (2,0)");

      final events = _actorEvents(result);
      final types = events.map((e) => e.type).toList();
      expect(
          types,
          equals(
              ['actor_moved', 'actor_entered', 'actor_moved', 'actor_entered']),
          reason: 'expected moved/entered pairs, front-first');
      expect(events[0]['kind'], equals('shu'),
          reason: 'front actor (shu) must resolve before trailing actor (wei)');
      expect(events[2]['kind'], equals('wei'));
      expect(events[0]['fromPosition'], equals(const Position(2, 0)));
      expect(events[0]['position'], equals(const Position(3, 0)));
      expect(events[2]['fromPosition'], equals(const Position(1, 0)));
      expect(events[2]['position'], equals(const Position(2, 0)));
    });

    test('actor moves produce actor-layer entity_move animations', () {
      final game = _makeGame();
      final level = _makeLevel(actors: [
        [1, 0, 'wei'],
        [2, 0, 'shu'],
      ]);
      final engine = _engineFor(game, level);

      final result = engine.executeTurn(_moveRight());

      final animations = result.animations
          .where((step) => step.type == 'entity_move')
          .toList();
      expect(animations.length, equals(2));
      expect(
        animations.map((step) => step.entityKind).toSet(),
        equals({'wei', 'shu'}),
      );
      expect(
        animations.every((step) => step.extra['layer'] == 'actors'),
        isTrue,
      );
      expect(animations.first.durationMs, equals(130));
    });

    test('wall blocks one actor while other moves freely', () {
      final game = _makeGame();
      // wei is far from the wall and moves freely; shu is blocked by a wall.
      final level = _makeLevel(actors: [
        [0, 0, 'wei'],
        [2, 0, 'shu'],
      ], walls: [
        [3, 0]
      ]);
      final engine = _engineFor(game, level);

      final result = engine.executeTurn(_moveRight());

      expect(result.accepted, isTrue);
      expect(_actorPos(engine, 'wei'), equals(const Position(1, 0)),
          reason: 'wei should move freely to (1,0)');
      expect(_actorPos(engine, 'shu'), equals(const Position(2, 0)),
          reason: 'shu should stay at (2,0) (wall ahead)');

      final events = _actorEvents(result);
      final blocked = events.where((e) => e.type == 'actor_blocked').toList();
      final moved = events.where((e) => e.type == 'actor_moved').toList();
      expect(blocked.length, equals(1));
      expect(blocked[0]['kind'], equals('shu'));
      expect(blocked[0]['position'], equals(const Position(2, 0)));
      expect(moved.length, equals(1));
      expect(moved[0]['kind'], equals('wei'));
    });

    test('wall blocks front actor and traps trailing actor', () {
      final game = _makeGame();
      final level = _makeLevel(actors: [
        [2, 0, 'wei'],
        [3, 0, 'shu'],
      ], walls: [
        [4, 0]
      ]);
      final engine = _engineFor(game, level);

      final result = engine.executeTurn(_moveRight());

      expect(result.accepted, isTrue);
      expect(_actorPos(engine, 'shu'), equals(const Position(3, 0)),
          reason: 'shu (front) should stay at (3,0)');
      expect(_actorPos(engine, 'wei'), equals(const Position(2, 0)),
          reason: 'wei (trailing) should stay at (2,0)');

      final events = _actorEvents(result);
      expect(events.every((e) => e.type == 'actor_blocked'), isTrue,
          reason: 'expected only actor_blocked events');
      final kinds = events.map((e) => e['kind'] as String).toSet();
      expect(kinds, equals({'wei', 'shu'}));
    });

    test('out of bounds blocks actor at the edge', () {
      final game = _makeGame();
      final level = _makeLevel(
        actors: [
          [3, 0, 'wei'],
          [4, 0, 'shu'],
        ],
        width: 5,
      );
      final engine = _engineFor(game, level);

      final result = engine.executeTurn(_moveRight());

      expect(result.accepted, isTrue);
      expect(_actorPos(engine, 'shu'), equals(const Position(4, 0)),
          reason: 'shu should stay at the edge (4,0)');
      expect(_actorPos(engine, 'wei'), equals(const Position(3, 0)),
          reason: 'wei should stay behind shu (3,0)');

      final events = _actorEvents(result);
      expect(events.length, equals(2));
      expect(events.every((e) => e.type == 'actor_blocked'), isTrue);
    });
  });

  group('coupled_actors — claiming', () {
    test('claim marks fresh destination cells for each mover', () {
      final game = _makeClaimGame();
      final level = _makeClaimLevel(actors: [
        [1, 0, 'wei'],
        [4, 0, 'shu'],
      ]);
      final engine = _engineFor(game, level);

      final result = engine.executeTurn(_moveRight());

      expect(result.accepted, isTrue);
      expect(_territoryKind(engine, const Position(2, 0)), equals('terr_wei'),
          reason: "wei's destination should be claimed for wei");
      expect(_territoryKind(engine, const Position(5, 0)), equals('terr_shu'),
          reason: "shu's destination should be claimed for shu");

      final claims = _claimEvents(result);
      expect(claims.length, equals(2));
      final byOwner = {for (final e in claims) e['ownerKind'] as String: e};
      expect(byOwner['wei']!['position'], equals(const Position(2, 0)));
      expect(byOwner['wei']!['kind'], equals('terr_wei'));
      expect(byOwner['shu']!['position'], equals(const Position(5, 0)));
      expect(byOwner['shu']!['kind'], equals('terr_shu'));
      expect(claims.every((e) => e['layer'] == 'territory'), isTrue,
          reason: "expected layer='territory' on every claim");
    });

    test('claim does not overwrite an already-owned cell', () {
      final game = _makeClaimGame();
      // (3,0) is already owned by wei's territory. shu (front actor) trains
      // onto it while wei (trailing) moves into shu's vacated, unclaimed
      // cell.
      final level = _makeClaimLevel(
        actors: [
          [1, 0, 'wei'],
          [2, 0, 'shu'],
        ],
        territory: [
          [3, 0, 'terr_wei']
        ],
      );
      final engine = _engineFor(game, level);

      final result = engine.executeTurn(_moveRight());

      expect(result.accepted, isTrue);
      expect(_actorPos(engine, 'shu'), equals(const Position(3, 0)));
      expect(_actorPos(engine, 'wei'), equals(const Position(2, 0)));

      expect(_territoryKind(engine, const Position(3, 0)), equals('terr_wei'),
          reason: 'pre-owned cell must not be overwritten by shu');
      expect(_territoryKind(engine, const Position(2, 0)), equals('terr_wei'),
          reason: "wei's fresh destination should be claimed for wei");

      final claims = _claimEvents(result);
      expect(claims.length, equals(1),
          reason:
              'expected exactly one cell_claimed event (only the fresh claim)');
      expect(claims[0]['ownerKind'], equals('wei'));
      expect(claims[0]['position'], equals(const Position(2, 0)));
      expect(claims[0]['kind'], equals('terr_wei'));
    });

    test('claim is not applied to a blocked actor', () {
      final game = _makeClaimGame();
      final level = _makeClaimLevel(actors: [
        [2, 0, 'shu']
      ], walls: [
        [3, 0]
      ]);
      final engine = _engineFor(game, level);

      final result = engine.executeTurn(_moveRight());

      expect(result.accepted, isTrue);
      expect(_actorPos(engine, 'shu'), equals(const Position(2, 0)),
          reason: 'shu should stay in place (wall ahead)');
      expect(_territoryKind(engine, const Position(2, 0)), isNull,
          reason: 'no claim should be made for a blocked actor');
      expect(_territoryKind(engine, const Position(3, 0)), isNull,
          reason: 'wall cell was never a move destination, so no claim');
      expect(_claimEvents(result), isEmpty,
          reason: 'blocked actor must not emit cell_claimed');
    });
  });
}
