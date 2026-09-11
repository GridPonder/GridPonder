import 'dart:ui';

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

  test('uses elapsed time for motion frames when configured', () {
    final kind = EntityKindDef.fromJson('cinder', {
      'layer': 'actors',
      'tags': ['npc'],
      'symbol': '&',
      'sprite': 'assets/cinder.png',
      'motion': {'frameDurationMs': 100},
    });

    expect(resolveEntityMotionFrame(kind, 0, 0), 0);
    expect(resolveEntityMotionFrame(kind, 99, 0.25), 0);
    expect(resolveEntityMotionFrame(kind, 100, 0.25), 1);
    expect(resolveEntityMotionFrame(kind, 399, 0.99), 3);
    expect(resolveEntityMotionFrame(kind, 400, 1), 4);
  });

  test('motion frames retain the legacy per-cell fallback', () {
    final kind = EntityKindDef.fromJson('crate', {
      'layer': 'objects',
      'tags': ['solid'],
      'symbol': 'C',
      'sprite': 'assets/crate.png',
    });

    expect(resolveEntityMotionFrame(kind, 399, 2.75), 2);
  });

  test('resolves a pack-local avatar fallback sprite', () {
    final theme = AvatarThemeDef.fromJson({
      'visible': true,
      'sprite': 'assets/sprites/alien.png',
    });

    expect(resolveAvatarSpriteChoice(theme, 'right'), (
      visible: true,
      path: 'assets/sprites/alien.png',
      mirrorHorizontally: false,
    ));
  });

  test('honors hidden and mirrored avatar theme entries', () {
    final hidden = AvatarThemeDef.fromJson({'visible': false});
    expect(resolveAvatarSpriteChoice(hidden, 'left'), (
      visible: false,
      path: null,
      mirrorHorizontally: false,
    ));

    final mirrored = AvatarThemeDef.fromJson({
      'sprites': {
        'idle': {
          'right': 'assets/sprites/alien_right.png',
          'left': {'mirror': 'right'},
        },
      },
    });
    expect(resolveAvatarSpriteChoice(mirrored, 'left'), (
      visible: true,
      path: 'assets/sprites/alien_right.png',
      mirrorHorizontally: true,
    ));
  });

  test('selects directional avatar walk frames while moving', () {
    final theme = AvatarThemeDef.fromJson({
      'sprites': {
        'idle': {'right': 'assets/avatar/idle_right.png'},
        'walk': {
          'right': {
            'frames': [
              'assets/avatar/walk_right_1.png',
              'assets/avatar/walk_right_2.png',
            ],
            'duration': 220,
            'mode': 'loop',
          },
        },
      },
    });

    expect(
      resolveAvatarSpriteChoice(theme, 'right', moving: true, progress: 0.2),
      (
        visible: true,
        path: 'assets/avatar/walk_right_1.png',
        mirrorHorizontally: false,
      ),
    );
    expect(
      resolveAvatarSpriteChoice(theme, 'right', moving: true, progress: 0.8),
      (
        visible: true,
        path: 'assets/avatar/walk_right_2.png',
        mirrorHorizontally: false,
      ),
    );
    expect(resolveAvatarSpriteChoice(theme, 'right'), (
      visible: true,
      path: 'assets/avatar/idle_right.png',
      mirrorHorizontally: false,
    ));
  });

  test('renders board layers in the order declared by the pack', () {
    final game = GameDefinition.fromJson({
      'layers': [
        {'id': 'ground', 'occupancy': 'exactly_one', 'default': 'floor'},
        {'id': 'territory', 'occupancy': 'zero_or_one'},
        {'id': 'markers', 'occupancy': 'zero_or_one'},
        {'id': 'objects', 'occupancy': 'zero_or_one'},
      ],
    });

    expect(resolveBoardLayerOrder(game), [
      'ground',
      'territory',
      'markers',
      'objects',
    ]);
  });

  test('elastic face reaches a crate before the crate starts moving', () {
    expect(
      elasticPushObjectTravel(
        blockTravel: 1.5,
        totalBlockDistance: 4,
        objectDistance: 2,
      ),
      0,
    );
    expect(
      elasticPushObjectTravel(
        blockTravel: 2.5,
        totalBlockDistance: 4,
        objectDistance: 2,
      ),
      0.5,
    );
    expect(
      elasticPushObjectTravel(
        blockTravel: 4,
        totalBlockDistance: 4,
        objectDistance: 2,
      ),
      2,
    );
  });

  test('elastic block grows only its leading edge', () {
    const start = Rect.fromLTRB(2, 3, 4, 5);

    expect(
      elasticBlockRect(start, 'right', 1.25),
      const Rect.fromLTRB(2, 3, 5.25, 5),
    );
    expect(
      elasticBlockRect(start, 'up', 0.75),
      const Rect.fromLTRB(2, 2.25, 4, 5),
    );
  });

  test('elastic block collapse interpolates the trailing edge', () {
    const start = Rect.fromLTRB(1, 2, 7, 5);
    const end = Rect.fromLTRB(6, 2, 7, 5);

    expect(
      elasticBlockRectTween(start, end, 0.5),
      const Rect.fromLTRB(3.5, 2, 7, 5),
    );
    expect(elasticBlockRectTween(start, end, 1), end);
  });
}
