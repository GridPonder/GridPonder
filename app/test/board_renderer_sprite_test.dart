import 'package:flutter_test/flutter_test.dart';
import 'package:gridponder_app/src/widgets/board_renderer.dart';
import 'package:gridponder_engine/engine.dart';

EntityKindDef _actorKind() => EntityKindDef.fromJson('test_actor', {
  'layer': 'actors',
  'tags': ['actor'],
  'symbol': 'W',
  'sprite': 'assets/actors/test_actor/idle_down.png',
  'motion': {
    'sprites': {
      'idle': {
        'up': 'assets/actors/test_actor/idle_up.png',
        'down': 'assets/actors/test_actor/idle_down.png',
        'left': 'assets/actors/test_actor/idle_left.png',
        'right': 'assets/actors/test_actor/idle_right.png',
      },
      'walk': {
        'right': [
          'assets/actors/test_actor/walk_right_1.png',
          'assets/actors/test_actor/walk_right_2.png',
        ],
      },
    },
  },
});

void main() {
  test('resolves static sprite when no motion sprites are active', () {
    final kind = EntityKindDef.fromJson('wall', {
      'layer': 'ground',
      'tags': ['solid'],
      'symbol': '#',
      'sprite': 'assets/wall.png',
    });

    expect(
      resolveEntitySpritePath(kind, const EntityInstance('wall')),
      'assets/wall.png',
    );
  });

  test('resolves idle sprite from remembered facing direction', () {
    expect(
      resolveEntitySpritePath(
        _actorKind(),
        const EntityInstance('test_actor'),
        facingDirection: 'right',
      ),
      'assets/actors/test_actor/idle_right.png',
    );
  });

  test('resolves walk frame from temporary movement params', () {
    expect(
      resolveEntitySpritePath(
        _actorKind(),
        const EntityInstance('test_actor', {
          '_motionDirection': 'right',
          '_motionFrame': 1,
        }),
      ),
      'assets/actors/test_actor/walk_right_2.png',
    );
  });
}
