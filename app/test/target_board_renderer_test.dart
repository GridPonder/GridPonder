import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gridponder_app/src/widgets/board_renderer.dart';

void main() {
  Map<String, dynamic> targetLayers(int rows, int cols) => {
    'ground': List.generate(rows, (_) => List<String?>.filled(cols, null)),
  };

  testWidgets('lays out inside IntrinsicHeight without throwing', (
    tester,
  ) async {
    // _buildGoalGuidePanel (play_screen.dart) wraps the goal panel in
    // IntrinsicHeight to line it up with the guide panel beside it.
    // IntrinsicHeight queries its children's intrinsic dimensions during
    // layout, which a LayoutBuilder-based child cannot answer -- it throws.
    // This reproduces that exact ancestor shape for a large board, where the
    // bug first showed up as a frozen blank screen on every level.
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              IntrinsicHeight(
                child: TargetBoardRenderer(targetLayers: targetLayers(13, 25)),
              ),
            ],
          ),
        ),
      ),
    );

    expect(tester.takeException(), isNull);
    expect(find.byType(TargetBoardRenderer), findsOneWidget);
  });

  testWidgets('renders a small board at full cell size', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TargetBoardRenderer(targetLayers: targetLayers(3, 3)),
        ),
      ),
    );

    expect(tester.takeException(), isNull);
    final size = tester.getSize(find.byType(TargetBoardRenderer));
    expect(size.width, 72); // 3 cols * 24px max cell size
    expect(size.height, 72);
  });
}
