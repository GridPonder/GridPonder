import 'dart:io';
import 'package:test/test.dart';
import 'package:gridponder_engine/engine.dart';

LoadedPack _loadPack(String packDir) {
  final manifestStr = File('$packDir/manifest.json').readAsStringSync();
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

void main() {
  late LoadedPack pack;
  late GameDefinition gameDef;
  late LevelDefinition levelDef;

  setUpAll(() {
    pack = _loadPack('../packs/flood_colors');
    gameDef = pack.game;
    levelDef = pack.levels['fl_001']!;
  });

  group('anonymous mode', () {
    test('buildAnonKindToLabel assigns unique letters in alphabetical order', () {
      final map = buildAnonKindToLabel(gameDef);

      // Labels are unique.
      expect(map.values.toSet().length, equals(map.length));
      // Entities with symbol '.' or ' ' must NOT be in the map.
      for (final entry in gameDef.entityKinds.entries) {
        final sym = entry.value.symbol;
        if (sym == '.' || sym == ' ') {
          expect(map.containsKey(entry.key), isFalse,
              reason: 'void/empty kind "${entry.key}" should be excluded');
        }
      }
      // Non-void kinds should all have labels.
      for (final entry in gameDef.entityKinds.entries) {
        final sym = entry.value.symbol;
        if (sym != '.' && sym != ' ') {
          expect(map.containsKey(entry.key), isTrue,
              reason: 'kind "${entry.key}" should have a label');
        }
      }
      // First label should be 'A'.
      if (map.isNotEmpty) {
        expect(map.values.contains('A'), isTrue);
      }
    });

    test('buildAnonReverseMap covers all valid actions', () {
      final engine = TurnEngine(gameDef, levelDef);
      final obs = AgentObservation.build(gameDef, levelDef, engine.state);
      final reverseMap = buildAnonReverseMap(obs.validActions);

      expect(reverseMap.length, equals(obs.validActions.length));
      // Labels are a1…aN.
      final n = obs.validActions.length;
      for (int i = 1; i <= n; i++) {
        expect(reverseMap.containsKey('a$i'), isTrue);
      }
      // Deterministic: rebuilt map equals original.
      final reverseMap2 = buildAnonReverseMap(obs.validActions);
      for (final label in reverseMap.keys) {
        expect(reverseMap[label]!.actionId, equals(reverseMap2[label]!.actionId));
      }
    });

    test('buildPrompt anonymize=false is identical to default', () {
      final engine = TurnEngine(gameDef, levelDef);
      final obs = AgentObservation.build(gameDef, levelDef, engine.state);
      expect(
        LlmAgent.buildPrompt(obs, anonymize: false),
        equals(LlmAgent.buildPrompt(obs)),
      );
    });

    test('buildPrompt anonymize=true hides game title and entity names', () {
      final engine = TurnEngine(gameDef, levelDef);
      final kindMap = buildAnonKindToLabel(gameDef);
      final obs = AgentObservation.build(
        gameDef, levelDef, engine.state,
        kindSymbolOverrides: kindMap,
      );

      final promptAnon = LlmAgent.buildPrompt(obs, anonymize: true);

      // Title line is just the generic phrase, not the game title.
      expect(promptAnon, contains('You are playing a grid puzzle.'));
      expect(promptAnon, isNot(contains(gameDef.title)));

      // Available actions use a1…aN labels, not real action IDs.
      expect(promptAnon, contains('"action": "a1"'));
      final actionsSection =
          promptAnon.split('AVAILABLE ACTIONS:').last.split('\n\n').first;
      // flood_colors actions all start with "flood_" — none should appear.
      final hasRealAction =
          gameDef.actions.any((a) => actionsSection.contains('"${a.id}"'));
      expect(hasRealAction, isFalse,
          reason: 'real action IDs must not appear in actions section');
    });

    test('board rendered with kindSymbolOverrides uses only letter symbols', () {
      final engine = TurnEngine(gameDef, levelDef);
      final kindMap = buildAnonKindToLabel(gameDef);
      final obs = AgentObservation.build(
        gameDef,
        levelDef,
        engine.state,
        kindSymbolOverrides: kindMap,
      );

      // Extract just the grid (first block before the legend).
      final gridBlock = obs.boardText.split('\n\n').first;
      for (final ch in gridBlock.split('').where((c) => c != '\n')) {
        // Letters (A-Z), empty '.', avatar '@', number 'N', and void ' ' are OK.
        final ok = RegExp(r'^[A-Z.@ N]$').hasMatch(ch);
        expect(ok, isTrue,
            reason: 'Unexpected board character: "$ch"');
      }

      // Legend should use '?' for anonymised entity descriptions.
      expect(obs.boardText, contains('=?'));
      // Legend should NOT contain any non-? game-specific entity uiNames
      // (flood_colors has no custom uiNames, so skip if all are null/'?').
      final customNames = gameDef.entityKinds.values
          .map((k) => k.uiName ?? '')
          .where((n) => n.isNotEmpty && n != '?')
          .toList();
      for (final name in customNames) {
        expect(obs.boardText, isNot(contains(name)),
            reason: 'Legend should not contain "$name" in anon mode');
      }
    });
  });
}
