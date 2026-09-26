import 'package:test/test.dart';
import '../lib/src/models/solution.dart';

void main() {
  test('legacy budgets default to the gold path length', () {
    expect(
        SolutionDef.fromJson({
          'goldPath': ['right']
        }).budgetPathLength,
        1);
    expect(SolutionDef.fromJson({}).budgetPathLength, 0);
  });

  test('a shorter reference preserves a frozen benchmark allowance', () {
    final solution = SolutionDef.fromJson({
      'goldPath': ['right'],
      'benchmarkBudgetLength': 11,
    });
    expect(solution.goldPath.length, 1);
    expect(solution.budgetPathLength, 11);
  });

  test('invalid budget values fail when loading a level', () {
    for (final value in [true, false, 0, -1, 1.5, '11', [], {}]) {
      expect(
        () => SolutionDef.fromJson({'benchmarkBudgetLength': value}),
        throwsFormatException,
      );
    }
  });
}
