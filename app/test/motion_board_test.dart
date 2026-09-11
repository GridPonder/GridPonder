import 'package:flutter_test/flutter_test.dart';
import 'package:gridponder_app/src/animation/motion_board.dart';
import 'package:gridponder_engine/engine.dart';

const _layerDefs = [
  LayerDef(id: 'ground', occupancy: 'exactly_one', defaultKind: 'brush'),
  LayerDef(id: 'actors', occupancy: 'zero_or_one'),
];

/// A 4x1 strip: the avatar at [avatarX], one Cinder at [actorX], and [burnt]
/// cells turned to ember.
LevelState _state({
  required int avatarX,
  required int actorX,
  Set<int> burnt = const {},
}) {
  final board = Board.fromJson({
    'size': [4, 1],
    'layers': {
      'ground': [
        [for (var x = 0; x < 4; x++) burnt.contains(x) ? 'ember' : 'brush'],
      ],
      'actors': {
        'format': 'sparse',
        'entries': [
          {
            'position': [actorX, 0],
            'kind': 'cinder',
          },
        ],
      },
    },
  }, _layerDefs);

  return LevelState(
    board: board,
    avatar: AvatarState(enabled: true, position: Position(avatarX, 0)),
    variables: {},
  );
}

TravellingEntity _cinder(int fromX, int toX) => TravellingEntity(
  from: Position(fromX, 0),
  to: Position(toX, 0),
  layer: 'actors',
  entity: const EntityInstance('cinder'),
);

String? _actorAt(LevelState s, int x) =>
    s.board.getEntity('actors', Position(x, 0))?.kind;

String? _groundAt(LevelState s, int x) =>
    s.board.getEntity('ground', Position(x, 0))?.kind;

void main() {
  group('boardDuringMotion', () {
    // The regression this module exists for. On a Firebreak turn the avatar
    // walks (stage 0) and the Cinder walks (a later stage). The board shown
    // while the Cinder animated used to be rebuilt from the *pre-turn* state,
    // which rewound the avatar and the fire along with it.
    test('does not rewind the avatar while a later mover is in flight', () {
      final post = _state(avatarX: 1, actorX: 3, burnt: {2, 3});
      final shown = boardDuringMotion(post, inFlight: [_cinder(2, 3)]);

      expect(
        shown.avatar.position,
        const Position(1, 0),
        reason: 'the avatar has already walked; it must not hop back',
      );
    });

    test('does not rewind terrain while a later mover is in flight', () {
      final post = _state(avatarX: 1, actorX: 3, burnt: {2, 3});
      final shown = boardDuringMotion(post, inFlight: [_cinder(2, 3)]);

      expect(_groundAt(shown, 2), 'ember');
      expect(
        _groundAt(shown, 3),
        'ember',
        reason: 'fire that has already spread must not un-burn',
      );
    });

    test('lifts an in-flight mover off the board entirely', () {
      final post = _state(avatarX: 1, actorX: 3);
      final shown = boardDuringMotion(post, inFlight: [_cinder(2, 3)]);

      expect(
        _actorAt(shown, 3),
        isNull,
        reason: 'the sprite in flight is the only copy that should render',
      );
      expect(_actorAt(shown, 2), isNull);
    });

    // The other half of the same bug: before its stage ran, a mover was drawn
    // at its destination, so it teleported there during the avatar's step and
    // then snapped back to slide the distance a second time.
    test('holds a pending mover at its origin until its stage runs', () {
      final post = _state(avatarX: 1, actorX: 3);
      final shown = boardDuringMotion(post, pending: [_cinder(2, 3)]);

      expect(
        _actorAt(shown, 2),
        'cinder',
        reason: 'it has not moved yet, so it belongs on its origin',
      );
      expect(_actorAt(shown, 3), isNull);
    });

    test('with nothing travelling it is the finished board', () {
      final post = _state(avatarX: 1, actorX: 3, burnt: {2, 3});
      final shown = boardDuringMotion(post);

      expect(shown.avatar.position, const Position(1, 0));
      expect(_actorAt(shown, 3), 'cinder');
      expect(_groundAt(shown, 2), 'ember');
    });

    test('one mover into the cell another is leaving resolves both', () {
      // A moved 0->1 while B moved 1->2, so in the finished board they sit on
      // 1 and 2. Clearing destinations before placing origins is what keeps
      // this from depending on which one is handled first.
      final post = _state(avatarX: 3, actorX: 1);
      post.board.setEntity(
        'actors',
        const Position(2, 0),
        const EntityInstance('cinder'),
      );

      final shown = boardDuringMotion(
        post,
        pending: [_cinder(1, 2), _cinder(0, 1)],
      );

      expect(_actorAt(shown, 0), 'cinder', reason: 'A is still at its origin');
      expect(_actorAt(shown, 1), 'cinder', reason: 'B is still at its origin');
      expect(_actorAt(shown, 2), isNull, reason: 'nobody has arrived yet');
    });

    test('leaves the source state untouched', () {
      final post = _state(avatarX: 1, actorX: 3);
      boardDuringMotion(post, inFlight: [_cinder(2, 3)]);

      expect(
        _actorAt(post, 3),
        'cinder',
        reason: 'callers keep the engine state; it must not be mutated',
      );
    });
  });
}
