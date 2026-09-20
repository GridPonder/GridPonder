import 'package:flutter_test/flutter_test.dart';
import 'package:gridponder_app/src/screens/cell_selection_state.dart';
import 'package:gridponder_engine/engine.dart';

void main() {
  const optedInBinding = GestureBinding(
    gesture: 'tap_cell',
    action: 'rotate_cell',
    paramMapping: {'position': 'tap_position'},
    showSelection: true,
  );

  test('accepted tap action position can be reused during replay', () {
    final position = selectionPositionForAction(
      GameAction('rotate_cell', {
        'position': [3, 2],
      }),
      const [optedInBinding],
    );

    expect(position, const Position(3, 2));
  });

  test('bindings without selection feedback do not select a cell', () {
    final position = selectionPositionForAction(
      GameAction('rotate_cell', {
        'position': [3, 2],
      }),
      const [
        GestureBinding(
          gesture: 'tap_cell',
          action: 'rotate_cell',
          paramMapping: {'position': 'tap_position'},
        ),
      ],
    );

    expect(position, isNull);
  });
}
