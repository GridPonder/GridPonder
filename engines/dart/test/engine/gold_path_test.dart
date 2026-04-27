import 'dart:convert';
import 'dart:io';

import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

/// Helpers for loading a pack from disk and replaying a gold path.
LoadedPack _loadPack(String packDir) {
  final manifestStr =
      File('$packDir/manifest.json').readAsStringSync();
  final gameStr = File('$packDir/game.json').readAsStringSync();

  final levelsDir = Directory('$packDir/levels');
  final levelStrs = <String, String>{};
  for (final file in levelsDir.listSync().whereType<File>()) {
    levelStrs[file.path] = file.readAsStringSync();
  }

  return PackLoader.loadFromStrings(
    manifestStr: manifestStr,
    gameStr: gameStr,
    levelStrs: levelStrs,
  );
}

TurnEngine _engineForLevel(LoadedPack pack, String levelId) {
  final level = pack.levels[levelId];
  if (level == null) throw StateError('Level $levelId not found');
  return TurnEngine(pack.game, level);
}

List<GameAction> _goldPath(LoadedPack pack, String levelId) {
  final level = pack.levels[levelId];
  if (level == null) throw StateError('Level $levelId not found');
  return level.solution.goldPath;
}

void _replayAndExpectWin(TurnEngine engine, List<GameAction> path) {
  for (final action in path) {
    if (engine.isWon) break;
    engine.executeTurn(action);
  }
  expect(engine.isWon, isTrue,
      reason: 'Should be won after gold path');
  expect(engine.isLost, isFalse);
}

void main() {
  // --- carrot_quest ---
  group('carrot_quest gold paths', () {
    late LoadedPack pack;
    setUpAll(() => pack = _loadPack('../../packs/carrot_quest'));

    for (final id in [
      'fw_001','fw_002','fw_003','fw_004','fw_005','fw_006','pw_001','pw_003','fw_007',
      'fw_ice_002','fw_ice_003','fw_ice_005','fw_ice_006','fw_ice_007','fw_ice_008',
      'fw_ice_011',
    ]) {
      test(id, () => _replayAndExpectWin(_engineForLevel(pack, id), _goldPath(pack, id)));
    }
  });

  // --- number_cells ---
  group('number_cells gold paths', () {
    late LoadedPack pack;
    setUpAll(() => pack = _loadPack('../../packs/number_cells'));

    for (final id in ['nc_001','nc_002','nc_003','nc_004','nc_005','nc_006','nc_007','nc_008','nc_009','nc_010','nc_011','nc_012','nc_013','nc_014','nc_015','nc_019']) {
      test(id, () => _replayAndExpectWin(_engineForLevel(pack, id), _goldPath(pack, id)));
    }
  });

  // --- rotate_flip ---
  group('rotate_flip gold paths', () {
    late LoadedPack pack;
    setUpAll(() => pack = _loadPack('../../packs/rotate_flip'));

    for (final id in ['rf_001','rf_002']) {
      test(id, () => _replayAndExpectWin(_engineForLevel(pack, id), _goldPath(pack, id)));
    }
  });

  // --- flood_colors ---
  group('flood_colors gold paths', () {
    late LoadedPack pack;
    setUpAll(() => pack = _loadPack('../../packs/flood_colors'));

    test('fl_001', () => _replayAndExpectWin(_engineForLevel(pack, 'fl_001'), _goldPath(pack, 'fl_001')));
    test('fl_002', () => _replayAndExpectWin(_engineForLevel(pack, 'fl_002'), _goldPath(pack, 'fl_002')));
    test('fl_003', () => _replayAndExpectWin(_engineForLevel(pack, 'fl_003'), _goldPath(pack, 'fl_003')));
  });

  // --- diagonal_swipes ---
  group('diagonal_swipes gold paths', () {
    late LoadedPack pack;
    setUpAll(() => pack = _loadPack('../../packs/diagonal_swipes'));

    for (final id in ['ds_001','ds_002']) {
      test(id, () => _replayAndExpectWin(_engineForLevel(pack, id), _goldPath(pack, id)));
    }
  });

  group('undo/reset', () {
    late LoadedPack pack;
    setUpAll(() => pack = _loadPack('../../packs/carrot_quest'));
    test('undo restores state', () {
      final engine = _engineForLevel(pack, 'fw_001');
      final initialState = engine.state;
      engine.executeTurn(GameAction('move', {'direction': 'right'}));
      expect(engine.state.avatar.position, isNot(equals(initialState.avatar.position)));
      expect(engine.undo(), isTrue);
      expect(engine.state.avatar.position, equals(initialState.avatar.position));
    });

    test('reset restores initial state', () {
      final engine = _engineForLevel(pack, 'fw_001');
      final goldPath = _goldPath(pack, 'fw_001');
      for (final action in goldPath) {
        engine.executeTurn(action);
      }
      expect(engine.isWon, isTrue);
      engine.reset();
      expect(engine.isWon, isFalse);
      expect(engine.undoDepth, equals(0));
    });
  });
}
