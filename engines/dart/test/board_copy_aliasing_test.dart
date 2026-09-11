// A board copy must not alias the entities of the board it came from.
//
// `BoardLayer.copy` used to copy the cell slots but share the EntityInstance
// objects, whose `params` map is mutable and written in place -- follower_npcs
// assigns `params['facing']` on every reversal. So playing a level rewrote the
// facings inside the LevelDefinition it was loaded from: the first run of a
// level worked and every later run in the same session started from a board the
// first run had turned around. In the app that is the Solve button replaying
// from a corrupted board. Python's `Entity.copy` has always deep-copied params,
// so this was also a silent Python/Dart divergence that trace parity could not
// see, because each trace builds a fresh engine.
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _game() => GameDefinition.fromJson({
  'id': 'com.gridponder.test_board_copy_aliasing',
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
    {
      'id': 'machines',
      'type': 'follower_npcs',
      'config': {
        'npcTags': ['npc'],
        'behaviors': {
          'walker': {
            'type': 'patrol',
            'lethalContact': false,
            'solidBlocking': true,
          },
        },
      },
    },
  ],
}, id: 'test_board_copy_aliasing');

/// A 4x3 board with one machine patrolling the top row, starting east. It hits
/// the east edge within three beats and turns around, which writes its facing.
LevelDefinition _level(GameDefinition game) => LevelDefinition.fromJson({
  'id': 'test_level',
  'board': {
    'size': [4, 3],
    'layers': {
      'actors': {
        'format': 'sparse',
        'entries': [
          {
            'position': [0, 0],
            'kind': 'machine',
            'behavior': 'walker',
            'facing': 'right',
          },
        ],
      },
    },
  },
  'state': {
    'avatar': {
      'enabled': true,
      'position': [0, 2],
    },
  },
  'goals': <dynamic>[],
  'loseConditions': <dynamic>[],
}, game.layers);

String _facings(LevelState s) => s.board.layers['actors']!
    .entries()
    .map((e) => '${e.key}:${e.value.params['facing']}')
    .join(' ');

/// Spends [beats] beats by walking into the bottom edge (a blocked move is still
/// a beat) and returns the machine's position and facing after each one.
List<String> _run(GameDefinition game, LevelDefinition level, int beats) {
  final engine = TurnEngine(game, level);
  final trace = <String>[];
  for (var i = 0; i < beats; i++) {
    engine.executeTurn(GameAction('move', {'direction': 'down'}));
    trace.add(_facings(engine.state));
  }
  return trace;
}

void main() {
  test(
    'replaying a level twice from the same definition gives the same run',
    () {
      final game = _game();
      final level = _level(game);

      final before = _facings(TurnEngine(game, level).state);
      final first = _run(game, level, 6);
      expect(
        first.any((f) => f.endsWith(':left')),
        isTrue,
        reason: 'the fixture must make the machine turn around',
      );

      // A brand-new engine on the SAME definition must see the same board.
      expect(
        _facings(TurnEngine(game, level).state),
        before,
        reason: 'playing mutated the level definition',
      );
      expect(
        _run(game, level, 6),
        first,
        reason: 'the second run of the same definition diverged',
      );
    },
  );
}
