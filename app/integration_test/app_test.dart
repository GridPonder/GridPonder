import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:gridponder_app/main.dart' as app;
import 'package:gridponder_app/src/screens/library_screen.dart';
import 'package:gridponder_app/src/screens/play_screen.dart';
import 'package:gridponder_app/src/services/pack_file_reader.dart';
import 'package:gridponder_app/src/services/pack_registry.dart';
import 'package:gridponder_app/src/services/pack_service.dart';
import 'package:gridponder_app/src/services/settings_service.dart';
import 'package:gridponder_app/src/widgets/board_renderer.dart';

// ---------------------------------------------------------------------------
// TEST CONFIGURATION — change these to run different levels
// ---------------------------------------------------------------------------
const String kPackId = 'twinseed';
// Where the pack is bundled: 'assets/packs' (public) or 'assets/packs-private'.
const String kPackRoot = 'assets/packs';
const String kLevelId = 'tw_005';
// Board width in cells; only used by cell-targeted moves ('x,y,direction').
const int kBoardCols = 5;
// Gold-path moves: a direction string or button label.
//   Swipes:  'right' | 'left' | 'up' | 'down'   (from the screen centre)
//   Cell swipes: '<x>,<y>,<direction>'          (from the centre of that cell,
//                                                for position+direction games)
//   Buttons: 'clone'
const List<String> kMoves = [
  'up', 'up', 'left', 'clone', 'right', 'right', 'right', 'right', 'up', 'left',
  'up', 'left', 'left', 'down', 'up', 'right', 'down', 'down', 'down', 'clone',
  'right', 'right', 'right',
];
// ---------------------------------------------------------------------------

Future<void> _saveScreenshot(WidgetTester tester, String path) async {
  final boundary = tester.renderObject(find.byType(RepaintBoundary).first)
      as RenderRepaintBoundary;
  final image = await boundary.toImage(pixelRatio: 2.0);
  final byteData = await image.toByteData(format: ui.ImageByteFormat.png);
  await File(path).writeAsBytes(byteData!.buffer.asUint8List());
}

Future<void> _executeMove(WidgetTester tester, String move, Offset center) async {
  switch (move) {
    case 'right':
      await tester.dragFrom(center, const Offset(100, 0));
    case 'left':
      await tester.dragFrom(center, const Offset(-100, 0));
    case 'down':
      await tester.dragFrom(center, const Offset(0, 100));
    case 'up':
      await tester.dragFrom(center, const Offset(0, -100));
    case 'swap_right':
      // Tap the first "Swap" button (↘ down_right diagonal)
      await tester.tap(find.text('Swap').first);
    case 'swap_left':
      // Tap the second "Swap" button (↙ down_left diagonal)
      await tester.tap(find.text('Swap').last);
    default:
      if (move.contains(',')) {
        final parts = move.split(',');
        final grid = tester.getRect(find
            .descendant(
                of: find.byType(BoardRenderer), matching: find.byType(Stack))
            .first);
        final cell = grid.width / kBoardCols;
        final start = grid.topLeft +
            Offset((int.parse(parts[0]) + 0.5) * cell,
                (int.parse(parts[1]) + 0.5) * cell);
        final delta = switch (parts[2]) {
          'right' => const Offset(100, 0),
          'left' => const Offset(-100, 0),
          'down' => const Offset(0, 100),
          _ => const Offset(0, -100),
        };
        await tester.dragFrom(start, delta);
        return;
      }
      // Button tap: find by capitalised label
      final label = move[0].toUpperCase() + move.substring(1);
      await tester.tap(find.text(label));
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('$kPackId/$kLevelId — execute ${kMoves.length} gold-path moves',
      (tester) async {
    app.main();

    // Wait for LibraryScreen to load
    await tester.pumpAndSettle(const Duration(seconds: 3));

    // Screenshot the library screen (shows DEV badges in debug mode / progress bars in release)
    final screenshotDir0 = '${Directory.current.path}/test/screenshots';
    await Directory(screenshotDir0).create(recursive: true);
    await _saveScreenshot(tester,
        '$screenshotDir0/gridponder_new_library_screen.png');

    // Navigate directly to the target level
    final ctx = tester.element(find.byType(LibraryScreen));
    final settings = await SettingsService.create();
    final packService = await PackService.loadFromEntry(PackEntry(
      id: kPackId,
      isInstalled: false,
      reader: BundledPackFileReader(kPackId, assetRoot: kPackRoot),
    ));

    Navigator.of(ctx).push(
      MaterialPageRoute(
        builder: (_) => PlayScreen(
          packService: packService,
          settings: settings,
          startLevelId: kLevelId,
        ),
      ),
    );
    // Bounded pumps instead of pumpAndSettle: a looping animation on the play
    // screen (hint pulse) can keep pumpAndSettle from ever returning.
    for (var i = 0; i < 20; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }

    final screenshotDir = screenshotDir0;
    final screenSize = tester.view.physicalSize / tester.view.devicePixelRatio;
    final center = Offset(screenSize.width / 2, screenSize.height / 2);

    // Step 0: initial state
    final step0 = '$screenshotDir/gridponder_new_${kPackId}_${kLevelId}_step00.png';
    await _saveScreenshot(tester, step0);
    // ignore: avoid_print
    print('Screenshot step 00: $step0');

    // Execute moves, screenshotting after each
    for (int i = 0; i < kMoves.length; i++) {
      await _executeMove(tester, kMoves[i], center);
      await tester.pumpAndSettle(const Duration(milliseconds: 800));

      final step = (i + 1).toString().padLeft(2, '0');
      final path = '$screenshotDir/gridponder_new_${kPackId}_${kLevelId}_step$step.png';
      await _saveScreenshot(tester, path);
      // ignore: avoid_print
      print('Screenshot step $step: $path');
    }

    // Verify play screen is still displaying (no crash)
    expect(find.byType(PlayScreen), findsOneWidget);
  });
}
