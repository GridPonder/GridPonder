import 'package:gridponder_engine/engine.dart';
import 'package:gridponder_engine/src/engine/goal_evaluator.dart';
import 'package:test/test.dart';

void main() {
  final game = GameDefinition.fromJson({
    'layers': [
      {'id': 'objects', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'cell': {
        'layer': 'objects',
        'tags': <String>[],
        'symbol': 'C',
        'params': {
          'charge': {'type': 'integer'}
        },
      },
    },
    'actions': <dynamic>[],
    'systems': <dynamic>[],
  }, id: 'board_match_params_test');
  final board = Board.fromJson({
    'size': [2, 1],
    'layers': {
      'objects': [
        [
          {'kind': 'cell', 'charge': 1},
          {'kind': 'cell', 'charge': 2},
        ],
      ],
    },
  }, game.layers);
  final state = LevelState.fromJson(const {}, board);

  GoalStatus evaluate(List<dynamic> target, {List<String>? matchParams}) {
    final config = <String, dynamic>{
      'targetLayers': {
        'objects': [target]
      },
      'matchMode': 'exact',
      if (matchParams != null) 'matchParams': matchParams,
    };
    final goal = GoalDef.fromJson({
      'id': 'target',
      'type': 'board_match',
      'config': config,
    });
    return GoalEvaluator().evaluate([goal], state, game, const []);
  }

  test('kind-only behavior is unchanged when matchParams is absent', () {
    final result = evaluate([
      {'kind': 'cell', 'charge': 9},
      {'kind': 'cell', 'charge': 9},
    ]);
    expect(result.isWon, isTrue);
    expect(result.progress['target'], 1.0);
  });

  test('selected param must match exactly', () {
    final result = evaluate([
      {'kind': 'cell', 'charge': 1},
      {'kind': 'cell', 'charge': 9},
    ], matchParams: [
      'charge'
    ]);
    expect(result.isWon, isFalse);
    expect(result.progress['target'], 0.5);
  });

  test('target must name every selected param', () {
    final result = evaluate([
      {'kind': 'cell', 'charge': 1},
      {'kind': 'cell'},
    ], matchParams: [
      'charge'
    ]);
    expect(result.isWon, isFalse);
    expect(result.progress['target'], 0.5);
  });
}
