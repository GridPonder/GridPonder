// Behavioural parity tests for the `individual_actors` system.
import 'package:gridponder_engine/engine.dart';
import 'package:test/test.dart';

GameDefinition _makeGame({Map<String, dynamic> config = const {}}) {
  final data = {
    'id': 'com.gridponder.test_individual_actors',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
      {'id': 'actors', 'occupancy': 'zero_or_one'},
      {'id': 'territory', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'empty': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': '.',
      },
      'wall': {
        'layer': 'ground',
        'tags': ['solid'],
        'symbol': '#',
      },
      'wei': {
        'layer': 'actors',
        'tags': ['actor'],
        'symbol': 'W',
      },
      'shu': {
        'layer': 'actors',
        'tags': ['actor'],
        'symbol': 'S',
      },
      'terr_wei': {
        'layer': 'territory',
        'tags': ['territory'],
        'symbol': '1',
      },
      'terr_shu': {
        'layer': 'territory',
        'tags': ['territory'],
        'symbol': '2',
      },
    },
    'actions': [
      {
        'id': 'move',
        'params': {
          'direction': {
            'type': 'direction',
            'values': ['up', 'down', 'left', 'right'],
          },
        },
      },
      {
        'id': 'tap_cell',
        'params': {
          'position': {'type': 'position'},
        },
      },
    ],
    'systems': [
      {
        'id': 'individual',
        'type': 'individual_actors',
        'config': {
          'claim': {
            'layer': 'territory',
            'map': {'wei': 'terr_wei', 'shu': 'terr_shu'},
          },
          ...config,
        },
      },
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_individual_actors');
}

GameDefinition _makeSwitchGame() {
  final data = {
    'id': 'com.gridponder.test_individual_actors_switch',
    'layers': [
      {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'empty'},
      {'id': 'actors', 'occupancy': 'zero_or_one'},
    ],
    'entityKinds': {
      'empty': {
        'layer': 'ground',
        'tags': ['walkable'],
        'symbol': '.',
      },
      'wall': {
        'layer': 'ground',
        'tags': ['solid'],
        'symbol': '#',
      },
      'wei': {
        'layer': 'actors',
        'tags': ['actor'],
        'symbol': 'W',
      },
      'shu': {
        'layer': 'actors',
        'tags': ['actor'],
        'symbol': 'S',
      },
    },
    'actions': [
      {
        'id': 'move',
        'params': {
          'direction': {
            'type': 'direction',
            'values': ['up', 'down', 'left', 'right'],
          },
        },
      },
      {
        'id': 'tap_cell',
        'params': {
          'position': {'type': 'position'},
        },
      },
    ],
    'systems': [
      {'id': 'coupled', 'type': 'coupled_actors', 'config': {}},
      {
        'id': 'individual',
        'type': 'individual_actors',
        'enabled': false,
        'config': {},
      },
    ],
  };
  return GameDefinition.fromJson(data, id: 'test_individual_actors_switch');
}

Map<String, dynamic> _makeLevel() => {
      'id': 'test_level',
      'board': {
        'size': [5, 1],
        'layers': {
          'ground': {'format': 'sparse', 'entries': []},
          'actors': {
            'format': 'sparse',
            'entries': [
              {
                'position': [1, 0],
                'kind': 'wei',
              },
              {
                'position': [3, 0],
                'kind': 'shu',
              },
            ],
          },
          'territory': {'format': 'sparse', 'entries': []},
        },
      },
      'state': {},
      'goals': [],
      'loseConditions': [],
    };

Map<String, dynamic> _makeBalanceBudgetLevel() => {
      'id': 'test_balance_budget_level',
      'board': {
        'size': [4, 1],
        'layers': {
          'ground': {'format': 'sparse', 'entries': []},
          'actors': {
            'format': 'sparse',
            'entries': [
              {
                'position': [0, 0],
                'kind': 'wei',
              },
              {
                'position': [3, 0],
                'kind': 'shu',
              },
            ],
          },
          'territory': {
            'format': 'sparse',
            'entries': [
              {
                'position': [0, 0],
                'kind': 'terr_wei',
              },
              {
                'position': [3, 0],
                'kind': 'terr_shu',
              },
            ],
          },
        },
      },
      'state': {},
      'goals': [
        {
          'id': 'balance_goal',
          'type': 'balance',
          'config': {
            'layer': 'territory',
            'owners': ['terr_wei', 'terr_shu'],
            'claimableLayer': 'ground',
            'claimableKind': 'empty',
            'requireComplete': true,
            'requireEqual': true,
          },
        },
      ],
      'loseConditions': [
        {
          'type': 'balance_budget_exhausted',
          'config': {'goalId': 'balance_goal'},
        },
      ],
    };

TurnEngine _engineFor(GameDefinition game, Map<String, dynamic> levelJson) {
  final level = LevelDefinition.fromJson(levelJson, game.layers);
  return TurnEngine(game, level);
}

Position? _actorPos(TurnEngine engine, String kind) {
  for (final entry in engine.state.board.layers['actors']!.entries()) {
    if (entry.value.kind == kind) return entry.key;
  }
  return null;
}

String? _territoryKind(TurnEngine engine, Position pos) =>
    engine.state.board.getEntity('territory', pos)?.kind;

void main() {
  test('tap selects actor and move moves only selected actor', () {
    final game = _makeGame();
    final engine = _engineFor(game, _makeLevel());

    final selected = engine.executeTurn(GameAction('tap_cell', {
      'position': [1, 0],
    }));
    final moved = engine.executeTurn(GameAction('move', {
      'direction': 'right',
    }));

    expect(selected.accepted, isTrue);
    expect(moved.accepted, isTrue);
    expect(engine.state.variables['selectedActorKind'], equals('wei'));
    expect(_actorPos(engine, 'wei'), equals(const Position(2, 0)));
    expect(_actorPos(engine, 'shu'), equals(const Position(3, 0)));
    expect(_territoryKind(engine, const Position(2, 0)), equals('terr_wei'));
    expect(
      selected.events
          .where((e) => e.type.startsWith('actor_'))
          .map((e) => e.type),
      equals(['actor_selected']),
    );
    expect(
      moved.events.where((e) => e.type.startsWith('actor_')).map((e) => e.type),
      equals(['actor_moved', 'actor_entered']),
    );
  });

  test('move is rejected when selected actor budget is exhausted', () {
    final game = _makeGame(config: {
      'budgets': {'wei': 0, 'shu': 2},
    });
    final engine = _engineFor(game, _makeLevel());

    final selected = engine.executeTurn(GameAction('tap_cell', {
      'position': [1, 0],
    }));
    final moved = engine.executeTurn(GameAction('move', {
      'direction': 'right',
    }));

    expect(selected.accepted, isTrue);
    expect(moved.accepted, isFalse);
    expect(_actorPos(engine, 'wei'), equals(const Position(1, 0)));
    expect(
      (engine.state.variables['actorMovesRemaining'] as Map)['wei'],
      equals(0),
    );
  });

  test('selection identifies one actor when kinds are duplicated', () {
    final game = _makeGame();
    final level = _makeLevel();
    final entries = (((level['board'] as Map)['layers'] as Map)['actors']
        as Map)['entries'] as List;
    entries
      ..clear()
      ..addAll(<Map<String, Object>>[
        {
          'position': [0, 0],
          'kind': 'wei',
        },
        {
          'position': [3, 0],
          'kind': 'wei',
        },
      ]);
    final engine = _engineFor(game, level);

    engine.executeTurn(GameAction('tap_cell', {
      'position': [0, 0],
    }));
    final moved = engine.executeTurn(GameAction('move', {
      'direction': 'right',
    }));

    expect(moved.accepted, isTrue);
    expect(
      engine.state.board.getEntity('actors', const Position(1, 0))?.kind,
      'wei',
    );
    expect(
      engine.state.board.getEntity('actors', const Position(3, 0))?.kind,
      'wei',
    );
  });

  test('balance budget condition is inactive without configured budgets', () {
    final game = _makeGame();
    final engine = _engineFor(game, _makeBalanceBudgetLevel());

    final result = engine.executeTurn(GameAction('tap_cell', {
      'position': [3, 0],
    }));

    expect(result.accepted, isTrue);
    expect(result.isLost, isFalse);
  });

  test('explicit empty actorToOwner disables budget inference', () {
    final game = _makeGame(config: {
      'budgets': {'wei': 0, 'shu': 0},
    });
    final level = _makeBalanceBudgetLevel();
    ((level['loseConditions'] as List).single as Map)['config'] = {
      'goalId': 'balance_goal',
      'actorToOwner': <String, String>{},
    };
    final engine = _engineFor(game, level);

    final result = engine.executeTurn(GameAction('tap_cell', {
      'position': [3, 0],
    }));

    expect(result.accepted, isTrue);
    expect(result.isLost, isFalse);
  });

  test('balance budget exhausted loses when actor still needs claims', () {
    final game = _makeGame(config: {
      'budgets': {'wei': 0, 'shu': 1},
    });
    final engine = _engineFor(game, _makeBalanceBudgetLevel());

    final result = engine.executeTurn(GameAction('tap_cell', {
      'position': [3, 0],
    }));

    expect(result.accepted, isTrue);
    expect(result.isLost, isTrue);
    expect(result.loseReason, equals('balance_budget_exhausted'));
  });

  test('balance budget exhausted allows actor at target with zero budget', () {
    final game = _makeGame(config: {
      'budgets': {'wei': 0, 'shu': 1},
    });
    final level = _makeBalanceBudgetLevel();
    ((level['board'] as Map)['layers'] as Map)['territory']['entries'].add({
      'position': [1, 0],
      'kind': 'terr_wei',
    });
    final engine = _engineFor(game, level);

    final result = engine.executeTurn(GameAction('tap_cell', {
      'position': [3, 0],
    }));

    expect(result.accepted, isTrue);
    expect(result.isLost, isFalse);
  });

  test('level overrides can switch from coupled to individual movement', () {
    final game = _makeSwitchGame();
    final level = _makeLevel()
      ..['systemOverrides'] = {
        'coupled': {'enabled': false},
        'individual': {'enabled': true},
      };
    final engine = _engineFor(game, level);

    engine.executeTurn(GameAction('tap_cell', {
      'position': [1, 0],
    }));
    final moved = engine.executeTurn(GameAction('move', {
      'direction': 'right',
    }));

    expect(moved.accepted, isTrue);
    expect(_actorPos(engine, 'wei'), equals(const Position(2, 0)));
    expect(_actorPos(engine, 'shu'), equals(const Position(3, 0)));
  });
}
