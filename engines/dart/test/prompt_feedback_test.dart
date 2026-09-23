// Parity mirror of the prompt features defined by the Python reference:
//   engines/python/test_goal_renderer.py  — target grid legend (C), balance
//     connectivity and override progress (D), loss reasons (F), index-0 labels
//   engines/python/test_observation.py    — status block (E), previous
//     attempt / rejected action / board-did-not-change feedback (F), and the
//     anonymous inventory line.
// Expected strings are the ones the Python tests assert.
import 'dart:convert';

import 'package:gridponder_engine/engine.dart';
import 'package:llm_dart/llm_dart.dart';
import 'package:test/test.dart';

/// Normalises a Dart literal to the types jsonDecode yields.
Map<String, dynamic> _j(Object o) =>
    jsonDecode(jsonEncode(o)) as Map<String, dynamic>;

GameDefinition _game(Map<String, dynamic> data) =>
    GameDefinition.fromJson(_j(data), id: data['id'] as String? ?? 'test');

LevelDefinition _level(GameDefinition game, Map<String, dynamic> data) =>
    LevelDefinition.fromJson(_j({'id': 'l', ...data}), game.layers);

// ── C. target grid ──────────────────────────────────────────────────────────

final _symbolGame = {
  'id': 'test_target_grid',
  'layers': [
    {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
    {'id': 'objects', 'occupancy': 'zero_or_one'},
    {'id': 'actors', 'occupancy': 'zero_or_one'},
  ],
  'entityKinds': {
    'floor': {'layer': 'ground', 'symbol': '.', 'uiName': 'Cut floor'},
    'rock': {'layer': 'ground', 'symbol': '#'},
    'pod': {'layer': 'objects', 'symbol': 'p', 'uiName': 'Landed Pod'},
    'digger': {'layer': 'actors', 'symbol': '1', 'uiName': 'Digger'},
  },
  'actions': [],
  'systems': [],
};

String _targetText(Map<String, dynamic> targetLayers,
    {String? mode, bool anon = false}) {
  final game = _game(_symbolGame);
  final level = _level(game, {
    'board': {
      'size': [3, 2],
      'layers': {},
    },
    'goals': [
      {
        'id': 'g',
        'type': 'board_match',
        'config': {
          'targetLayers': targetLayers,
          if (mode != null) 'matchMode': mode,
        },
      },
    ],
  });
  final state = TurnEngine(game, level).state;
  return LlmAgent.describeGoals(level, state, game,
      anonymize: anon,
      kindToLabel: anon ? buildAnonKindToLabel(game) : const {});
}

// ── D. balance ──────────────────────────────────────────────────────────────

Map<String, dynamic> _balanceGame({Map<String, String>? overrides}) => {
      'id': 'test_goal_renderer',
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
        {'id': 'territory', 'occupancy': 'zero_or_one'},
      ],
      'entityKinds': {
        'empty': {
          'layer': 'ground',
          'tags': ['walkable'],
          'symbol': '.'
        },
        'terr_wei': {
          'layer': 'territory',
          'uiName': 'Wei territory',
          'symbol': 'w'
        },
        'terr_shu': {
          'layer': 'territory',
          'uiName': 'Shu territory',
          'symbol': 's'
        },
        'terr_wu': {
          'layer': 'territory',
          'uiName': 'Wu territory',
          'symbol': 'u'
        },
      },
      'actions': [],
      'systems': [],
      if (overrides != null) 'goalDescriptions': overrides,
    };

// Wei holds (0,0),(1,0) and a cut-off (0,2); Shu holds (2,1),(2,2); Wu none.
const _connected = [
  [0, 0, 'terr_wei'],
  [1, 0, 'terr_wei'],
  [0, 2, 'terr_wei'],
  [2, 1, 'terr_shu'],
  [2, 2, 'terr_shu'],
];

Map<String, dynamic> _board(List<List<Object>> territory) => {
      'size': [3, 3],
      'layers': {
        'territory': {
          'format': 'sparse',
          'entries': [
            for (final t in territory)
              {
                'position': [t[0], t[1]],
                'kind': t[2]
              },
          ],
        },
      },
    };

Map<String, dynamic> _connectedGoal() => {
      'id': 'balance_goal',
      'type': 'balance',
      'config': {
        'layer': 'territory',
        'owners': ['terr_wei', 'terr_shu', 'terr_wu'],
        'claimableLayer': 'ground',
        'claimableKind': 'empty',
        'requireConnected': true,
        'connectionSources': {
          'terr_wei': [0, 0],
          'terr_shu': [2, 2],
          'terr_wu': [1, 1],
        },
      },
    };

String _goalText(Map<String, dynamic> gameData,
    List<Map<String, dynamic>> goals, List<List<Object>> territory,
    {bool anon = false, Map<String, int>? sequenceIndices}) {
  final game = _game(gameData);
  final level = _level(game, {'board': _board(territory), 'goals': goals});
  final state = TurnEngine(game, level).state;
  if (sequenceIndices != null) state.sequenceIndices.addAll(sequenceIndices);
  return LlmAgent.describeGoals(level, state, game,
      anonymize: anon,
      kindToLabel: anon ? buildAnonKindToLabel(game) : const {});
}

// ── E/F. status block and feedback ──────────────────────────────────────────

final _obsGame = {
  'id': 'obs',
  'layers': [
    {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
    {'id': 'actors', 'occupancy': 'zero_or_one'},
  ],
  'entityKinds': {
    'empty': {
      'layer': 'ground',
      'tags': ['walkable'],
      'symbol': '.'
    },
    'wall': {
      'layer': 'ground',
      'tags': ['solid'],
      'symbol': '#'
    },
    'red': {
      'layer': 'actors',
      'tags': ['actor'],
      'symbol': 'R',
      'uiName': 'Red piece'
    },
    'blue': {
      'layer': 'actors',
      'tags': ['actor'],
      'symbol': 'B',
      'uiName': 'Blue piece'
    },
  },
  'actions': [
    {
      'id': 'move',
      'params': {
        'direction': {
          'type': 'direction',
          'values': ['up', 'down', 'left', 'right']
        }
      }
    },
    {
      'id': 'tap_cell',
      'params': {
        'position': {'type': 'position'}
      }
    },
  ],
  'systems': [
    {
      'id': 'individual',
      'type': 'individual_actors',
      'enabled': false,
      'config': {
        'actorLayer': 'actors',
        'groundLayer': 'ground',
        'budgets': {'red': 3, 'blue': 2},
      },
    },
  ],
  'ui': {
    'readouts': [
      {'variable': 'heat', 'label': 'Heat', 'blankWhen': -1},
      {'variable': 'missing', 'label': 'Never shown'},
      {'variable': 'gauge', 'label': 'Gauge'},
    ],
  },
};

Map<String, dynamic> _obsLevel() => {
      'id': 'obs_01',
      'board': {
        'size': [3, 2],
        'layers': {
          'ground': {
            'format': 'sparse',
            'entries': [
              {
                'position': [2, 1],
                'kind': 'wall'
              }
            ]
          },
          'actors': {
            'format': 'sparse',
            'entries': [
              {
                'position': [0, 0],
                'kind': 'red'
              },
              {
                'position': [0, 1],
                'kind': 'blue'
              },
            ],
          },
        },
      },
      'state': {
        'avatar': {'enabled': false},
        'variables': {'heat': -1, 'gauge': 2.0},
      },
      'systemOverrides': {
        'individual': {'enabled': true}
      },
      'goals': [
        {
          'id': 'g',
          'type': 'reach_target',
          'config': {'targetKind': 'wall'}
        }
      ],
      'loseConditions': [
        {
          'type': 'max_actions',
          'config': {'limit': 11}
        }
      ],
    };

class _Obs {
  final GameDefinition game;
  final LevelDefinition level;
  final TurnEngine engine;
  _Obs(this.game, this.level, this.engine);

  List<String> status({bool anon = false}) =>
      LlmAgent.statusLines(game, level, engine.state,
              anonymize: anon,
              kindToLabel: anon ? buildAnonKindToLabel(game) : const {})
          .split('\n')
          .sublist(1);

  bool act(String id, Map<String, dynamic> params) =>
      engine.executeTurn(GameAction(id, params)).accepted;

  String prompt({
    GameAction? lastAction,
    String? previousBoardText,
    String? previousInventory,
    String? previousStatus,
    String? previousAttempt,
    Map<String, dynamic>? rejectedAction,
    String? rejectionDetail,
    String? lastActionLabel,
    bool anon = false,
  }) {
    final obs = AgentObservation.build(game, level, engine.state,
        lastAction: lastAction,
        previousBoardText: previousBoardText,
        previousInventory: previousInventory,
        previousStatus: previousStatus,
        kindSymbolOverrides: anon ? buildAnonKindToLabel(game) : null);
    return LlmAgent.buildPrompt(obs,
        anonymize: anon,
        previousAttempt: previousAttempt,
        rejectedAction: rejectedAction,
        rejectionDetail: rejectionDetail,
        lastActionLabel: lastActionLabel);
  }
}

_Obs _setup(
    {Map<String, dynamic>? levelPatch, Map<String, dynamic>? gamePatch}) {
  final game = _game({..._obsGame, ...?gamePatch});
  final level = _level(game, {..._obsLevel(), ...?levelPatch});
  return _Obs(game, level, TurnEngine(game, level));
}

/// A provider that always answers [reply].
class _FixedReply extends ChatCapability {
  final String reply;
  _FixedReply(this.reply);

  @override
  Future<ChatResponse> chatWithTools(
          List<ChatMessage> messages, List<Tool>? tools,
          {CancelToken? cancelToken}) =>
      throw UnimplementedError();

  @override
  Stream<ChatStreamEvent> chatStream(List<ChatMessage> messages,
      {List<Tool>? tools, CancelToken? cancelToken}) async* {
    yield TextDeltaEvent(reply);
  }
}

void main() {
  group('C. target grid', () {
    test('unconstrained cells are wildcards; required floor stays a dot', () {
      final text = _targetText({
        'ground': [
          ['floor', null, null],
          [null, null, null]
        ]
      });
      expect(text.split('\n').sublist(1), [
        '.??',
        '???',
        'Target legend: ?=any (unconstrained), .=Cut floor',
      ]);
    });

    test('exact mode keeps dots for cells that must be empty', () {
      final text = _targetText({
        'objects': [
          ['pod', null, null],
          [null, null, null]
        ]
      }, mode: 'exact');
      expect(text.split('\n').sublist(1), [
        'p..',
        '...',
        'Target legend: .=must be empty, p=Landed Pod',
      ]);
    });

    test('target legend names kinds absent from the board', () {
      final text = _targetText({
        'objects': [
          [null, null, null],
          [null, 'pod', null]
        ]
      });
      expect(text, contains('p=Landed Pod'));
    });

    test('composite cells show the top layer and list the rest', () {
      final text = _targetText({
        'ground': [
          ['floor', 'rock', null],
          [null, null, null]
        ],
        'actors': [
          ['digger', null, null],
          [null, null, null]
        ],
      });
      expect(text.split('\n').sublist(1), [
        '1#?',
        '???',
        'Target legend: ?=any (unconstrained), 1=Digger, #=rock',
        'Also required: (0,0) .=Cut floor',
      ]);
    });

    test('anonymous target legend lists labels only', () {
      final labels = buildAnonKindToLabel(_game(_symbolGame));
      final text = _targetText({
        'ground': [
          ['floor', null, null],
          [null, null, null]
        ],
        'actors': [
          ['digger', null, null],
          [null, null, 'digger']
        ],
      }, anon: true);
      final lines = text.split('\n');
      expect(lines[1], '${labels['digger']}??');
      expect(lines[3],
          'Target legend: ?=any (unconstrained), ${labels['digger']}');
      expect(labels.containsKey('floor'), isFalse);
      expect(lines[4], 'Also required: (0,0) .');
      for (final leak in [
        'Cut floor',
        'Landed Pod',
        'Digger',
        'floor',
        'digger'
      ]) {
        expect(text, isNot(contains(leak)));
      }
    });

    test('entry-form target cells render their kind', () {
      final text = _targetText({
        'objects': [
          [
            {'kind': 'pod', 'facing': 'up'},
            null,
            null
          ],
          [null, null, null]
        ]
      });
      expect(text.split('\n').sublist(1), [
        'p??',
        '???',
        'Target legend: ?=any (unconstrained), p=Landed Pod',
      ]);
    });

    test('entry-form target cells do not crash anonymous mode', () {
      final text = _targetText({
        'objects': [
          [
            {'kind': 'pod', 'facing': 'up'},
            null,
            null
          ],
          [null, null, null]
        ]
      }, anon: true);
      final label = buildAnonKindToLabel(_game(_symbolGame))['pod'];
      expect(text.split('\n')[1], '$label??');
    });
  });

  group('C. several goals', () {
    String multi(List<Map<String, dynamic>> goals, {bool anon = false}) {
      final game = _game(_symbolGame);
      final level = _level(game, {
        'board': {
          'size': [3, 2],
          'layers': {},
        },
        'goals': goals,
      });
      return LlmAgent.describeGoals(level, TurnEngine(game, level).state, game,
          anonymize: anon,
          kindToLabel: anon ? buildAnonKindToLabel(game) : const {});
    }

    final match = {
      'id': 'm',
      'type': 'board_match',
      'config': {
        'targetLayers': {
          'objects': [
            ['pod', null, null],
            [null, null, null]
          ]
        }
      },
    };
    final clear = {
      'id': 'c',
      'type': 'all_cleared',
      'config': {'kind': 'pod'}
    };
    final reach = {
      'id': 'r',
      'type': 'reach_target',
      'config': {'targetKind': 'pod'}
    };

    test('a goal after a target grid starts on its own line', () {
      for (final anon in [false, true]) {
        final lines = multi([match, clear], anon: anon).split('\n');
        expect(lines[3], startsWith('Target legend: '));
        expect(lines[3], isNot(contains(';')));
        expect(lines[4], startsWith('Clear all '));
        expect(lines, hasLength(5));
      }
    });

    test('consecutive target grids each end cleanly', () {
      final lines = multi([match, match, reach]).split('\n');
      expect(lines[3], isNot(contains(';')));
      expect(lines[4], startsWith('Arrange'));
      expect(lines[7], 'Target legend: ?=any (unconstrained), p=Landed Pod');
      expect(lines[8], 'Reach the Landed Pod');
    });

    test('single-line goals still join with semicolons', () {
      expect(multi([reach, clear]),
          'Reach the Landed Pod; Clear all Landed Pods from the board');
      expect(
          multi([reach, match]),
          startsWith('Reach the Landed Pod; '
              'Arrange tiles to match the target pattern:\n'));
      expect(LlmAgent.joinGoalParts([]), '');
      expect(LlmAgent.joinGoalParts(['a\nb', 'c', 'd']), 'a\nb\nc; d');
    });
  });

  group('D. balance connectivity and override progress', () {
    test('connected balance states connectivity and counts', () {
      expect(
          _goalText(_balanceGame(), [_connectedGoal()], _connected),
          "Claim every claimable cell, and give Wei territory, Shu territory and "
          "Wu territory an equal number each, and each owner's cells must connect "
          'orthogonally to its source cell [Wei territory (0,0), Shu territory (2,2), '
          'Wu territory (1,1)] (Wei territory 2/3 connected, Shu territory 2/2, '
          'Wu territory 0/0 — 5 of 9 claimed)');
    });

    test('connected balance, anonymous', () {
      final labels = buildAnonKindToLabel(_game(_balanceGame()));
      final w = labels['terr_wei'],
          s = labels['terr_shu'],
          u = labels['terr_wu'];
      expect(
          _goalText(_balanceGame(), [_connectedGoal()], _connected, anon: true),
          endsWith('source cell [$w (0,0), $s (2,2), $u (1,1)] '
              '($w 2/3 connected, $s 2/2, $u 0/0 — 5 of 9 claimed)'));
    });

    test('override keeps connected progress', () {
      expect(
          _goalText(
              _balanceGame(
                  overrides: {'balance_goal': 'Split it; stay connected.'}),
              [_connectedGoal()],
              _connected),
          'Split it; stay connected. (now: Wei territory 2/3 connected, '
          'Shu territory 2/2, Wu territory 0/0 — 5 of 9 claimed)');
    });

    test('override on a goal without progress is unchanged', () {
      expect(
          _goalText(
              _balanceGame(overrides: {'match_goal': 'Put Wei in the middle.'}),
              [
                {
                  'id': 'match_goal',
                  'type': 'board_match',
                  'config': {
                    'targetLayers': {
                      'territory': [
                        [null, null, null],
                        [null, 'terr_wei', null],
                        [null, null, null]
                      ]
                    }
                  }
                }
              ],
              _connected),
          'Put Wei in the middle.');
    });

    test('override on sequence_match appends done count', () {
      expect(
          _goalText(
              _balanceGame(overrides: {'seq': 'Merge 2, then 4.'}),
              [
                {
                  'id': 'seq',
                  'type': 'sequence_match',
                  'config': {
                    'sequence': [2, 4]
                  }
                }
              ],
              _connected,
              sequenceIndices: {'seq': 1}),
          'Merge 2, then 4. (now: 1/2 done)');
    });

    test('row and column 0 are not rendered as unknown', () {
      for (final (type, extra) in [
        ('sum_constraint', {'target': 5}),
        ('count_constraint', {'predicate': 'even', 'target': 1}),
      ]) {
        for (final (scope, word) in [('row', 'row'), ('col', 'column')]) {
          final text = _goalText(_balanceGame(), [
            {
              'id': 'c',
              'type': type,
              'config': {'scope': scope, 'index': 0, ...extra}
            }
          ], const []);
          expect(text, contains('$word 0'));
          expect(text, isNot(contains('?')));
        }
      }
    });
  });

  group('F. loss reasons', () {
    final game = _game(_balanceGame());
    LevelDefinition lose(List<Map<String, dynamic>> conditions) =>
        _level(game, {
          'board': _board(const []),
          'loseConditions': conditions,
        });
    final level = lose([
      {
        'type': 'max_actions',
        'config': {'limit': 11}
      },
      {
        'type': 'variable_threshold',
        'config': {'variable': 'heat', 'target': 3}
      },
      {'type': 'balance_budget_exhausted', 'config': {}},
      {'type': 'balance_unreachable', 'config': {}},
    ]);

    test('generic loss reasons', () {
      expect(LlmAgent.describeLoss(level, 'max_actions'),
          'move limit of 11 reached');
      expect(LlmAgent.describeLoss(level, 'variable_threshold:heat'),
          'loss condition "heat" reached');
      expect(LlmAgent.describeLoss(level, 'balance_budget_exhausted'),
          "a piece's remaining moves can no longer complete its share");
      expect(LlmAgent.describeLoss(level, 'balance_unreachable'),
          'the balance goal became unreachable');
    });

    test('anonymous loss reasons hide variable names', () {
      expect(
          LlmAgent.describeLoss(level, 'variable_threshold:heat',
              anonymize: true),
          'loss condition "#2" reached');
      expect(LlmAgent.describeLoss(level, 'max_actions', anonymize: true),
          'move limit of 11 reached');
    });

    test('lose condition description wins in named mode only', () {
      final described = lose([
        {
          'type': 'variable_threshold',
          'config': {'variable': 'heat', 'target': 3},
          'description': 'the boiler overheated',
        }
      ]);
      expect(LlmAgent.describeLoss(described, 'variable_threshold:heat'),
          'the boiler overheated');
      expect(
          LlmAgent.describeLoss(described, 'variable_threshold:heat',
              anonymize: true),
          'loss condition "#1" reached');
    });
  });

  group('E. status block', () {
    test('initial status block', () {
      expect(_setup().status(), [
        'Moves this attempt: 0 of 11 allowed (a tap that only selects is free)',
        'Selected: none',
        'Moves left: Red piece 3, Blue piece 2',
        'Heat: -',
        'Gauge: 2',
      ]);
    });

    test('selection and budget after moves', () {
      final o = _setup();
      expect(
          o.act('tap_cell', {
            'position': [0, 0]
          }),
          isTrue);
      expect(o.act('move', {'direction': 'right'}), isTrue);
      o.engine.state.variables['heat'] = 4;
      expect(o.status(), [
        'Moves this attempt: 1 of 11 allowed (a tap that only selects is free)',
        'Selected: Red piece at (1,0)',
        'Moves left: Red piece 2, Blue piece 2',
        'Heat: 4',
        'Gauge: 2',
      ]);
    });

    test('selection that no longer holds its piece', () {
      final o = _setup();
      o.act('tap_cell', {
        'position': [0, 0]
      });
      o.engine.state.board.setEntity('actors', const Position(0, 0), null);
      expect(o.status()[1],
          'Selected: none (the piece selected at (0,0) is gone or changed)');
    });

    test('anonymous status block uses labels', () {
      final o = _setup();
      final labels = buildAnonKindToLabel(o.game);
      o.act('tap_cell', {
        'position': [0, 1]
      });
      final lines = o.status(anon: true);
      expect(lines, [
        'Moves this attempt: 0 of 11 allowed (a tap that only selects is free)',
        'Selected: ${labels['blue']} at (0,1)',
        'Moves left: ${labels['red']} 3, ${labels['blue']} 2',
        'Readout 1: -',
        'Readout 3: 2',
      ]);
      expect(
          lines.any((l) => l.contains('piece') || l.contains('Heat')), isFalse);
    });

    test('system disabled and no max_actions keeps the old line', () {
      final o = _setup(levelPatch: {
        'systemOverrides': {},
        'loseConditions': [
          {
            'type': 'variable_threshold',
            'config': {'variable': 'heat', 'target': 9}
          }
        ],
      }, gamePatch: {
        'ui': {}
      });
      expect(o.status(), ['Moves this attempt: 0']);
    });

    test('readouts parsing drops malformed entries', () {
      final ui = GameUiConfig.fromJson(_j({
        'readouts': [
          {'variable': 'a', 'label': 'A', 'blankWhen': 0},
          {'label': 'no variable'},
          'not an object',
          {'variable': '', 'label': 'empty'},
          {'variable': 'b', 'label': 7, 'blankWhen': true},
        ],
      }));
      expect(ui.readouts.map((r) => [r.variable, r.label, r.color, r.blankWhen]),
          [
            ['a', 'A', null, 0],
            ['b', '', null, null],
          ]);
    });

    test('no lose conditions, no status', () {
      final o = _setup(
          levelPatch: {'systemOverrides': {}, 'loseConditions': []},
          gamePatch: {'ui': {}});
      expect(LlmAgent.statusLines(o.game, o.level, o.engine.state), '');
    });
  });

  group('F. prompt feedback', () {
    test('previous attempt line sits before CURRENT BOARD', () {
      final prompt =
          _setup().prompt(previousAttempt: 'lost — move limit of 11 reached');
      expect(
          prompt,
          contains('PREVIOUS ATTEMPT: lost — move limit of 11 reached\n'
              'CURRENT BOARD (first move of this attempt):\n'));
    });

    test('rejected action section', () {
      final o = _setup();
      final board = TextRenderer.render(o.engine.state, o.game);
      final prompt = o.prompt(
        lastAction: const GameAction('tap_cell', {
          'position': [0, 0]
        }),
        previousBoardText: 'irrelevant',
        rejectedAction: {'action': 'move', 'direction': 'up', 'memory': 'x'},
        rejectionDetail: 'move is not legal in this state',
      );
      expect(
          prompt,
          contains(
              'LAST ACTION: {"action": "move", "direction": "up"} — REJECTED '
              '(move is not legal in this state); no action was spent, the board is unchanged.\n'
              'CURRENT BOARD:\n$board\nMoves this attempt: 0 of 11 allowed'));
      expect(prompt, isNot(contains('BOARD BEFORE')));
      expect(prompt, isNot(contains('BOARD AFTER')));
    });

    test('anonymous last action echoes the submitted label', () {
      final o = _setup();
      final before = TextRenderer.render(o.engine.state, o.game,
          includeLegend: false,
          kindSymbolOverrides: buildAnonKindToLabel(o.game));
      o.act('tap_cell', {
        'position': [0, 0]
      });
      const tap = GameAction('tap_cell', {
        'position': [0, 0]
      });
      final prompt = o.prompt(
          anon: true,
          lastAction: tap,
          previousBoardText: before,
          lastActionLabel: 'a7');
      expect(prompt, contains('LAST ACTION: {"action": "a7"}\nBOARD BEFORE:'));
      final named = o.prompt(
          lastAction: tap, previousBoardText: 'x', lastActionLabel: 'a7');
      expect(
          named,
          contains(
              'LAST ACTION: {"action": "tap_cell", "position": [0, 0]}\n'));
    });

    test('an anonymous LlmAgent echoes the label it submitted', () async {
      final o = _setup();
      final agent = LlmAgent(
          provider: _FixedReply('{"action": "a2"}'),
          displayName: 'fixed',
          anonymize: true);
      GameAction? lastAction;
      AgentObservation obs() =>
          AgentObservation.build(o.game, o.level, o.engine.state,
              engine: o.engine,
              lastAction: lastAction,
              previousBoardText: lastAction == null ? null : 'x');
      final first = obs();
      final chosen = (await agent.act(first).last as AgentActCompleted)
          .result
          .actions
          .single;
      expect(buildAnonReverseMap(first.validActions)['a2'], chosen);
      expect(o.engine.executeTurn(chosen).accepted, isTrue);
      lastAction = chosen;
      final second = obs();
      // Re-tapping is no longer offered, so the new labels cannot name it.
      final now = buildAnonReverseMap(second.validActions)
          .entries
          .where((e) =>
              jsonEncode(e.value.toJson()) == jsonEncode(chosen.toJson()))
          .map((e) => e.key)
          .firstOrNull;
      expect(now, isNot('a2'));
      await agent.act(second).last;
      expect(agent.lastPrompt,
          contains('LAST ACTION: {"action": "a2"}\nBOARD BEFORE:'));
    });

    test('board did not change note', () {
      final o = _setup();
      o.act('tap_cell', {
        'position': [0, 1]
      });
      final before =
          TextRenderer.render(o.engine.state, o.game, includeLegend: false);
      final beforeStatus =
          LlmAgent.statusFingerprint(o.game, o.level, o.engine.state);
      // Blue moving down leaves the board: blocked, but accepted and counted.
      // Only the move counter changed, which is not a change to the board.
      expect(o.act('move', {'direction': 'down'}), isTrue);
      expect(o.engine.state.actionCount, 1);
      final prompt = o.prompt(
          lastAction: const GameAction('move', {'direction': 'down'}),
          previousBoardText: before,
          previousStatus: beforeStatus);
      expect(
          prompt,
          contains(
              'Moves this attempt: 1 of 11 allowed (a tap that only selects is free)\nSelected: Blue piece at (0,1)\n'
              'Moves left: Red piece 3, Blue piece 2\nHeat: -\nGauge: 2\n'
              'The board did not change.\n\nCompare the two boards'));
    });

    test('status fingerprint drops only the move counter', () {
      final o = _setup();
      expect(LlmAgent.statusFingerprint(o.game, o.level, o.engine.state),
          'Selected: none\nMoves left: Red piece 3, Blue piece 2\nHeat: -\nGauge: 2');
    });

    test('a selection change has no note', () {
      // Selecting redraws no cell, but `Selected:` changed: not "no change".
      final o = _setup();
      final before =
          TextRenderer.render(o.engine.state, o.game, includeLegend: false);
      final beforeStatus =
          LlmAgent.statusFingerprint(o.game, o.level, o.engine.state);
      o.act('tap_cell', {
        'position': [0, 0]
      });
      expect(TextRenderer.render(o.engine.state, o.game, includeLegend: false),
          before);
      const tap = GameAction('tap_cell', {
        'position': [0, 0]
      });
      final prompt = o.prompt(
          lastAction: tap,
          previousBoardText: before,
          previousStatus: beforeStatus);
      expect(prompt, contains('Selected: Red piece at (0,0)'));
      expect(prompt, isNot(contains('The board did not change.')));
      // Anonymous prompts decide the same way (labels are a bijection).
      final anonBefore = TextRenderer.render(o.engine.state, o.game,
          includeLegend: false,
          kindSymbolOverrides: buildAnonKindToLabel(o.game));
      final anon = o.prompt(
          lastAction: tap,
          previousBoardText: anonBefore,
          previousStatus: beforeStatus,
          anon: true);
      expect(anon, isNot(contains('The board did not change.')));
    });

    test('changed board has no note', () {
      final o = _setup();
      o.act('tap_cell', {
        'position': [0, 0]
      });
      final before =
          TextRenderer.render(o.engine.state, o.game, includeLegend: false);
      o.act('move', {'direction': 'right'});
      final prompt = o.prompt(
          lastAction: const GameAction('move', {'direction': 'right'}),
          previousBoardText: before);
      expect(prompt, isNot(contains('The board did not change.')));
    });

    test('anonymous inventory shows the label, not the kind', () {
      final game = _game({
        'id': 'inv',
        'layers': [
          {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
        ],
        'entityKinds': {
          'empty': {'layer': 'ground', 'symbol': '.'},
          'torch': {'layer': 'ground', 'symbol': 't', 'uiName': 'Torch'},
        },
        'actions': [
          {'id': 'wait'}
        ],
      });
      final level = _level(game, {
        'board': {
          'size': [2, 1],
          'layers': {},
        },
        'state': {
          'avatar': {
            'enabled': true,
            'position': [0, 0],
            'inventory': {'slot': 'torch'},
          },
        },
        'goals': [],
      });
      final o = _Obs(game, level, TurnEngine(game, level));
      final label = buildAnonKindToLabel(game)['torch'];
      expect(o.prompt(), contains('\nInventory: torch'));
      final board = TextRenderer.render(o.engine.state, game,
          includeLegend: false,
          kindSymbolOverrides: buildAnonKindToLabel(game));
      final anon = o.prompt(
          anon: true,
          lastAction: const GameAction('wait'),
          previousBoardText: board,
          previousInventory: 'torch');
      expect(anon, contains('\nInventory: $label'));
      expect(anon.toLowerCase(), isNot(contains('torch')));
    });
  });
}
