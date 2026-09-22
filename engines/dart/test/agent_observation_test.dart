import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

void main() {
  test('position parameters enumerate every board coordinate row-major', () {
    final game = GameDefinition.fromJson({
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
      ],
      'entityKinds': {
        'floor': {'layer': 'ground', 'symbol': '.'},
      },
      'actions': [
        {
          'id': 'tap_cell',
          'params': {
            'position': {'type': 'position'},
          },
        },
      ],
    }, id: 'position_action_test');
    final level = LevelDefinition.fromJson({
      'id': 'position_action_test',
      'board': {'size': [2, 2], 'layers': <String, dynamic>{}},
      'state': {'avatar': {'enabled': false}},
      'goals': <dynamic>[],
    }, game.layers);
    final engine = TurnEngine(game, level);

    final observation = AgentObservation.build(game, level, engine.state);

    expect(
      observation.validActions.map((action) => action.toJson()).toList(),
      [
        {
          'action': 'tap_cell',
          'position': [0, 0],
        },
        {
          'action': 'tap_cell',
          'position': [1, 0],
        },
        {
          'action': 'tap_cell',
          'position': [0, 1],
        },
        {
          'action': 'tap_cell',
          'position': [1, 1],
        },
      ],
    );
  });
}
