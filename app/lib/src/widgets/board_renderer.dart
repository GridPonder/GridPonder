import 'dart:math';
import 'package:flutter/material.dart';
import 'package:gridponder_engine/engine.dart';
import '../services/pack_service.dart';

/// Resolves a colour name (e.g. "red") to a Color. Pack themes can override
/// or extend the built-in palette via theme.json's `palette` block; any name
/// the pack doesn't declare falls back to the canonical defaults below. The
/// defaults are chosen to be clearly distinguishable from each other and
/// from black (void), and to work on a light background.
Color cellNamedColor(String name, {Map<String, String>? palette}) {
  final hex = palette?[name];
  if (hex != null) {
    final parsed = _parsePaletteHex(hex);
    if (parsed != null) return parsed;
  }
  return switch (name) {
    'red' => const Color(0xFFE53935),
    'blue' => const Color(0xFF1E88E5),
    'green' => const Color(0xFF43A047),
    'yellow' => const Color(0xFFFFD600),
    'orange' => const Color(0xFFFB8C00),
    'purple' => const Color(0xFF8E24AA),
    'lime' => const Color(0xFF7CB342),
    'teal' => const Color(0xFF00897B),
    'pink' => const Color(0xFFE91E63),
    _ => const Color(0xFF9E9E9E),
  };
}

Color? _parsePaletteHex(String hex) {
  var s = hex.trim();
  if (s.startsWith('#')) s = s.substring(1);
  if (s.length == 6) s = 'FF$s';
  if (s.length != 8) return null;
  final v = int.tryParse(s, radix: 16);
  return v == null ? null : Color(v);
}

class LineOfSightFeedback {
  final Position source;
  final Position target;
  final String kind;

  const LineOfSightFeedback({
    required this.source,
    required this.target,
    required this.kind,
  });
}

/// Resolves the sprite path for an entity instance, including optional
/// direction-aware motion sprites declared under `motion.sprites`.
String? resolveEntitySpritePath(
  EntityKindDef? kindDef,
  EntityInstance entity, {
  String? facingDirection,
}) {
  final sprite = kindDef?.sprite;
  if (sprite == null) return null;

  final motionSprite = _motionSpritePath(
    kindDef!.motion,
    entity,
    facingDirection: facingDirection,
  );
  if (motionSprite != null) return motionSprite;

  final spriteParam = kindDef.spriteParam;
  if (spriteParam == null) return sprite;
  final value = entity.param(spriteParam);
  return sprite.replaceAll('{$spriteParam}', value?.toString() ?? '0');
}

String? _motionSpritePath(
  Map<String, dynamic> motion,
  EntityInstance entity, {
  String? facingDirection,
}) {
  final sprites = motion['sprites'];
  if (sprites is! Map) return null;

  final movementDirection = entity.param('_motionDirection');
  if (movementDirection is String) {
    final walk = sprites['walk'];
    final frames = walk is Map ? walk[movementDirection] : null;
    if (frames is List && frames.isNotEmpty) {
      final rawFrame = entity.param('_motionFrame');
      final frame = rawFrame is int ? rawFrame : 0;
      return frames[frame % frames.length] as String?;
    }
  }

  if (facingDirection != null) {
    final idle = sprites['idle'];
    final frame = idle is Map ? idle[facingDirection] : null;
    if (frame is String) return frame;
  }

  return null;
}

class BoardRenderer extends StatelessWidget {
  final LevelState state;
  final GameDefinition game;
  final PackService packService;
  /// Optional overlay sprites rendered on top of the objects layer, used during
  /// entity destruction animations. Maps cell position → DSL sprite path.
  /// Resolved pack-first then gridponder-base, matching static sprite behaviour.
  final Map<Position, String>? animationOverlays;
  /// Called when the user taps/clicks a cell. Enables tap-to-act gestures.
  final void Function(int x, int y)? onCellTap;

  /// Last known facing direction per actor kind. Used to render idle actor
  /// sprites after movement animation has finished.
  final Map<String, String> actorFacingByKind;

  /// When set, cell_flooded entities are rendered in this color instead of
  /// their default color — used by Flood Colors to show the last chosen color.
  final Color? floodedColorOverride;
  /// When set, the avatar is rendered at this position instead of
  /// state.avatar.position — used during ice slide animations.
  final Position? avatarPositionOverride;

  /// UI-only selection state for direct-manipulation multi-cell objects.
  final String? selectedMultiCellObjectId;

  /// UI-only selection state for an individually controlled actor.
  final Position? selectedActorPosition;

  /// Short-lived visual feedback for a line-of-sight detection event.
  final List<LineOfSightFeedback> lineOfSightFeedbacks;

  const BoardRenderer({
    super.key,
    required this.state,
    required this.game,
    required this.packService,
    this.animationOverlays,
    this.onCellTap,
    this.actorFacingByKind = const {},
    this.floodedColorOverride,
    this.avatarPositionOverride,
    this.selectedMultiCellObjectId,
    this.selectedActorPosition,
    this.lineOfSightFeedbacks = const [],
  });

  @override
  Widget build(BuildContext context) {
    final board = state.board;
    final cols = board.width;
    final rows = board.height;

    return LayoutBuilder(
      builder: (context, constraints) {
        final cellSize = (constraints.maxWidth / cols)
            .clamp(15.0, 70.0)
            .clamp(0.0, constraints.maxHeight / rows);

        final gridWidth = cellSize * cols;
        final gridHeight = cellSize * rows;

        // Background structures such as pipes stay below cell layers. Physical
        // sliding blocks render above them so covered objects remain hidden.
        final backgroundMcos = state.board.multiCellObjects
            .where((mco) => !game.hasTag(mco.kind, 'sliding_block'))
            .toList();
        final foregroundMcos = state.board.multiCellObjects
            .where((mco) => game.hasTag(mco.kind, 'sliding_block'))
            .toList();

        // Background structures replace the ground tile (for example pipes).
        // Foreground multi-cell objects keep the ground below them so
        // transparent sprites render correctly.
        final backgroundMcoPosSet = <Position>{
          for (final mco in backgroundMcos) ...mco.cells,
        };

        return SizedBox(
          width: gridWidth,
          height: gridHeight,
          child: Stack(
            children: [
              for (final mco in backgroundMcos)
                ..._buildMcoCells(
                  mco,
                  cellSize,
                  selected: mco.id == selectedMultiCellObjectId,
                ),
              for (int y = 0; y < rows; y++)
                for (int x = 0; x < cols; x++)
                  Positioned(
                    left: x * cellSize,
                    top: y * cellSize,
                    width: cellSize,
                    height: cellSize,
                    child: onCellTap != null
                        ? GestureDetector(
                            behavior: HitTestBehavior.opaque,
                            onTap: () => onCellTap!(x, y),
                            child: _Cell(
                              x: x,
                              y: y,
                              state: state,
                              game: game,
                              packService: packService,
                              cellSize: cellSize,
                              skipGround: backgroundMcoPosSet.contains(
                                Position(x, y),
                              ),
                              actorFacingByKind: actorFacingByKind,
                              floodedColorOverride: floodedColorOverride,
                            ),
                          )
                        : _Cell(
                            x: x,
                            y: y,
                            state: state,
                            game: game,
                            packService: packService,
                            cellSize: cellSize,
                            skipGround: backgroundMcoPosSet.contains(
                              Position(x, y),
                            ),
                            actorFacingByKind: actorFacingByKind,
                            floodedColorOverride: floodedColorOverride,
                          ),
                  ),
              for (final mco in foregroundMcos)
                ..._buildMcoCells(
                  mco,
                  cellSize,
                  selected: mco.id == selectedMultiCellObjectId,
                ),
              // Region outlines: stroke the perimeter of contiguous cells
              // for any kind that has `outline` set in game.json. Painted
              // above cells but below avatar / animation overlays so the
              // border is always visible on top of the fill.
              Positioned.fill(
                child: IgnorePointer(
                  child: CustomPaint(
                    painter: _OutlinePainter(state, game, cellSize),
                  ),
                ),
              ),
              if (selectedActorPosition case final selectedPos?)
                _buildSelectedActorRing(selectedPos, cellSize),
              if (animationOverlays != null)
                for (final entry in animationOverlays!.entries)
                  _buildAnimOverlay(entry.key, entry.value, cellSize),
              if (state.overlay != null)
                _buildOverlay(state.overlay!, cellSize),
              if (lineOfSightFeedbacks.isNotEmpty)
                Positioned.fill(
                  child: IgnorePointer(
                    child: CustomPaint(
                      painter: _LineOfSightFeedbackPainter(
                        lineOfSightFeedbacks,
                        cellSize,
                      ),
                    ),
                  ),
                ),
              for (final feedback in lineOfSightFeedbacks)
                _buildLineOfSightTargetFeedback(feedback, cellSize),
              if (state.avatar.enabled && state.avatar.position != null)
                _buildAvatar(
                  avatarPositionOverride != null
                      ? state.avatar.copyWith(position: avatarPositionOverride)
                      : state.avatar,
                  cellSize,
                ),
            ],
          ),
        );
      },
    );
  }

  List<Widget> _buildMcoCells(
    MultiCellObjectInstance mco,
    double cellSize, {
    bool selected = false,
  }) {
    final exitList = mco.params['exitPosition'] as List?;
    final exitPos = exitList != null
        ? Position(exitList[0] as int, exitList[1] as int)
        : null;
    final queue = (mco.params['queue'] as List?)
            ?.map((e) => e as int)
            .toList() ??
        [];
    final currentIndex = (mco.params['currentIndex'] as int?) ?? 0;

    // Assign queued values to pipe cells.
    final bodyValues = <Position, int>{};
    final pipeSlots = mco.params['pipeSlots'] as List?;
    if (pipeSlots != null) {
      // Bidirectional (slot model): pipeSlots[i] maps directly to mco.cells[i].
      final cells = mco.cells.toList();
      for (int i = 0; i < cells.length && i < pipeSlots.length; i++) {
        final v = pipeSlots[i];
        if (v != null) bodyValues[cells[i]] = v as int;
      }
    } else {
      // Unidirectional (counter model): exit cell gets next-to-drop, then cells further back.
      final remaining = queue.skip(currentIndex).toList();
      if (remaining.isNotEmpty) {
        final orderedCells = mco.cells.toList()
          ..sort((a, b) {
            final da = exitPos != null
                ? (a.x - exitPos.x).abs() + (a.y - exitPos.y).abs()
                : 0;
            final db = exitPos != null
                ? (b.x - exitPos.x).abs() + (b.y - exitPos.y).abs()
                : 0;
            return da.compareTo(db);
          });
        for (int i = 0; i < orderedCells.length && i < remaining.length; i++) {
          bodyValues[orderedCells[i]] = remaining[i];
        }
      }
    }

    return mco.cells.map((pos) {
      final sprite = mco.cellSprites[pos];

      Widget background;
      if (sprite != null) {
        background = Image(
          image: packService.resolvePackImage(sprite),
          width: cellSize,
          height: cellSize,
          fit: BoxFit.cover,
          errorBuilder: (_, __, ___) => _mcoFallback(pos, mco, exitPos, cellSize),
        );
      } else {
        background = _mcoFallback(pos, mco, exitPos, cellSize);
      }

      // Queue value label rendered on top of the background.
      Widget? label;
      if (bodyValues.containsKey(pos)) {
        label = Center(
          child: Text(
            '${bodyValues[pos]}',
            style: TextStyle(
              color: Colors.white,
              fontSize: cellSize * 0.38,
              fontWeight: FontWeight.bold,
            ),
          ),
        );
      }

      final cell = Stack(
        fit: StackFit.expand,
        children: [
          background,
          if (label != null) label,
          if (selected) _selectedMcoCellOverlay(cellSize),
        ],
      );

      return Positioned(
        left: pos.x * cellSize,
        top: pos.y * cellSize,
        width: cellSize,
        height: cellSize,
        child: cell,
      );
    }).toList();
  }

  Widget _selectedMcoCellOverlay(double cellSize) {
    final borderWidth = (cellSize * 0.055).clamp(2.0, 4.0);
    return IgnorePointer(
      child: DecoratedBox(
        decoration: BoxDecoration(
          border: Border.all(
            color: const Color(0xFFFFC107),
            width: borderWidth,
          ),
          boxShadow: [
            BoxShadow(
              color: const Color(0xFFFFC107).withValues(alpha: 0.35),
              blurRadius: borderWidth * 2.4,
              spreadRadius: borderWidth * 0.25,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildLineOfSightTargetFeedback(
    LineOfSightFeedback feedback,
    double cellSize,
  ) {
    final assetPath = game.entityKinds[feedback.kind]?.sprite;
    final child = assetPath != null
        ? Image(
            image: packService.resolvePackImage(assetPath),
            fit: BoxFit.contain,
            errorBuilder: (_, __, ___) => Icon(
              Icons.auto_awesome,
              color: Colors.amber.shade600,
              size: cellSize * 0.58,
            ),
          )
        : Icon(
            Icons.auto_awesome,
            color: Colors.amber.shade600,
            size: cellSize * 0.58,
          );

    return Positioned(
      left: feedback.target.x * cellSize,
      top: feedback.target.y * cellSize,
      width: cellSize,
      height: cellSize,
      child: IgnorePointer(
        child: Center(
          child: Transform.scale(
            scale: 1.22,
            child: DecoratedBox(
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: Colors.amber.withValues(alpha: 0.6),
                    blurRadius: cellSize * 0.22,
                    spreadRadius: cellSize * 0.04,
                  ),
                ],
              ),
              child: SizedBox(
                width: cellSize * 0.78,
                height: cellSize * 0.78,
                child: child,
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _mcoFallback(
    Position pos,
    MultiCellObjectInstance mco,
    Position? exitPos,
    double cellSize,
  ) {
    final cellSet = mco.cells.toSet();
    final isExit = pos == exitPos;
    return CustomPaint(
      painter: _PipeCellPainter(
        openLeft: cellSet.contains(Position(pos.x - 1, pos.y)),
        openRight: cellSet.contains(Position(pos.x + 1, pos.y)),
        openUp: cellSet.contains(Position(pos.x, pos.y - 1)),
        openDown: cellSet.contains(Position(pos.x, pos.y + 1)) || isExit,
        isExit: isExit,
      ),
    );
  }

  Widget _buildOverlay(OverlayCursor overlay, double cellSize) {
    return Positioned(
      left: overlay.x * cellSize,
      top: overlay.y * cellSize,
      width: overlay.width * cellSize,
      height: overlay.height * cellSize,
      child: IgnorePointer(
        child: Container(
          decoration: BoxDecoration(
            border: Border.all(color: Colors.amber.withOpacity(0.9), width: 2.5),
            color: Colors.amber.withOpacity(0.08),
            borderRadius: BorderRadius.circular(3),
          ),
        ),
      ),
    );
  }

  Widget _buildSelectedActorRing(Position pos, double cellSize) {
    return Positioned(
      left: pos.x * cellSize,
      top: pos.y * cellSize,
      width: cellSize,
      height: cellSize,
      child: IgnorePointer(
        child: Padding(
          padding: EdgeInsets.all(cellSize * 0.08),
          child: DecoratedBox(
            decoration: BoxDecoration(
              border: Border.all(
                color: const Color(0xFFFFD45A),
                width: max(2.0, cellSize * 0.045),
              ),
              borderRadius: BorderRadius.circular(cellSize * 0.18),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildAnimOverlay(Position pos, String dslPath, double cellSize) {
    return Positioned(
      left: pos.x * cellSize,
      top: pos.y * cellSize,
      width: cellSize,
      height: cellSize,
      child: IgnorePointer(
        child: Image(
          image: packService.resolvePackImage(dslPath),
          fit: BoxFit.cover,
          errorBuilder: (_, __, ___) => Image.asset(
            packService.resolveSprite(dslPath),
            fit: BoxFit.cover,
          ),
        ),
      ),
    );
  }

  /// Path declared by the pack's theme for this avatar state and direction, or
  /// null when the pack declares no avatar art and the shared base sprites
  /// should be used instead. Mirror entries resolve to the path they point at;
  /// [mirrored] reports whether the caller must flip it horizontally.
  ({String path, bool mirrored})? _themeAvatarSprite(String facing) {
    final avatarTheme = packService.theme?.avatar;
    if (avatarTheme == null) return null;

    ({String path, bool mirrored})? pathOf(String direction, bool mirrored) {
      final entry = avatarTheme.resolve('idle', direction);
      if (entry == null) return null;
      if (entry.isStatic) return (path: entry.staticPath!, mirrored: mirrored);
      // Animated entries render their first frame; nothing drives a per-frame
      // ticker for the avatar yet.
      if (entry.isAnimated && entry.frames!.isNotEmpty) {
        return (path: entry.frames!.first, mirrored: mirrored);
      }
      // A mirror of a mirror would loop, so only one hop is followed.
      if (entry.isMirror && !mirrored) return pathOf(entry.mirror!, true);
      return null;
    }

    return pathOf(facing, false);
  }

  Widget _buildAvatar(AvatarState avatar, double cellSize) {
    final facing = avatar.facing.toJson();
    final themeSprite = _themeAvatarSprite(facing);
    final assetPath = packService.resolveAvatarSprite(_avatarSpriteFile(facing));
    final slot = avatar.inventory.slot;

    // When an overlay exists, center the avatar at the overlay's midpoint.
    final overlay = state.overlay;
    final double left, top, size;
    if (overlay != null) {
      size = cellSize * 0.9;
      left = (overlay.x + overlay.width / 2) * cellSize - size / 2;
      top = (overlay.y + overlay.height / 2) * cellSize - size / 2;
    } else {
      final pos = avatar.position!;
      size = cellSize;
      left = pos.x * cellSize;
      top = pos.y * cellSize;
    }

    return Positioned(
      left: left,
      top: top,
      width: size,
      height: size,
      child: Stack(
        children: [
          if (themeSprite != null)
            Transform.scale(
              scaleX: themeSprite.mirrored ? -1 : 1,
              child: Image(
                image: packService.resolvePackImage(themeSprite.path),
                fit: BoxFit.contain,
                errorBuilder: (_, __, ___) => Image.asset(
                  packService.resolveSprite(themeSprite.path),
                  fit: BoxFit.contain,
                ),
              ),
            )
          else
            Image.asset(
              assetPath,
              fit: BoxFit.contain,
              errorBuilder: (_, __, ___) => Container(
                decoration: BoxDecoration(
                  color: Colors.pink.shade200,
                  shape: BoxShape.circle,
                ),
                child: Icon(Icons.pets, size: size * 0.6, color: Colors.white),
              ),
            ),
          if (slot != null) _buildInventoryBadge(slot, size),
        ],
      ),
    );
  }

  Widget _buildInventoryBadge(String itemKind, double cellSize) {
    final badgeSize = cellSize * 0.38;
    final sprite = game.entityKinds[itemKind]?.sprite;
    return Positioned(
      right: 0,
      top: 0,
      width: badgeSize,
      height: badgeSize,
      child: sprite != null
          ? Image.asset(
              packService.resolveSprite(sprite),
              fit: BoxFit.contain,
              errorBuilder: (_, __, ___) =>
                  Icon(Icons.auto_awesome, size: badgeSize * 0.7),
            )
          : Icon(Icons.auto_awesome, size: badgeSize * 0.7),
    );
  }

  String _avatarSpriteFile(String direction) {
    switch (direction) {
      case 'up':
        return 'rabbit_walking_up_1.png';
      case 'down':
        return 'rabbit_walking_down_1.png';
      case 'left':
        return 'rabbit_walking_left_1.png';
      default:
        return 'rabbit_looking_right.png';
    }
  }
}

class _LineOfSightFeedbackPainter extends CustomPainter {
  final List<LineOfSightFeedback> feedbacks;
  final double cellSize;

  const _LineOfSightFeedbackPainter(this.feedbacks, this.cellSize);

  @override
  void paint(Canvas canvas, Size size) {
    final linePaint = Paint()
      ..color = const Color(0xFFFFD54F).withValues(alpha: 0.9)
      ..strokeWidth = (cellSize * 0.075).clamp(3.0, 7.0)
      ..strokeCap = StrokeCap.round;
    final glowPaint = Paint()
      ..color = const Color(0xFFFFF176).withValues(alpha: 0.32)
      ..strokeWidth = (cellSize * 0.19).clamp(8.0, 16.0)
      ..strokeCap = StrokeCap.round;

    for (final feedback in feedbacks) {
      final source = Offset(
        (feedback.source.x + 0.5) * cellSize,
        (feedback.source.y + 0.5) * cellSize,
      );
      final target = Offset(
        (feedback.target.x + 0.5) * cellSize,
        (feedback.target.y + 0.5) * cellSize,
      );
      canvas.drawLine(source, target, glowPaint);
      canvas.drawLine(source, target, linePaint);
    }
  }

  @override
  bool shouldRepaint(covariant _LineOfSightFeedbackPainter oldDelegate) {
    return oldDelegate.feedbacks != feedbacks ||
        oldDelegate.cellSize != cellSize;
  }
}

class _Cell extends StatelessWidget {
  final int x, y;
  final LevelState state;
  final GameDefinition game;
  final PackService packService;
  final double cellSize;
  final bool skipGround;
  final Map<String, String> actorFacingByKind;
  final Color? floodedColorOverride;

  const _Cell({
    required this.x,
    required this.y,
    required this.state,
    required this.game,
    required this.packService,
    required this.cellSize,
    this.skipGround = false,
    this.actorFacingByKind = const {},
    this.floodedColorOverride,
  });

  @override
  Widget build(BuildContext context) {
    final pos = Position(x, y);
    final groundEntity = state.board.getEntity('ground', pos);
    if (groundEntity?.kind == 'void' && !skipGround) {
      final kindDef = game.entityKinds['void'];
      final spritePath = resolveEntitySpritePath(kindDef, groundEntity!);
      if (spritePath != null) {
        return Image.asset(
          packService.resolveSprite(spritePath),
          width: cellSize,
          height: cellSize,
          fit: BoxFit.cover,
        );
      }
      // Procedural fallback only when the game itself uses procedural
      // rendering for normal cells (no sprite on `empty`). Sprite-backed
      // packs (e.g. twinseed: empty=grass.png) frame voids naturally via the
      // surrounding tiles, so we leave them transparent.
      final emptySprite = game.entityKinds['empty']?.sprite;
      if (emptySprite == null) {
        return Container(
          width: cellSize,
          height: cellSize,
          color: const Color(0xFFB0B0B0),
        );
      }
      return const SizedBox.shrink();
    }
    return Container(
      decoration:
          BoxDecoration(border: Border.all(color: Colors.black12, width: 0.5)),
      child: Stack(
        children: [
          if (!skipGround) _layer('ground', pos),
          _layer('territory', pos),
          _layer('portals', pos),
          _layer('objects', pos),
          _layer('clone', pos),
          _layer('markers', pos),
          _layer('actors', pos),
        ],
      ),
    );
  }

  Widget _layer(String layerId, Position pos) {
    final entity = state.board.getEntity(layerId, pos);
    if (entity == null) return const SizedBox.shrink();
    final kindDef = game.entityKinds[entity.kind];
    final facingDirection = layerId == 'actors'
        ? actorFacingByKind[entity.kind]
        : null;
    final spritePath = resolveEntitySpritePath(
      kindDef,
      entity,
      facingDirection: facingDirection,
    );
    if (spritePath != null) {
      // Try pack-specific path first; fall back to gridponder-base for shared sprites.
      return Image(
        image: packService.resolvePackImage(spritePath),
        width: cellSize,
        height: cellSize,
        fit: BoxFit.cover,
        errorBuilder: (_, __, ___) => Image.asset(
          packService.resolveSprite(spritePath),
          width: cellSize,
          height: cellSize,
          fit: BoxFit.cover,
          errorBuilder: (_, __, ___) => _fallback(entity),
        ),
      );
    }
    return _fallback(entity);
  }

  Widget _fallback(EntityInstance entity) {
    final kind = entity.kind;
    final kindDef = game.entityKinds[kind];
    final display = kindDef?.display;
    if (display != null) {
      final widget = _renderFromDisplay(display, entity);
      if (widget != null) return widget;
    }

    final color = _color(kind, entity);
    return Container(
      color: color,
      alignment: Alignment.center,
      child: switch (kind) {
        _ => null,
      },
    );
  }

  Color _color(String kind, EntityInstance entity) {
    if (kind == 'cell_flooded' && floodedColorOverride != null) {
      return floodedColorOverride!;
    }
    if (kind.startsWith('cell_')) return _namedColor(kind.substring(5));
    if (kind == 'number') {
      final v = (entity.param('value') as int?) ?? 0;
      return _numberColor(v);
    }
    if (kind.startsWith('num_')) {
      return _numberColor(int.tryParse(kind.substring(4)) ?? 0);
    }
    return switch (kind) {
      'empty' => const Color(0xFFF5F0E8),
      'wall' => const Color(0xFF546E7A),
      'water' => const Color(0xFF64B5F6),
      'ice' => const Color(0xFFB3E5FC),
      'bridge' => const Color(0xFF8D6E63),
      'void' => Colors.black87,
      'rock' => const Color(0xFF9E9E9E),
      'wood' => const Color(0xFFFF9800),
      'metal_crate' => const Color(0xFF78909C),
      'torch' => const Color(0xFFFFEB3B),
      'pickaxe' => const Color(0xFF795548),
      'portal' => const Color(0xFFCE93D8),
      _ => const Color(0xFFF8BBD9),
    };
  }

  Color _namedColor(String name) =>
      cellNamedColor(name, palette: packService.theme?.palette);

  Color _numberColor(int v) =>
      HSLColor.fromAHSL(1.0, (v * 37 % 360).toDouble(), 0.6, 0.45).toColor();

  /// Renders an entity using a `display` block from its kind def. Returns
  /// null when [display] doesn't specify a recognised type (caller falls
  /// back to legacy procedural paths). Sole pack-visible vocabulary, so
  /// the renderer doesn't have to recognise specific entity-kind names.
  Widget? _renderFromDisplay(Map<String, dynamic> display, EntityInstance entity) {
    final type = display['type'] as String?;
    final color = _resolveDisplayColor(display['color'], entity);
    switch (type) {
      case 'tile':
        return Container(
          margin: EdgeInsets.all(cellSize * 0.1),
          decoration: BoxDecoration(
            color: color ?? _namedColor('grey'),
            borderRadius: BorderRadius.circular(cellSize * 0.1),
            boxShadow: const [
              BoxShadow(color: Colors.black26, blurRadius: 2, offset: Offset(1, 1)),
            ],
          ),
        );
      case 'fill':
        return Container(color: color ?? _namedColor('grey'));
      case 'circle':
        final c = color ?? _namedColor('green');
        return Center(
          child: Container(
            width: cellSize * 0.5,
            height: cellSize * 0.5,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: c,
              boxShadow: [BoxShadow(color: c, blurRadius: 4, spreadRadius: 1)],
            ),
          ),
        );
      case 'label':
        final labelText = _resolveDisplayString(display['label'], entity) ?? '?';
        return Container(
          color: color ?? _namedColor('grey'),
          alignment: Alignment.center,
          child: Text(
            labelText,
            style: TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.bold,
              fontSize: cellSize * 0.42,
            ),
          ),
        );
      case 'emoji':
        final glyph = display['value'] as String? ?? '?';
        return Center(
          child: Text(glyph, style: TextStyle(fontSize: cellSize * 0.6)),
        );
      case 'icon':
        return Container(
          color: color,
          alignment: Alignment.center,
          child: Icon(
            _materialIcon(display['value'] as String?),
            size: cellSize * 0.65,
            color: Colors.white70,
          ),
        );
      default:
        return null;
    }
  }

  /// Resolves a `display.color` spec. Accepts `null`, a palette name
  /// (`"red"`), or one of the substitution tokens:
  ///   - `@param:<key>`        — read a colour name from an instance param
  ///   - `@hue:<source>`       — derive an HSL colour from a numeric
  ///                             string. `<source>` is itself a string spec
  ///                             (literal int, or a nested `@param:` /
  ///                             `@kind_suffix:` token).
  Color? _resolveDisplayColor(dynamic spec, EntityInstance entity) {
    if (spec is! String) return null;
    if (spec.startsWith('@hue:')) {
      final source = _resolveDisplayString(spec.substring(5), entity);
      final n = source == null ? null : int.tryParse(source);
      return n == null ? null : _numberColor(n);
    }
    if (spec.startsWith('@param:')) {
      final v = entity.param(spec.substring(7));
      if (v is! String) return null;
      return _namedColor(v);
    }
    return _namedColor(spec);
  }

  /// Resolves a string spec used inside `display` (label text, the source
  /// of `@hue:`, …). Tokens:
  ///   - `@param:<key>`         — entity.param(key).toString()
  ///   - `@kind_suffix:<prefix>` — entity.kind with [prefix] removed
  ///   - anything else           — literal
  String? _resolveDisplayString(dynamic spec, EntityInstance entity) {
    if (spec is! String) return null;
    if (spec.startsWith('@param:')) {
      final v = entity.param(spec.substring(7));
      return v?.toString();
    }
    if (spec.startsWith('@kind_suffix:')) {
      final prefix = spec.substring(13);
      return entity.kind.startsWith(prefix)
          ? entity.kind.substring(prefix.length)
          : null;
    }
    return spec;
  }

  /// Tiny lookup so a pack can name a Material icon by its standard name.
  /// Extend as needed; unknown names render the default placeholder.
  IconData _materialIcon(String? name) => switch (name) {
        'blur_on' => Icons.blur_on,
        'star' => Icons.star,
        'flag' => Icons.flag,
        _ => Icons.circle_outlined,
      };
}

// ---------------------------------------------------------------------------
// Target board renderer (for board_match goal display)
// ---------------------------------------------------------------------------

/// Renders a static mini-grid from a board_match goal's targetLayers config.
/// targetLayers maps layer id → 2D list [y][x] of kind strings (nullable).
/// Pass [currentState] to highlight cells that already match the target.
class TargetBoardRenderer extends StatelessWidget {
  final Map<String, dynamic> targetLayers;
  final LevelState? currentState;
  /// Pack-specific colour overrides forwarded to [cellNamedColor]. Pass
  /// `packService.theme?.palette` from the caller; null falls back to
  /// the renderer's built-in palette.
  final Map<String, String>? palette;
  static const double _cellSize = 24.0;

  const TargetBoardRenderer(
      {super.key, required this.targetLayers, this.currentState, this.palette});

  @override
  Widget build(BuildContext context) {
    final firstLayer = targetLayers.values.firstOrNull;
    if (firstLayer == null) return const SizedBox.shrink();
    final rows = (firstLayer as List).length;
    final cols = rows > 0 ? (firstLayer[0] as List).length : 0;
    if (rows == 0 || cols == 0) return const SizedBox.shrink();

    return SizedBox(
      width: _cellSize * cols,
      height: _cellSize * rows,
      child: Stack(
        children: [
          for (int y = 0; y < rows; y++)
            for (int x = 0; x < cols; x++)
              Positioned(
                left: x * _cellSize,
                top: y * _cellSize,
                width: _cellSize,
                height: _cellSize,
                child: _TargetCell(
                    x: x,
                    y: y,
                    targetLayers: targetLayers,
                    currentState: currentState,
                    palette: palette),
              ),
        ],
      ),
    );
  }
}

class _TargetCell extends StatelessWidget {
  final int x, y;
  final Map<String, dynamic> targetLayers;
  final LevelState? currentState;
  final Map<String, String>? palette;

  const _TargetCell(
      {required this.x,
      required this.y,
      required this.targetLayers,
      this.currentState,
      this.palette});

  String? _kindAt(String layerId) {
    final layer = targetLayers[layerId] as List?;
    if (layer == null || y >= layer.length) return null;
    final row = layer[y] as List?;
    if (row == null || x >= row.length) return null;
    return row[x] as String?;
  }

  bool _matches(String targetKind, String layerId) {
    final cs = currentState;
    if (cs == null) return false;
    final entity = cs.board.getEntity(layerId, Position(x, y));
    return entity?.kind == targetKind;
  }

  static const double _cellSize = 24.0;

  @override
  Widget build(BuildContext context) {
    String? kind;
    bool matched = false;
    for (final layerId in ['objects', 'markers']) {
      final k = _kindAt(layerId);
      if (k != null) {
        kind = k;
        matched = _matches(k, layerId);
        break;
      }
    }
    final bgColor =
        matched ? Colors.lightGreen.shade200 : const Color(0xFFF5F0E8);
    return Container(
      decoration: BoxDecoration(
        color: bgColor,
        border: const Border.fromBorderSide(
            BorderSide(color: Colors.black12, width: 0.5)),
      ),
      child: kind != null ? _buildTargetCell(kind) : null,
    );
  }

  Widget _buildTargetCell(String kind) {
    final color = _cellColor(kind);
    final label = kind.startsWith('num_') ? kind.substring(4) : null;
    return Container(
      margin: const EdgeInsets.all(_cellSize * 0.1),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(_cellSize * 0.1),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.2),
            blurRadius: 2,
            offset: const Offset(1, 1),
          ),
        ],
      ),
      child: label != null
          ? Center(
              child: Text(
                label,
                style: const TextStyle(
                  fontSize: _cellSize * 0.42,
                  fontWeight: FontWeight.bold,
                  color: Colors.white,
                ),
              ),
            )
          : null,
    );
  }

  Color _cellColor(String kind) {
    if (kind.startsWith('cell_')) return _namedColor(kind.substring(5));
    return switch (kind) {
      'empty' => const Color(0xFFF5F0E8),
      'rock' => const Color(0xFF9E9E9E),
      'wood' => const Color(0xFFFF9800),
      _ => const Color(0xFFF8BBD9),
    };
  }

  Color _namedColor(String name) => cellNamedColor(name, palette: palette);
}

// ---------------------------------------------------------------------------
// Pipe tile painter
// ---------------------------------------------------------------------------

class _PipeCellPainter extends CustomPainter {
  final bool openLeft, openRight, openUp, openDown, isExit;

  const _PipeCellPainter({
    required this.openLeft,
    required this.openRight,
    required this.openUp,
    required this.openDown,
    required this.isExit,
  });

  static const _bg = Color(0xFF37474F);       // dark steel background
  static const _wall = Color(0xFF263238);      // darker outline
  static const _lumen = Color(0xFF78909C);     // inner channel fill
  static const _lumenLight = Color(0xFF90A4AE);// highlight inside channel

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;
    final r = min(w, h);
    final cr = r * 0.30; // channel half-width (30% of cell)

    // Fill background.
    canvas.drawRect(Rect.fromLTWH(0, 0, w, h), Paint()..color = _bg);

    final lumenPaint = Paint()..color = _lumen;
    final lightPaint = Paint()..color = _lumenLight;
    final wallPaint  = Paint()
      ..color = _wall
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0;

    final cx = w / 2;
    final cy = h / 2;

    // Draw channel segments for each open direction.
    // Each segment is a filled rectangle from cell center toward the open edge.
    void drawSegment(double x1, double y1, double x2, double y2) {
      final rect = Rect.fromPoints(Offset(x1, y1), Offset(x2, y2));
      canvas.drawRect(rect, lumenPaint);
      // Small highlight strip along the top/left edge of each channel.
      final isHoriz = (y2 - y1).abs() < (x2 - x1).abs();
      if (isHoriz) {
        canvas.drawRect(
            Rect.fromLTWH(rect.left, rect.top, rect.width, rect.height * 0.25),
            lightPaint);
      } else {
        canvas.drawRect(
            Rect.fromLTWH(rect.left, rect.top, rect.width * 0.25, rect.height),
            lightPaint);
      }
      canvas.drawRect(rect, wallPaint);
    }

    // Center square — filled whenever two or more sides are open.
    final centerRect = Rect.fromLTWH(cx - cr, cy - cr, cr * 2, cr * 2);
    final openCount = [openLeft, openRight, openUp, openDown]
        .where((v) => v)
        .length;
    if (openCount >= 2) {
      canvas.drawRect(centerRect, lumenPaint);
      canvas.drawRect(centerRect, wallPaint);
    }

    if (openLeft)  drawSegment(0,      cy - cr, cx, cy + cr);
    if (openRight) drawSegment(cx,     cy - cr, w,  cy + cr);
    if (openUp)    drawSegment(cx - cr, 0,      cx + cr, cy);
    if (openDown)  drawSegment(cx - cr, cy,     cx + cr, h);

    // Exit indicator: small downward chevron at the bottom edge.
    if (isExit) {
      final chevronPaint = Paint()
        ..color = Colors.white54
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.5
        ..strokeCap = StrokeCap.round;
      final bx = cx;
      final by = h - r * 0.1;
      final arm = r * 0.12;
      canvas.drawLine(Offset(bx - arm, by - arm), Offset(bx, by), chevronPaint);
      canvas.drawLine(Offset(bx, by), Offset(bx + arm, by - arm), chevronPaint);
    }
  }

  @override
  bool shouldRepaint(_PipeCellPainter old) =>
      old.openLeft != openLeft ||
      old.openRight != openRight ||
      old.openUp != openUp ||
      old.openDown != openDown ||
      old.isExit != isExit;
}

// ---------------------------------------------------------------------------

/// Strokes the outer perimeter of every contiguous region of cells whose
/// kind has `outline` set in game.json. For each cell in such a region we
/// draw an edge segment on the sides whose neighbour is NOT in the region;
/// stitched together this traces the region boundary exactly once. Layer is
/// taken from the kind def, so the same outline kind in a different layer
/// works without configuration.
class _OutlinePainter extends CustomPainter {
  final LevelState state;
  final GameDefinition game;
  final double cellSize;

  const _OutlinePainter(this.state, this.game, this.cellSize);

  @override
  void paint(Canvas canvas, Size size) {
    for (final entry in game.entityKinds.entries) {
      final kindId = entry.key;
      final kindDef = entry.value;
      final outline = kindDef.outline;
      if (outline == null) continue;

      final color = _parseHex(outline['color'] as String?) ?? const Color(0xFF222222);
      final width = (outline['width'] as num?)?.toDouble() ?? 2.0;
      final paint = Paint()
        ..color = color
        ..strokeWidth = width
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.square;

      final layer = state.board.layers[kindDef.layer];
      if (layer == null) continue;

      bool inSet(int x, int y) {
        if (x < 0 || y < 0) return false;
        final e = layer.getAt(Position(x, y));
        return e != null && e.kind == kindId;
      }

      for (final cell in layer.entries()) {
        if (cell.value.kind != kindId) continue;
        final px = cell.key.x * cellSize;
        final py = cell.key.y * cellSize;
        final left = px;
        final top = py;
        final right = px + cellSize;
        final bottom = py + cellSize;

        if (!inSet(cell.key.x, cell.key.y - 1)) {
          canvas.drawLine(Offset(left, top), Offset(right, top), paint);
        }
        if (!inSet(cell.key.x + 1, cell.key.y)) {
          canvas.drawLine(Offset(right, top), Offset(right, bottom), paint);
        }
        if (!inSet(cell.key.x, cell.key.y + 1)) {
          canvas.drawLine(Offset(left, bottom), Offset(right, bottom), paint);
        }
        if (!inSet(cell.key.x - 1, cell.key.y)) {
          canvas.drawLine(Offset(left, top), Offset(left, bottom), paint);
        }
      }
    }
  }

  Color? _parseHex(String? hex) {
    if (hex == null) return null;
    var s = hex.trim();
    if (s.startsWith('#')) s = s.substring(1);
    if (s.length == 6) s = 'FF$s';
    if (s.length != 8) return null;
    final v = int.tryParse(s, radix: 16);
    return v == null ? null : Color(v);
  }

  @override
  bool shouldRepaint(_OutlinePainter old) =>
      !identical(old.state, state) || old.cellSize != cellSize;
}
