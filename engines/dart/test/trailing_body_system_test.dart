// Parity mirror of engines/python/test_trailing_body.py — the
// `trailing_body` system's unload mechanic (docs/dsl/04_systems.md §2.26).
// Structural mid-chain splice-and-reconnect behavior a gold path exercises
// implicitly (ht_009) but doesn't assert on directly, so it's covered here
// against internal state instead.
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _makeGame({Map<String, dynamic>? unloadConfig}) {
  final data = {
    'id': 'com.gridponder.test_trailing_body',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
      {'id': 'objects', 'occupancy': 'zero_or_one'},
      {'id': 'tail', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'empty': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': '.',
      },
      'pickup_item': {
        'layer': 'objects',
        'tags': ['pickup'],
        'symbol': 'p',
      },
      'unloader': {
        'layer': 'objects',
        'tags': ['unloader'],
        'symbol': 'u',
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
        'id': 'trail',
        'type': 'trailing_body',
        'config': {
          'moverTag': 'avatar',
          'bodyLayer': 'tail',
          'growthKindSource': 'objects',
          'growthTriggerTag': 'pickup',
          'growthColorParam': 'color',
          'segmentKindTemplate': 'seg_{color}_{shape}',
          ...?unloadConfig,
        },
      },
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_trailing_body');
}

/// 6x1 corridor. Avatar starts at (avatarX, 0); the caller seeds the chain
/// directly onto the engine after construction (see test bodies) since
/// building it up through real pickup turns isn't the point here. An
/// unloader tile, when unloaderX is given, sits at (unloaderX, 0).
Map<String, dynamic> _chainLevel({
  required int avatarX,
  int? unloaderX,
  String unloaderColor = 'yellow',
}) {
  final objectsEntries = <dynamic>[];
  if (unloaderX != null) {
    objectsEntries.add({
      'position': [unloaderX, 0],
      'kind': 'unloader',
      'color': unloaderColor,
    });
  }
  return {
    'id': 'test_level',
    'board': {
      'size': [6, 1],
      'layers': {
        'objects': {'format': 'sparse', 'entries': objectsEntries},
      },
    },
    'state': {
      'avatar': {
        'enabled': true,
        'position': [avatarX, 0],
      },
    },
    'goals': <dynamic>[],
    'loseConditions': <dynamic>[],
  };
}

TurnEngine _engineFor(GameDefinition game, Map<String, dynamic> levelJson) {
  final level = LevelDefinition.fromJson(levelJson, game.layers);
  return TurnEngine(game, level);
}

/// Directly seeds the trailing_body system's internal segment list, as if
/// `chain` (closest-to-mover first) had already been picked up over
/// previous turns. `prevPos` is already the avatar's starting cell, set by
/// load-settle at construction — exactly where a real closest segment
/// would be adjacent to.
void _seedChain(TurnEngine engine, List<(int, String)> chain) {
  engine.state.variables['_trailingBody_trail_segments'] = [
    for (final (x, color) in chain) {
      'position': [x, 0],
      'color': color,
    },
  ];
}

void main() {
  test('unload splices a middle segment and reconnects the rest', () {
    // Red(closest) -> Yellow -> Blue(farthest), straight line behind an
    // avatar at x=3. Yellow's unloader sits exactly where Yellow will land
    // this turn (x=2). Moving right should: remove Yellow, pull Blue
    // forward into Yellow's slot (x=2), leave Red's ordinary one-cell hop
    // (x=2->x=3) untouched, and leave the unloader tile itself alone (only
    // a pack rule reacting to body_segment_unloaded would change it).
    final game = _makeGame(unloadConfig: {'unloadLayer': 'objects'});
    final level = _chainLevel(avatarX: 3, unloaderX: 2, unloaderColor: 'yellow');
    final engine = _engineFor(game, level);
    _seedChain(engine, [(2, 'red'), (1, 'yellow'), (0, 'blue')]);

    final result = engine.executeTurn(GameAction('move', {'direction': 'right'}));

    expect(result.accepted, isTrue);

    final unloaded =
        result.events.where((e) => e.type == 'body_segment_unloaded').toList();
    expect(unloaded, hasLength(1));
    expect(unloaded.single.position, const Position(2, 0));
    expect(unloaded.single['color'], 'yellow');

    final segments =
        engine.state.variables['_trailingBody_trail_segments'] as List;
    expect(
      segments
          .map((s) => (Position.fromJson(s['position']), s['color']))
          .toList(),
      [
        (const Position(3, 0), 'red'),
        (const Position(2, 0), 'blue'),
      ],
    );

    // Red's hop is a legal one-cell slide and must animate; Blue's two-cell
    // pull (closing the gap left by Yellow) must not pretend to be one.
    final moved = result.events.where((e) => e.type == 'tile_moved').toList();
    expect(moved, hasLength(1));
    expect(moved.single['fromPosition'], const Position(2, 0));
    expect(moved.single.position, const Position(3, 0));

    final freed = result.events
        .where((e) => e.type == 'body_segment_freed')
        .map((e) => e.position)
        .toSet();
    expect(freed, {const Position(1, 0), const Position(0, 0)});

    expect(
      engine.state.board.getEntity('tail', const Position(3, 0))?.kind,
      'seg_red_horizontal',
    );
    expect(
      engine.state.board.getEntity('tail', const Position(2, 0))?.kind,
      'seg_blue_horizontal',
    );
    expect(engine.state.board.getEntity('tail', const Position(1, 0)), isNull);
    expect(engine.state.board.getEntity('tail', const Position(0, 0)), isNull);

    // The unloader tile is untouched by the engine — only a pack rule
    // reacting to body_segment_unloaded is meant to change it.
    final unloader =
        engine.state.board.getEntity('objects', const Position(2, 0));
    expect(unloader?.kind, 'unloader');
  });

  test('unload requires a matching color', () {
    // The same geometry, but the unloader at x=2 is red, not yellow — the
    // yellow segment landing there must NOT be spliced out.
    final game = _makeGame(unloadConfig: {'unloadLayer': 'objects'});
    final level = _chainLevel(avatarX: 3, unloaderX: 2, unloaderColor: 'red');
    final engine = _engineFor(game, level);
    _seedChain(engine, [(2, 'red'), (1, 'yellow'), (0, 'blue')]);

    final result = engine.executeTurn(GameAction('move', {'direction': 'right'}));

    expect(
      result.events.any((e) => e.type == 'body_segment_unloaded'),
      isFalse,
    );
    final segments =
        engine.state.variables['_trailingBody_trail_segments'] as List;
    expect(
      segments
          .map((s) => (Position.fromJson(s['position']), s['color']))
          .toList(),
      [
        (const Position(3, 0), 'red'),
        (const Position(2, 0), 'yellow'),
        (const Position(1, 0), 'blue'),
      ],
    );
  });

  test('unloading is opt-in', () {
    // Without unloadLayer configured, a segment landing on an
    // `unloader`-tagged entity is just an ordinary segment passing over an
    // ordinary cell — nothing is spliced, no event fires. Confirms a pack
    // that never sets unloadLayer pays nothing here.
    final game = _makeGame();
    final level = _chainLevel(avatarX: 3, unloaderX: 2, unloaderColor: 'yellow');
    final engine = _engineFor(game, level);
    _seedChain(engine, [(2, 'red'), (1, 'yellow'), (0, 'blue')]);

    final result = engine.executeTurn(GameAction('move', {'direction': 'right'}));

    expect(
      result.events.any((e) => e.type == 'body_segment_unloaded'),
      isFalse,
    );
    final segments =
        engine.state.variables['_trailingBody_trail_segments'] as List;
    expect(segments, hasLength(3));
  });
}
