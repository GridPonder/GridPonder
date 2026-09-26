import 'game_action.dart';

/// Solution data: gold path + hint stops.
class SolutionDef {
  final List<GameAction> goldPath;
  final List<int> hintStops;

  /// Frozen reference length for benchmark action allowances.
  /// Scoring and hints continue to use [goldPath].
  final int? benchmarkBudgetLength;

  const SolutionDef({
    required this.goldPath,
    this.hintStops = const [],
    this.benchmarkBudgetLength,
  }) : assert(benchmarkBudgetLength == null || benchmarkBudgetLength > 0);

  int get budgetPathLength => benchmarkBudgetLength ?? goldPath.length;

  factory SolutionDef.fromJson(Map<String, dynamic> j) {
    final budget = j['benchmarkBudgetLength'];
    if (budget != null && (budget is! int || budget <= 0)) {
      throw const FormatException(
          'solution.benchmarkBudgetLength must be a positive integer');
    }
    return SolutionDef(
      goldPath: (j['goldPath'] as List? ?? [])
          .map((e) => e is String
              ? GameAction.fromShorthand(e)
              : GameAction.fromJson(e as Map<String, dynamic>))
          .toList(),
      hintStops: List<int>.from(j['hintStops'] as List? ?? []),
      benchmarkBudgetLength: budget as int?,
    );
  }
}
