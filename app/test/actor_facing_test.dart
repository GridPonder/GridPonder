import 'package:flutter_test/flutter_test.dart';
import 'package:gridponder_app/src/animation/actor_facing.dart';
import 'package:gridponder_engine/engine.dart';

const _layerDefs = [
  LayerDef(id: 'ground', occupancy: 'exactly_one', defaultKind: 'floor'),
  LayerDef(id: 'actors', occupancy: 'zero_or_one'),
];

/// A 4x1 strip of machines, each entry `(x, facing)`; a null facing is left
/// out of the params.
LevelState _state(List<(int, String?)> machines) {
  final board = Board.fromJson({
    'size': [4, 1],
    'layers': {
      'actors': {
        'format': 'sparse',
        'entries': [
          for (final (x, facing) in machines)
            {
              'position': [x, 0],
              'kind': 'ram',
              if (facing != null) 'facing': facing,
            },
        ],
      },
    },
  }, _layerDefs);
  return LevelState(
    board: board,
    avatar: const AvatarState(enabled: false),
    variables: {},
  );
}

void main() {
  test('two machines of one kind keep their own facings', () {
    final state = _state([(0, 'left'), (3, 'right')]);
    final actors = state.board.layers['actors']!;

    expect(
      actorIdleFacing(
        actors.getAt(const Position(0, 0))!,
        const Position(0, 0),
        {},
      ),
      'left',
    );
    expect(
      actorIdleFacing(
        actors.getAt(const Position(3, 0))!,
        const Position(3, 0),
        {},
      ),
      'right',
    );
  });

  test('a move faces the mover the way it travelled, at its new cell only', () {
    final facing = facingAfterMoves(
      {const Position(0, 0): 'left'},
      [
        (
          from: const Position(0, 0),
          to: const Position(1, 0),
          direction: 'right',
        ),
      ],
    );

    expect(facing, {const Position(1, 0): 'right'});
  });

  test('a chain of movers keeps the arriving mover facing', () {
    // A leaves 1 for 2 while B arrives on 1 from 0.
    final facing = facingAfterMoves({}, [
      (
        from: const Position(1, 0),
        to: const Position(2, 0),
        direction: 'right',
      ),
      (
        from: const Position(0, 0),
        to: const Position(1, 0),
        direction: 'right',
      ),
    ]);

    expect(facing[const Position(1, 0)], 'right');
    expect(facing[const Position(2, 0)], 'right');
    expect(facing.containsKey(const Position(0, 0)), isFalse);
  });

  // The off-beat shaft member: it reverses on a beat it does not step, so no
  // animation ever turns it. Its last move had it facing right.
  test('a machine that reverses without moving turns', () {
    final pre = _state([(1, 'right')]);
    final post = _state([(1, 'left')]);

    final facing = facingAfterTurnsInPlace(
      {const Position(1, 0): 'right'},
      pre,
      post,
    );

    expect(facing[const Position(1, 0)], 'left');
  });

  // A chaser's authored facing is never rewritten by its behavior. Its moves
  // are the only record of which way it faces, and must win.
  test('an unchanged facing param never overrides a move', () {
    final state = _state([(1, 'right')]);

    final facing = facingAfterTurnsInPlace(
      {const Position(1, 0): 'left'},
      state,
      state,
    );

    expect(facing[const Position(1, 0)], 'left');
  });

  test('an entity without a cardinal facing param has no idle facing', () {
    expect(
      actorIdleFacing(const EntityInstance('ram'), const Position(0, 0), {}),
      isNull,
    );
    expect(
      actorIdleFacing(
        const EntityInstance('ram', {'facing': 'sideways'}),
        const Position(0, 0),
        {},
      ),
      isNull,
    );
  });
}
