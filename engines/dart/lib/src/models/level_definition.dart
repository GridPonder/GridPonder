import 'board.dart';
import 'game_state.dart';
import 'goal.dart';
import 'layer.dart';
import 'rule.dart';
import 'solution.dart';

/// Parsed level JSON — one puzzle instance.
class LevelDefinition {
  final String id;
  final String? title;

  /// Optional short text shown in the guide panel to help the player understand
  /// the mechanics introduced in this level. Only displayed when the game has
  /// `ui.showGuide: true`.
  final String? guide;

  final Board _boardTemplate;
  final Map<String, dynamic> _stateJson;
  final List<GoalDef> goals;
  final List<LoseConditionDef> loseConditions;
  final List<RuleDef> rules;
  final Map<String, Map<String, dynamic>> systemOverrides;
  final SolutionDef solution;
  final Map<String, dynamic>? metadata;

  LevelDefinition({
    required this.id,
    this.title,
    this.guide,
    required Board boardTemplate,
    required Map<String, dynamic> stateJson,
    required this.goals,
    required this.loseConditions,
    required this.rules,
    required this.systemOverrides,
    required this.solution,
    this.metadata,
  })  : _boardTemplate = boardTemplate,
        _stateJson = stateJson;

  factory LevelDefinition.fromJson(
      Map<String, dynamic> j, List<LayerDef> layerDefs) {
    final board =
        Board.fromJson(j['board'] as Map<String, dynamic>, layerDefs);
    return LevelDefinition(
      id: j['id'] as String,
      title: j['title'] as String?,
      guide: j['guide'] as String?,
      boardTemplate: board,
      stateJson: Map<String, dynamic>.from(j['state'] as Map? ?? {}),
      goals: (j['goals'] as List? ?? [])
          .map((e) => GoalDef.fromJson(e as Map<String, dynamic>))
          .toList(),
      loseConditions: (j['loseConditions'] as List? ?? [])
          .map((e) => LoseConditionDef.fromJson(e as Map<String, dynamic>))
          .toList(),
      rules: (j['rules'] as List? ?? [])
          .map((e) => RuleDef.fromJson(e as Map<String, dynamic>))
          .toList(),
      systemOverrides: _parseOverrides(j['systemOverrides']),
      solution: j['solution'] != null
          ? SolutionDef.fromJson(j['solution'] as Map<String, dynamic>)
          : const SolutionDef(goldPath: []),
      metadata: j['metadata'] as Map<String, dynamic>?,
    );
  }

  static Map<String, Map<String, dynamic>> _parseOverrides(dynamic raw) {
    if (raw == null) return {};
    final map = raw as Map<String, dynamic>;
    return map.map((k, v) =>
        MapEntry(k, Map<String, dynamic>.from(v as Map)));
  }

  /// Creates a fresh initial level state from the board template + state JSON.
  LevelState initialState() =>
      LevelState.fromJson(_stateJson, _boardTemplate.copy());
}
