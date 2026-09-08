import 'package:flutter_test/flutter_test.dart';
import 'package:gridponder_app/src/screens/path_animation_state.dart';
import 'package:gridponder_engine/engine.dart';

void main() {
  test('path animation preserves params of an earlier transformed signal', () {
    const signalPosition = Position(0, 0);
    final markers = BoardLayer.empty(2, 1)
      ..setAt(
        signalPosition,
        const EntityInstance('signal_yellow_to_green', {'entrySide': 'left'}),
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
        signalPosition,
        'signal_yellow_to_green',
        'signal_green',
        'markers',
      ),
      GameEvent.entityPathMoved(
        const [Position(0, 0), Position(1, 0)],
        'car_blue',
        delivered: true,
      ),
      GameEvent.cellTransformed(
        signalPosition,
        'signal_green',
        'signal_yellow_to_red',
        'markers',
      ),
    ];

    final animationState = buildPathAnimationState(preState, events);
    final animatedSignal = animationState.board.getEntity(
      'markers',
      signalPosition,
    )!;

    expect(animatedSignal.kind, 'signal_green');
    expect(animatedSignal.param('entrySide'), 'left');
    expect(
      preState.board.getEntity('markers', signalPosition)!.kind,
      'signal_yellow_to_green',
    );
  });
}
