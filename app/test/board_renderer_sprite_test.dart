import 'package:flutter_test/flutter_test.dart';
import 'package:gridponder_app/src/widgets/board_renderer.dart';
import 'package:gridponder_engine/engine.dart';

EntityKindDef _actorKind() => EntityKindDef.fromJson('wei', {
  'layer': 'actors',
  'tags': ['actor'],
  'symbol': 'W',
  'sprite': 'assets/actors/wei/idle_down.png',
  'motion': {
    'sprites': {
      'idle': {
        'up': 'assets/actors/wei/idle_up.png',
        'down': 'assets/actors/wei/idle_down.png',
        'left': 'assets/actors/wei/idle_left.png',
        'right': 'assets/actors/wei/idle_right.png',
      },
      'walk': {
        'right': [
          'assets/actors/wei/walk_right_1.png',
          'assets/actors/wei/walk_right_2.png',
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
        const EntityInstance('wei'),
        facingDirection: 'right',
      ),
      'assets/actors/wei/idle_right.png',
    );
  });

  test('resolves walk frame from temporary movement params', () {
    expect(
      resolveEntitySpritePath(
        _actorKind(),
        const EntityInstance('wei', {
          '_motionDirection': 'right',
          '_motionFrame': 1,
        }),
      ),
      'assets/actors/wei/walk_right_2.png',
    );
  });
}
