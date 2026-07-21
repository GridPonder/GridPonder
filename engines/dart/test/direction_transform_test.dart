import 'package:gridponder_engine/src/models/direction_transform.dart';
import 'package:gridponder_engine/src/models/position.dart';
import 'package:test/test.dart';

const up = Position(0, -1);
const down = Position(0, 1);
const left = Position(-1, 0);
const right = Position(1, 0);

void main() {
  group('transformDelta', () {
    test('identity leaves every cardinal unchanged', () {
      for (final d in [up, down, left, right]) {
        expect(transformDelta(d, 'identity'), equals(d));
      }
    });

    test('missing and unknown transforms are identity (parity-safe)', () {
      expect(transformDelta(right, null), equals(right));
      expect(transformDelta(right, 'not_a_transform'), equals(right));
    });

    test('invert reverses both axes', () {
      expect(transformDelta(right, 'invert'), equals(left));
      expect(transformDelta(left, 'invert'), equals(right));
      expect(transformDelta(up, 'invert'), equals(down));
      expect(transformDelta(down, 'invert'), equals(up));
    });

    test('mirror_x flips horizontal only', () {
      expect(transformDelta(right, 'mirror_x'), equals(left));
      expect(transformDelta(left, 'mirror_x'), equals(right));
      expect(transformDelta(up, 'mirror_x'), equals(up));
      expect(transformDelta(down, 'mirror_x'), equals(down));
    });

    test('mirror_y flips vertical only', () {
      expect(transformDelta(up, 'mirror_y'), equals(down));
      expect(transformDelta(down, 'mirror_y'), equals(up));
      expect(transformDelta(right, 'mirror_y'), equals(right));
      expect(transformDelta(left, 'mirror_y'), equals(left));
    });
  });
}
