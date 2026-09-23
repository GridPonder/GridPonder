import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

// Mirrors the matching tests in engines/python/test_observation_prompt.py.

GameDefinition _game([Map<String, dynamic>? kinds]) => GameDefinition.fromJson({
      'id': 'shared_fixes',
      'title': 'Shared fixes',
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
      ],
      'entityKinds': kinds ??
          {
            'floor': {'layer': 'ground', 'symbol': '.', 'uiName': 'Floor'},
          },
      'actions': [
        {'id': 'wait', 'params': <String, dynamic>{}},
      ],
      'systems': [],
    }, id: 'shared_fixes');

LevelDefinition _level(GameDefinition game, List<Map<String, dynamic>> lose,
        {bool withGoal = false}) =>
    LevelDefinition.fromJson({
      'id': 'l',
      'board': {
        'size': [1, 1],
        'layers': <String, dynamic>{},
      },
      'state': {
        'avatar': {'enabled': false},
        'variables': {'score': 0, 'heat': 0},
      },
      'goals': withGoal
          ? [
              {
                'id': 'g',
                'type': 'variable_threshold',
                'config': {
                  'variable': 'score',
                  'comparison': 'gte',
                  'target': 0,
                },
              },
            ]
          : [],
      'loseConditions': lose,
    }, game.layers);

void main() {
  test('a turn that wins and breaks a lose condition is a loss', () {
    final game = _game();
    final engine = TurnEngine(
        game,
        _level(game, [
          {
            'type': 'variable_threshold',
            'config': {'variable': 'heat', 'comparison': 'gte', 'target': 0},
          },
        ], withGoal: true));
    final result = engine.executeTurn(const GameAction('wait'));
    expect(result.accepted, isTrue);
    expect(result.isLost, isTrue);
    expect(result.isWon, isFalse);
    expect(engine.isWon, isFalse);
  });

  test('winning on the last allowed move is still a win', () {
    final game = _game();
    final engine = TurnEngine(
        game,
        _level(game, [
          {
            'type': 'max_actions',
            'config': {'limit': 1},
          },
        ], withGoal: true));
    final result = engine.executeTurn(const GameAction('wait'));
    expect(result.isWon, isTrue);
    expect(result.isLost, isFalse);
  });

  test('text prompt states the coordinate convention once', () {
    final game = _game();
    final level = _level(game, []);
    final obs =
        AgentObservation.build(game, level, TurnEngine(game, level).state);
    final prompt = LlmAgent.buildPrompt(obs);
    expect('(0,0) is the top-left cell'.allMatches(prompt).length, 1);
    expect(prompt, contains('column x, row y'));
  });

  test('anonymous labels stay one character past 26 kinds', () {
    final kinds = <String, dynamic>{
      for (var i = 0; i < 70; i++)
        'k${i.toString().padLeft(2, '0')}': {
          'layer': 'ground',
          'symbol': String.fromCharCode(0x100 + i),
        },
      'floor': {'layer': 'ground', 'symbol': '.'},
    };
    final labels = buildAnonKindToLabel(_game(kinds));
    expect(labels.length, 70);
    expect(labels.values.every((l) => l.length == 1), isTrue);
    expect(labels.values.toSet().length, 70);
    expect(
        labels.values.toSet().intersection(
            {'.', '?', '@', '·', '=', '+', '(', ')', ',', ':'}),
        isEmpty);
  });

  test('an unparseable or unoffered reply is not replaced by an action', () {
    final game = _game();
    final level = _level(game, []);
    final obs =
        AgentObservation.build(game, level, TurnEngine(game, level).state);
    expect(obs.validActions, isNotEmpty);
    expect(LlmAgent.extractAction('no json here', obs), unrecognisedAction);
    expect(LlmAgent.extractAction('{"action": "jump"}', obs),
        unrecognisedAction);
    expect(LlmAgent.extractActionList('[{"action": "jump"}]', obs).$1,
        [unrecognisedAction]);
    expect(LlmAgent.extractAction('{"action": "wait"}', obs).actionId, 'wait');
  });
}
