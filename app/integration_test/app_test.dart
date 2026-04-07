import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:gridponder_app/main.dart' as app;
import 'package:gridponder_app/src/screens/library_screen.dart';
import 'package:gridponder_app/src/screens/play_screen.dart';
import 'package:gridponder_app/src/services/pack_service.dart';
import 'package:gridponder_app/src/services/settings_service.dart';

// ---------------------------------------------------------------------------
// TEST CONFIGURATION — change these to run different levels
// ---------------------------------------------------------------------------
const String kPackId = 'flag_adventure';
const String kLevelId = 'pw_001';
// Gold-path moves: (dx, dy) offsets for dragFrom — right=(100,0), left=(-100,0),
// down=(0,100), up=(0,-100).
const List<(double, double)> kMoves = [
  (0, 100),    // down → [0,1]
  (0, 100),    // down → [0,2]
  (0, 100),    // down → [0,3]
  (100, 0),    // right → [1,3] picks up pickaxe
  (100, 0),    // right → [2,3] enters portal, exits at [5,1]
  (-100, 0),   // left  → [4,1] breaks rock
  (-100, 0),   // left  → [3,1] reaches carrot
];
// ---------------------------------------------------------------------------

Future<void> _saveScreenshot(WidgetTester tester, String path) async {
  final boundary = tester.renderObject(find.byType(RepaintBoundary).first)
      as RenderRepaintBoundary;
  final image = await boundary.toImage(pixelRatio: 2.0);
  final byteData = await image.toByteData(format: ui.ImageByteFormat.png);
  await File(path).writeAsBytes(byteData!.buffer.asUint8List());
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('$kPackId/$kLevelId — execute ${kMoves.length} gold-path moves',
      (tester) async {
    app.main();

    // Wait for LibraryScreen to load
    await tester.pumpAndSettle(const Duration(seconds: 3));

    // Navigate directly to the target level
    final ctx = tester.element(find.byType(LibraryScreen));
    final settings = await SettingsService.create();
    final packService = await PackService.load(kPackId);

    Navigator.of(ctx).push(
      MaterialPageRoute(
        builder: (_) => PlayScreen(
          packService: packService,
          settings: settings,
          startLevelId: kLevelId,
        ),
      ),
    );
    await tester.pumpAndSettle(const Duration(seconds: 2));

    final tmp = Directory.systemTemp.path;
    final screenSize = tester.view.physicalSize / tester.view.devicePixelRatio;
    final center = Offset(screenSize.width / 2, screenSize.height / 2);

    // Step 0: initial state
    final step0 = '$tmp/gridponder_new_${kPackId}_${kLevelId}_step00.png';
    await _saveScreenshot(tester, step0);
    // ignore: avoid_print
    print('Screenshot step 00: $step0');

    // Execute moves, screenshotting after each
    for (int i = 0; i < kMoves.length; i++) {
      final (dx, dy) = kMoves[i];
      await tester.dragFrom(center, Offset(dx, dy));
      await tester.pumpAndSettle(const Duration(milliseconds: 800));

      final step = (i + 1).toString().padLeft(2, '0');
      final path = '$tmp/gridponder_new_${kPackId}_${kLevelId}_step$step.png';
      await _saveScreenshot(tester, path);
      // ignore: avoid_print
      print('Screenshot step $step: $path');
    }

    // Verify play screen is still displaying (no crash)
    expect(find.byType(PlayScreen), findsOneWidget);
  });
}
