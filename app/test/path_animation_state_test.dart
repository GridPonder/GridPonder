import 'package:flutter_test/flutter_test.dart';
import 'package:gridponder_app/src/screens/path_animation_state.dart';
import 'package:gridponder_engine/engine.dart';

void main() {
  test('path animation preserves params of an earlier transformed entity', () {
    const markerPosition = Position(0, 0);
    final markers = BoardLayer.empty(2, 1)
      ..setAt(
        markerPosition,
        const EntityInstance('phase_a', {'variant': 'left'}),
      );
    final preState = LevelState(
      board: Board(
        width: 2,
        height: 1,
        layers: {'markers': markers, 'objects': BoardLayer.empty(2, 1)},
        multiCellObjects: const [],
      ),
      avatar: const AvatarState(enabled: false),
      variables: {},
    );
    final events = [
      GameEvent.cellTransformed(
        markerPosition,
        'phase_a',
        'phase_b',
        'markers',
      ),
      GameEvent.entityPathMoved(
        const [Position(0, 0), Position(1, 0)],
        'mover',
        removedAtEnd: true,
      ),
      GameEvent.cellTransformed(
        markerPosition,
        'phase_b',
        'phase_c',
        'markers',
      ),
    ];

    final animationState = buildPathAnimationState(preState, events);
    final animatedMarker = animationState.board.getEntity(
      'markers',
      markerPosition,
    )!;

    expect(animatedMarker.kind, 'phase_b');
    expect(animatedMarker.param('variant'), 'left');
    expect(
      preState.board.getEntity('markers', markerPosition)!.kind,
      'phase_a',
    );
  });
}
