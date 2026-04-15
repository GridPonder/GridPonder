import 'game_action.dart';

/// Solution data: gold path + hint stops.
class SolutionDef {
  final List<GameAction> goldPath;
  final List<int> hintStops;

  const SolutionDef({required this.goldPath, this.hintStops = const []});

  factory SolutionDef.fromJson(Map<String, dynamic> j) => SolutionDef(
        goldPath: (j['goldPath'] as List? ?? [])
            .map((e) => GameAction.fromJson(e as Map<String, dynamic>))
            .toList(),
        hintStops: List<int>.from(j['hintStops'] as List? ?? []),
      );
}
