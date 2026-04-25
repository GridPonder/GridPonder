/// trace.dart — Replay a level's goldPath step-by-step and output the board
/// state after each move, in the same canonical format as trace_path.py so the
/// two outputs can be diffed directly.
///
/// Usage:
///   dart run bin/trace.dart <pack_dir> <level_id> [max_steps]
///
/// Example:
///   dart run bin/trace.dart ../packs/carrot_quest fw_ice_006c
///   dart run bin/trace.dart ../packs/carrot_quest fw_ice_006c 30

import 'dart:io';

import 'package:gridponder_engine/engine.dart';

void main(List<String> args) {
  if (args.isEmpty || args.length < 2) {
    stderr.writeln('Usage: dart run bin/trace.dart <pack_dir> <level_id> [max_steps]');
    exit(1);
  }

  final packDir = args[0];
  final levelId = args[1];
  final maxSteps = args.length >= 3 ? int.parse(args[2]) : null;

  // Load pack
  final manifestStr = File('$packDir/manifest.json').readAsStringSync();
  final gameStr = File('$packDir/game.json').readAsStringSync();

  final levelsDir = Directory('$packDir/levels');
  final levelStrs = <String, String>{};
  for (final file in levelsDir.listSync().whereType<File>()) {
    levelStrs[file.path] = file.readAsStringSync();
  }

  final pack = PackLoader.loadFromStrings(
    manifestStr: manifestStr,
    gameStr: gameStr,
    levelStrs: levelStrs,
  );

  final level = pack.levels[levelId];
  if (level == null) {
    stderr.writeln('Level "$levelId" not found in pack.');
    exit(1);
  }

  final engine = TurnEngine(pack.game, level);
  final goldPath = level.solution.goldPath;
  final steps = maxSteps != null ? goldPath.take(maxSteps).toList() : goldPath;

  final initPos = engine.state.avatar.position;
  print('level=$levelId');
  print('avatar_start=(${initPos?.x},${initPos?.y}) inventory=none');
  print('');

  for (var i = 0; i < steps.length; i++) {
    final action = steps[i];
    final direction = action.params['direction'] as String? ?? '?';
    final prevState = engine.state;

    final result = engine.executeTurn(action);

    final newPos = result.newState.avatar.position;
    final inv = result.newState.avatar.inventory.slot ?? 'none';
    final accepted = result.accepted;
    final noop = !accepted || _stateUnchanged(prevState, result.newState);

    final noopStr = noop ? ' noop' : '';
    print('step=${i + 1} action=$direction accepted=${accepted ? 'true' : 'false'}$noopStr');
    print('avatar=(${newPos?.x},${newPos?.y}) inventory=$inv');

    if (result.events.isNotEmpty) {
      print('events:');
      for (final ev in result.events) {
        print(_formatEvent(ev));
      }
    }
    print('');

    if (result.isWon) {
      print('WON at step=${i + 1}');
      return;
    }
  }

  final finalPos = engine.state.avatar.position;
  final carrotPos = _findCarrot(engine.state);
  final won = engine.isWon;
  print('end avatar=(${finalPos?.x},${finalPos?.y}) carrot=$carrotPos won=$won');
}

bool _stateUnchanged(LevelState a, LevelState b) {
  // Quick check: avatar position and inventory same
  final aPos = a.avatar.position;
  final bPos = b.avatar.position;
  if (aPos?.x != bPos?.x || aPos?.y != bPos?.y) return false;
  if (a.avatar.inventory.slot != b.avatar.inventory.slot) return false;
  // Compare object layers
  final aObj = _layerSnapshot(a, 'objects');
  final bObj = _layerSnapshot(b, 'objects');
  if (aObj != bObj) return false;
  final aGnd = _layerSnapshot(a, 'ground');
  final bGnd = _layerSnapshot(b, 'ground');
  return aGnd == bGnd;
}

Map<String, String> _layerSnapshot(LevelState state, String layerId) {
  final layer = state.board.layers[layerId];
  if (layer == null) return {};
  final result = <String, String>{};
  for (final entry in layer.entries()) {
    result['(${entry.key.x},${entry.key.y})'] = entry.value.kind;
  }
  return result;
}

String _findCarrot(LevelState state) {
  final markers = state.board.layers['markers'];
  if (markers == null) return '?';
  for (final entry in markers.entries()) {
    if (entry.value.kind == 'carrot') {
      return '(${entry.key.x},${entry.key.y})';
    }
  }
  return '?';
}

String _formatEvent(GameEvent ev) {
  final pos = ev.position;
  final posStr = pos != null ? ' (${pos.x},${pos.y})' : '';
  final extras = <String>[];
  for (final key in ev.payload.keys) {
    if (key == 'position' || key == 'animation') continue;
    final val = ev.payload[key];
    if (val is Map || val is List) continue; // skip complex values
    extras.add('$key=$val');
  }
  final extraStr = extras.isEmpty ? '' : ' ${extras.join(' ')}';
  return '  ${ev.type}$posStr$extraStr';
}
