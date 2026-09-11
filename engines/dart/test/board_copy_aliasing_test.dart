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
import 'dart:convert';
import 'dart:io';
import 'package:test/test.dart';
import 'package:gridponder_engine/engine.dart';

void main() {
  test('replaying a level twice from the same definition gives the same run', () {
    final root = '/home/mahmoud/work/TIB/gridponder-private/escapement';
    final game = GameDefinition.fromJson(
        jsonDecode(File('$root/game.json').readAsStringSync()) as Map<String, dynamic>);
    final level = LevelDefinition.fromJson(
        jsonDecode(File('$root/levels/esc_006.json').readAsStringSync())
            as Map<String, dynamic>,
        game.layers);

    String facings(LevelState s) => s.board.layers['actors']!
        .entries()
        .map((e) => '${e.key}:${e.value.params['facing']}')
        .join(' ');

    final before = facings(TurnEngine(game, level).state);

    // Play the gold path once, exactly as the Solve button does.
    final first = TurnEngine(game, level);
    for (final a in level.solution.goldPath) {
      first.executeTurn(a);
    }
    final wonFirst = first.isWon;

    // A brand-new engine on the SAME definition must see the same board.
    final after = facings(TurnEngine(game, level).state);
    final second = TurnEngine(game, level);
    for (final a in level.solution.goldPath) {
      second.executeTurn(a);
    }

    print('  initial facings : $before');
    print('  after one play  : $after');
    print('  first run won   : $wonFirst');
    print('  second run won  : ${second.isWon}  avatar=${second.state.avatar.position}');

    expect(after, before, reason: 'playing mutated the level definition');
    expect(second.isWon, isTrue, reason: 'second replay of the same gold path failed');
  });
}
