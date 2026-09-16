// Parity mirror of engines/python/test_beam.py — regression coverage for
// four issues raised in review of the Mirror Laser engine PR:
//   1. Reselecting an already-aimed source must not count as an action,
//      even though `beam`'s NPC-resolution retrace runs unconditionally
//      every turn and keeps emitting beam_traced/beam_cell_revealed.
//   2. A splitter kind with no `splitterGlowKinds`/`splitterBlockedKinds`
//      configured must show no marker on its blocked side, not fall back
//      to a generic wall-hit marker as if it weren't a splitter at all.
//   3. Firing must revalidate `sourceTags` on the stored source cell, not
//      just check it's non-empty, before writing a facing param onto it.
//   4. Reflector/splitter redirects must be cardinal-only, matching the
//      Python engine's `is_cardinal` check.
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _makeGame() {
  final beamConfig = <String, dynamic>{
    'selectAction': 'tap_cell',
    'sourceLayer': 'objects',
    'sourceTags': ['beam_source'],
    'facingParam': 'facing',
    'blockingLayers': ['ground'],
    'blockingTags': ['solid'],
    'targetTags': ['goal_target'],
    'hazardTags': ['hazard'],
    'reflectors': {
      // Deliberately invalid: a reflector map may only redirect cardinally.
      'mirror_diag': {'right': 'up_left'},
    },
    'splitters': {
      // No splitterGlowKinds/splitterBlockedKinds configured for this kind
      // at all — its blocked side must still show no marker.
      'splitter_plain': {
        'right': ['right', 'down'],
      },
      // One cardinal branch, one deliberately invalid diagonal branch.
      'splitter_diag': {
        'right': ['right', 'up_left'],
      },
    },
    'hitVariable': 'beamHitTarget',
    'hazardVariable': 'beamHitHazard',
    'pathLayer': 'markers',
    'pathKind': 'seg_default',
    'blockedKinds': {
      'up': 'blocked_generic',
      'down': 'blocked_generic',
      'left': 'blocked_generic',
      'right': 'blocked_generic',
    },
    'intersectionKind': 'intersection_generic',
    'splitterIntersectionKinds': {
      'splitter_plain': 'intersection_splitter_plain',
    },
    'maxSteps': 50,
  };

  final data = {
    'id': 'com.gridponder.test_beam',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
      {'id': 'objects', 'occupancy': 'zero_or_one'},
      {'id': 'markers', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'floor': {'layer': 'ground', 'tags': ['walkable'], 'symbol': '.'},
      'wall': {'layer': 'ground', 'tags': ['solid'], 'symbol': '#'},
      'target': {'layer': 'ground', 'tags': ['goal_target'], 'symbol': 'T'},
      'mirror_diag': {
        'layer': 'ground',
        'tags': ['reflector'],
        'symbol': 'M',
      },
      'splitter_plain': {
        'layer': 'ground',
        'tags': ['divider'],
        'symbol': 'P',
      },
      'splitter_diag': {
        'layer': 'ground',
        'tags': ['divider'],
        'symbol': 'D',
      },
      'source': {
        'layer': 'objects',
        'tags': ['beam_source'],
        'symbol': 'S',
        'params': {
          'facing': {'type': 'string'}
        },
      },
      'decoy': {'layer': 'objects', 'tags': [], 'symbol': 'X'},
    },
    'actions': [
      {
        'id': 'tap_cell',
        'params': {
          'position': {'type': 'position'}
        }
      },
      {'id': 'fire_up', 'params': <String, dynamic>{}},
      {'id': 'fire_down', 'params': <String, dynamic>{}},
      {'id': 'fire_left', 'params': <String, dynamic>{}},
      {'id': 'fire_right', 'params': <String, dynamic>{}},
    ],
    'systems': [
      {'id': 'beam', 'type': 'beam', 'config': beamConfig},
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_beam');
}

Map<String, dynamic> _makeLevel({
  List<List<dynamic>> ground = const [],
  List<List<dynamic>> objects = const [],
  List<int> size = const [6, 6],
  List<Map<String, dynamic>> loseConditions = const [],
}) {
  return {
    'id': 'test_level',
    'board': {
      'size': size,
      'layers': {
        'ground': {
          'format': 'sparse',
          'entries': [
            for (final g in ground) {'position': [g[0], g[1]], 'kind': g[2]}
          ],
        },
        'objects': {
          'format': 'sparse',
          'entries': [
            for (final o in objects)
              {
                'position': [o[0], o[1]],
                'kind': o[2],
                if (o.length > 3) 'facing': o[3],
              }
          ],
        },
      },
    },
    'state': <String, dynamic>{},
    'goals': <dynamic>[],
    'loseConditions': loseConditions,
  };
}

TurnEngine _engineFor(GameDefinition game, Map<String, dynamic> levelJson) {
  final level = LevelDefinition.fromJson(levelJson, game.layers);
  return TurnEngine(game, level);
}

GameAction _tap(int x, int y) => GameAction('tap_cell', {
      'position': [x, y]
    });
GameAction _fire(String dir) => GameAction('fire_$dir', const {});

void main() {
  group('beam selection-only actionCount', () {
    test('reselecting an already-aimed source does not count as an action',
        () {
      final engine = _engineFor(
        _makeGame(),
        _makeLevel(objects: [
          [0, 0, 'source']
        ]),
      );

      engine.executeTurn(_tap(0, 0));
      expect(engine.state.actionCount, 0, reason: 'pure selection is free');

      engine.executeTurn(_fire('right'));
      expect(engine.state.actionCount, 1,
          reason: 'firing is a real action');

      engine.executeTurn(_tap(0, 0));
      expect(engine.state.actionCount, 1,
          reason: 'reselecting the same, already-firing source must stay '
              'free even though its beam retrace keeps emitting '
              'beam_traced/beam_cell_revealed every turn regardless of '
              'the action');
    });

    test('reselecting does not trip a max_actions loss early', () {
      final engine = _engineFor(
        _makeGame(),
        _makeLevel(
          objects: [
            [0, 0, 'source']
          ],
          loseConditions: [
            {
              'type': 'max_actions',
              'config': {'limit': 2}
            },
          ],
        ),
      );

      engine.executeTurn(_tap(0, 0));
      final firstFire = engine.executeTurn(_fire('right'));
      expect(firstFire.isLost, isFalse);
      expect(engine.state.actionCount, 1);

      final reselect = engine.executeTurn(_tap(0, 0));
      expect(reselect.isLost, isFalse,
          reason: 'a free reselect must not push actionCount over the '
              'limit on its own');
      expect(engine.state.actionCount, 1);

      final secondFire = engine.executeTurn(_fire('right'));
      expect(engine.state.actionCount, 2);
      expect(secondFire.isLost, isTrue,
          reason: 'the second genuine fire really does reach the limit');
    });
  });

  group('beam splitter blocked-side marker', () {
    test('a splitter with no glow config paints no marker on its blocked '
        'side', () {
      final engine = _engineFor(
        _makeGame(),
        _makeLevel(
          ground: [
            [2, 0, 'splitter_plain']
          ],
          objects: [
            [2, 1, 'source', 'up']
          ],
        ),
      );

      // Any turn triggers the retrace; the source's facing is already set
      // in the level itself, so no select/fire is needed to exercise it.
      engine.executeTurn(_tap(5, 5));

      expect(
        engine.state.board.getEntity('markers', const Position(2, 0)),
        isNull,
        reason: 'splitter_plain only maps its "right" approach — entering '
            'from "up" is its solid, unmapped side, and with no '
            'splitterGlowKinds/splitterBlockedKinds configured at all it '
            'must show no marker, not fall back to blockedKinds or '
            'pathKind as if it were a plain wall',
      );
    });
  });

  group('beam splitter self-intersection marker', () {
    test('a beam re-entering a splitter it already used paints the '
        'splitter-specific marker, not the generic one', () {
      final engine = _engineFor(
        _makeGame(),
        _makeLevel(
          ground: [
            [2, 2, 'splitter_plain']
          ],
          objects: [
            [1, 2, 'source', 'right'],
            [3, 2, 'source', 'left'],
          ],
        ),
      );

      engine.executeTurn(_tap(5, 5));

      expect(
        engine.state.board.getEntity('markers', const Position(2, 2))?.kind,
        'intersection_splitter_plain',
        reason: 'a genuine self-intersection landing on a splitter must '
            'prefer splitterIntersectionKinds for that entity kind over '
            'the generic intersectionKind, so the player can tell a '
            'divider was re-entered rather than two plain beams just '
            'crossing',
      );
    });

    test('a beam re-entering a plain segment still uses the generic '
        'intersection marker', () {
      final engine = _engineFor(
        _makeGame(),
        _makeLevel(
          objects: [
            [1, 2, 'source', 'right'],
            [3, 2, 'source', 'left'],
          ],
        ),
      );

      engine.executeTurn(_tap(5, 5));

      expect(
        engine.state.board.getEntity('markers', const Position(2, 2))?.kind,
        'intersection_generic',
        reason: 'with no splitter involved, splitterIntersectionKinds has '
            'nothing to match, so the collision falls back to the plain '
            'intersectionKind exactly as before',
      );
    });
  });

  group('beam fire revalidates the source', () {
    test('firing ignores a selected cell after it stops holding a source',
        () {
      final engine = _engineFor(
        _makeGame(),
        _makeLevel(objects: [
          [0, 0, 'source']
        ]),
      );

      engine.executeTurn(_tap(0, 0));

      // Simulate another mechanism replacing the entity at the selected
      // position between selection and firing — beam has no such mechanism
      // of its own, so this pokes the board directly the way any other
      // system would.
      engine.state.board.setEntity(
        'objects',
        const Position(0, 0),
        const EntityInstance('decoy'),
      );

      final result = engine.executeTurn(_fire('right'));

      expect(result.events.any((e) => e.type == 'beam_aimed'), isFalse,
          reason: 'firing onto a cell that no longer holds a beam_source '
              'must be a no-op');
      expect(
        engine.state.board.getEntity('objects', const Position(0, 0))
            ?.params,
        isEmpty,
        reason: 'the replacement entity must not have a facing param '
            'written onto it',
      );
    });
  });

  group('beam cardinal-only redirects', () {
    test('a reflector configured with a diagonal redirect ends the trace '
        'instead of turning diagonally', () {
      final engine = _engineFor(
        _makeGame(),
        _makeLevel(
          ground: [
            [2, 2, 'mirror_diag']
          ],
          objects: [
            [0, 2, 'source', 'right']
          ],
        ),
      );

      engine.executeTurn(_tap(5, 5));

      expect(
        engine.state.board.getEntity('markers', const Position(1, 1)),
        isNull,
        reason: 'mirror_diag maps an incoming "right" beam to "up_left" — '
            'a diagonal the engine must reject (matching Python\'s '
            'is_cardinal check) rather than silently stepping off at an '
            'angle',
      );
    });

    test('a splitter branch configured with a diagonal direction dead-ends '
        'at the splitter instead of continuing diagonally', () {
      final engine = _engineFor(
        _makeGame(),
        _makeLevel(
          ground: [
            [2, 2, 'splitter_diag']
          ],
          objects: [
            [0, 2, 'source', 'right']
          ],
        ),
      );

      engine.executeTurn(_tap(5, 5));

      expect(
        engine.state.board.getEntity('markers', const Position(3, 2)),
        isNotNull,
        reason: 'the cardinal "right" branch should still trace normally',
      );
      expect(
        engine.state.board.getEntity('markers', const Position(1, 1)),
        isNull,
        reason: 'the diagonal "up_left" branch must not step off at an '
            'angle',
      );
    });
  });
}
