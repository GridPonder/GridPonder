import 'dart:math';
import 'package:flutter/material.dart';
import 'package:gridponder_engine/engine.dart';
import '../services/pack_service.dart';

/// Canonical 8-color palette for colored cell entities.
/// Colors are chosen to be clearly distinguishable from each other and from
/// black (used for void cells). All colors work on a light background.
Color cellNamedColor(String name) => switch (name) {
      'red' => const Color(0xFFE53935),
      'blue' => const Color(0xFF1E88E5),
      'green' => const Color(0xFF43A047),
      'yellow' => const Color(0xFFFFD600),
      'purple' => const Color(0xFF8E24AA),
      'lime' => const Color(0xFF7CB342),
      'teal' => const Color(0xFF00897B),
      'pink' => const Color(0xFFE91E63),
      _ => const Color(0xFF9E9E9E),
    };

class BoardRenderer extends StatelessWidget {
  final LevelState state;
  final GameDefinition game;
  final PackService packService;
  /// Optional overlay sprites rendered on top of the objects layer, used during
  /// entity destruction animations. Maps cell position → resolved asset path.
  final Map<Position, String>? animationOverlays;
  /// Called when the user taps/clicks a cell. Enables tap-to-act gestures.
  final void Function(int x, int y)? onCellTap;
  /// When set, cell_flooded entities are rendered in this color instead of
  /// their default color — used by Flood Colors to show the last chosen color.
  final Color? floodedColorOverride;

  const BoardRenderer({
    super.key,
    required this.state,
    required this.game,
    required this.packService,
    this.animationOverlays,
    this.onCellTap,
    this.floodedColorOverride,
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

        // Positions that belong to a multi-cell object — ground layer is
        // suppressed there so pipe tiles show through as the background.
        final mcoPosSet = <Position>{
          for (final mco in state.board.multiCellObjects) ...mco.cells,
        };

        return SizedBox(
          width: gridWidth,
          height: gridHeight,
          child: Stack(
            children: [
              // Pipe tile backgrounds rendered first so entity layers sit on top.
              for (final mco in state.board.multiCellObjects)
                ..._buildMcoCells(mco, cellSize),
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
                              skipGround: mcoPosSet.contains(Position(x, y)),
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
                            skipGround: mcoPosSet.contains(Position(x, y)),
                            floodedColorOverride: floodedColorOverride,
                          ),
                  ),
              if (animationOverlays != null)
                for (final entry in animationOverlays!.entries)
                  _buildAnimOverlay(entry.key, entry.value, cellSize),
              if (state.overlay != null)
                _buildOverlay(state.overlay!, cellSize),
              if (state.avatar.enabled && state.avatar.position != null)
                _buildAvatar(state.avatar, cellSize),
            ],
          ),
        );
      },
    );
  }

  List<Widget> _buildMcoCells(MultiCellObjectInstance mco, double cellSize) {
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
      final isExit = pos == exitPos;
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

      return Positioned(
        left: pos.x * cellSize,
        top: pos.y * cellSize,
        width: cellSize,
        height: cellSize,
        child: label != null
            ? Stack(children: [background, label])
            : background,
      );
    }).toList();
  }

  Widget _mcoFallback(Position pos, MultiCellObjectInstance mco,
      Position? exitPos, double cellSize) {
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

  Widget _buildAnimOverlay(Position pos, String spritePath, double cellSize) {
    return Positioned(
      left: pos.x * cellSize,
      top: pos.y * cellSize,
      width: cellSize,
      height: cellSize,
      child: IgnorePointer(
        child: Image.asset(spritePath, fit: BoxFit.cover),
      ),
    );
  }

  Widget _buildAvatar(AvatarState avatar, double cellSize) {
    final assetPath =
        packService.resolveAvatarSprite(_avatarSpriteFile(avatar.facing.toJson()));
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

class _Cell extends StatelessWidget {
  final int x, y;
  final LevelState state;
  final GameDefinition game;
  final PackService packService;
  final double cellSize;
  final bool skipGround;
  final Color? floodedColorOverride;

  const _Cell({
    required this.x,
    required this.y,
    required this.state,
    required this.game,
    required this.packService,
    required this.cellSize,
    this.skipGround = false,
    this.floodedColorOverride,
  });

  @override
  Widget build(BuildContext context) {
    final pos = Position(x, y);
    return Container(
      decoration:
          BoxDecoration(border: Border.all(color: Colors.black12, width: 0.5)),
      child: Stack(
        children: [
          if (!skipGround) _layer('ground', pos),
          _layer('objects', pos),
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
    if (kindDef?.sprite != null) {
      return Image.asset(
        packService.resolveSprite(kindDef!.sprite!),
        width: cellSize,
        height: cellSize,
        fit: BoxFit.cover,
        errorBuilder: (_, __, ___) => _fallback(entity),
      );
    }
    return _fallback(entity);
  }

  Widget _fallback(EntityInstance entity) {
    final kind = entity.kind;
    final color = _color(kind, entity);

    if (kind == 'number') {
      return Container(
        color: color,
        alignment: Alignment.center,
        child: Text(
          entity.param('value')?.toString() ?? '?',
          style: TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.bold,
              fontSize: cellSize * 0.42),
        ),
      );
    }
    if (kind.startsWith('num_')) {
      return Container(
        color: color,
        alignment: Alignment.center,
        child: Text(
          kind.substring(4),
          style: TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.bold,
              fontSize: cellSize * 0.42),
        ),
      );
    }

    if (kind == 'flag') {
      return Center(
        child: Text('🥕', style: TextStyle(fontSize: cellSize * 0.6)),
      );
    }

    if (kind == 'spirit') {
      final spiritColor = _namedColor(entity.param('color') as String? ?? 'green');
      return Center(
        child: Container(
          width: cellSize * 0.5,
          height: cellSize * 0.5,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: spiritColor,
            boxShadow: [
              BoxShadow(
                color: spiritColor.withOpacity(0.5),
                blurRadius: 4,
                spreadRadius: 1,
              ),
            ],
          ),
        ),
      );
    }

    if (kind == 'colored_cell') {
      final cellColor = _namedColor(entity.param('color') as String? ?? 'grey');
      return Container(color: cellColor);
    }

    if (kind == 'box_fragment') {
      final sides = (entity.param('sides') as int?) ?? 0;
      return CustomPaint(
        size: Size(cellSize, cellSize),
        painter: _BoxFragmentPainter(sides: sides, cellSize: cellSize),
      );
    }

    if (kind == 'box_target') {
      return Container(
        margin: EdgeInsets.all(cellSize * 0.15),
        decoration: BoxDecoration(
          border: Border.all(
            color: const Color(0xFF8B5E3C).withValues(alpha: 0.5),
            width: 2,
          ),
          borderRadius: BorderRadius.circular(cellSize * 0.08),
        ),
      );
    }

    if (kind.startsWith('cell_')) {
      return Container(
        margin: EdgeInsets.all(cellSize * 0.1),
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(cellSize * 0.1),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.2),
              blurRadius: 2,
              offset: const Offset(1, 1),
            ),
          ],
        ),
      );
    }

    return Container(
      color: color,
      alignment: Alignment.center,
      child: switch (kind) {
        'portal' =>
          Icon(Icons.blur_on, size: cellSize * 0.65, color: Colors.white70),
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

  Color _namedColor(String name) => cellNamedColor(name);

  Color _numberColor(int v) =>
      HSLColor.fromAHSL(1.0, (v * 37 % 360).toDouble(), 0.6, 0.45).toColor();
}

// ---------------------------------------------------------------------------
// Box fragment painter — draws sides as thick coloured walls
// ---------------------------------------------------------------------------

class _BoxFragmentPainter extends CustomPainter {
  final int sides;
  final double cellSize;

  // Side bit constants matching the engine.
  static const int _sU = 1, _sR = 2, _sD = 4, _sL = 8;

  _BoxFragmentPainter({required this.sides, required this.cellSize});

  @override
  void paint(Canvas canvas, Size size) {
    final full = sides == (_sU | _sR | _sD | _sL);
    final m = cellSize * 0.1; // margin
    final rect = Rect.fromLTRB(m, m, size.width - m, size.height - m);

    // Body fill
    final bodyPaint = Paint()
      ..color = full
          ? const Color(0xFF8B5E3C) // solid brown for complete box
          : const Color(0xFF8B5E3C).withValues(alpha: 0.15);
    final rr = RRect.fromRectAndRadius(rect, Radius.circular(cellSize * 0.08));
    canvas.drawRRect(rr, bodyPaint);

    // Draw active sides as thick lines
    final wallPaint = Paint()
      ..color = const Color(0xFF8B5E3C)
      ..strokeWidth = cellSize * 0.12
      ..strokeCap = StrokeCap.round;

    if (sides & _sU != 0) {
      canvas.drawLine(rect.topLeft, rect.topRight, wallPaint);
    }
    if (sides & _sR != 0) {
      canvas.drawLine(rect.topRight, rect.bottomRight, wallPaint);
    }
    if (sides & _sD != 0) {
      canvas.drawLine(rect.bottomLeft, rect.bottomRight, wallPaint);
    }
    if (sides & _sL != 0) {
      canvas.drawLine(rect.topLeft, rect.bottomLeft, wallPaint);
    }

    // Full-box indicator: a small check or star in the center
    if (full) {
      final iconPaint = Paint()..color = Colors.white.withValues(alpha: 0.8);
      final center = rect.center;
      final r = cellSize * 0.12;
      canvas.drawCircle(center, r, iconPaint);
    }
  }

  @override
  bool shouldRepaint(_BoxFragmentPainter old) =>
      old.sides != sides || old.cellSize != cellSize;
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
  static const double _cellSize = 24.0;

  const TargetBoardRenderer(
      {super.key, required this.targetLayers, this.currentState});

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
                    currentState: currentState),
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

  const _TargetCell(
      {required this.x,
      required this.y,
      required this.targetLayers,
      this.currentState});

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

  Color _namedColor(String name) => cellNamedColor(name);
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
