import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

void main() {
  test('gesture bindings opt in to cell selection feedback', () {
    final controls = ControlsDef.fromJson({
      'gestureMap': [
        {
          'gesture': 'tap_cell',
          'action': 'rotate_cell',
          'showSelection': true,
        },
      ],
    });

    expect(controls.gestureMap.single.showSelection, isTrue);
  });

  test('cell selection feedback is disabled by default', () {
    final binding = GestureBinding.fromJson({
      'gesture': 'tap_cell',
      'action': 'rotate_cell',
    });

    expect(binding.showSelection, isFalse);
  });
}
