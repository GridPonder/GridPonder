import '../models/board.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/level_definition.dart';
import '../models/position.dart';
import '../models/system_def.dart';

/// Renders a [LevelState] as a compact text grid using Unicode symbols.
///
/// Each cell shows the "most prominent" entity across all layers.
/// The avatar is highest; board layers follow the game's declared rendering
/// order (last layer is topmost), with an MCO body above ground when no board
/// layer above it supplies a symbol.
///
/// When an overlay is active the avatar is suppressed from the grid (its
/// position is shown in the Active region block instead) and cell content is
/// displayed at every position without bracket corner markers.
///
/// The text symbol for each entity kind is defined by [EntityKindDef.symbol]
/// in game.json. All symbols must be single Unicode characters with display
/// width 1 (narrow). The only hardcoded symbol is '@' for the avatar (an
/// engine concept, not an entity kind). Entity kinds with [EntityKindDef.symbolParam]
/// are rendered as 'N' in the grid; their exact values appear in the
/// "Number values" block below the grid.
///
/// Multi-cell objects (e.g. pipes) are rendered with direction-aware symbols
/// in the grid (═ horizontal, ║ vertical, ╬ junction, ▲▼◄► exit — arrow
/// points in the exit direction) and additionally described in a labeled block
/// below the grid that includes remaining queue contents.
class TextRenderer {
  static const _avatarSymbol = '@';

  /// Render the board to a text string.
  ///
  /// Returns a multi-line string where each character is one cell.
  /// Set [includeLegend] to false to omit the legend line.
  /// When [kindSymbolOverrides] is provided, entity kind IDs are rendered
  /// using the mapped symbol instead of the game-defined symbol (anonymous mode).
  static String render(LevelState state, GameDefinition game,
      {bool includeLegend = true,
      Map<String, String>? kindSymbolOverrides,
      LevelDefinition? level}) {
    final effectiveGame =
        level == null ? game : game.withSystemOverrides(level.systemOverrides);
    final board = state.board;
    final w = board.width;
    final h = board.height;

    final overlay = state.overlay;
    // When an overlay is active, suppress the avatar from the grid so that
    // actual cell content is visible everywhere.
    final gridAvatarPos = overlay != null
        ? null
        : (state.avatar.enabled ? state.avatar.position : null);

    // Build a position→symbol map for multi-cell objects (pipe bodies, etc.)
    // Exit cell gets a directional arrow matching the exit direction (▲▼◄►).
    // Body cells get a direction-aware Unicode box-drawing symbol:
    //   ═ horizontal, ║ vertical, ╬ corner/junction.
    final mcoSymbols = <Position, String>{};
    for (final mco in state.board.multiCellObjects) {
      final exitList = mco.params['exitPosition'] as List?;
      final exitPos = exitList != null
          ? Position(exitList[0] as int, exitList[1] as int)
          : null;
      final exitDir = mco.params['exitDirection'] as String?;
      final cellSet = mco.cells.toSet();
      for (final cell in mco.cells) {
        if (cell == exitPos) {
          mcoSymbols[cell] = switch (exitDir) {
            'up' => '▲',
            'left' => '◄',
            'right' => '►',
            _ => '▼', // 'down' or unknown
          };
          continue;
        }
        final h = cellSet.contains(Position(cell.x - 1, cell.y)) ||
            cellSet.contains(Position(cell.x + 1, cell.y));
        final v = cellSet.contains(Position(cell.x, cell.y - 1)) ||
            cellSet.contains(Position(cell.x, cell.y + 1));
        mcoSymbols[cell] = (h && !v)
            ? '═'
            : (!h && v)
                ? '║'
                : '╬';
      }
    }
    final concealedPositions =
        _observationConcealedPositions(state, effectiveGame);
    final layerOrder = _orderedLayerIds(state, effectiveGame);

    final lines = <String>[];
    for (int y = 0; y < h; y++) {
      final sb = StringBuffer();
      for (int x = 0; x < w; x++) {
        final pos = Position(x, y);

        // Avatar takes highest priority (suppressed when overlay is active).
        if (gridAvatarPos == pos) {
          sb.write(_avatarSymbol);
          continue;
        }

        // Find the most prominent symbol from the declared layer order, with
        // an MCO body between non-ground layers and ground.
        // MCO is placed above ground so pipe shapes are visible even when
        // the ground layer is void/empty.
        String? objectSymbol; // from actors, markers, or objects layers
        String? groundSymbol; // from ground layer only
        final mcoSymbol = mcoSymbols[pos];
        if (concealedPositions.contains(pos) && mcoSymbol != null) {
          sb.write(mcoSymbol);
          continue;
        }
        for (final layerId in layerOrder) {
          final entity = board.getEntity(layerId, pos);
          if (entity == null) continue;
          final kindDef = effectiveGame.entityKinds[entity.kind];
          String? sym;
          if (kindDef == null) {
            sym = entity.kind[0].toUpperCase();
          } else if (kindDef.symbolParam != null) {
            // Number tiles always render as 'N' regardless of anon mode.
            final paramVal = entity.param(kindDef.symbolParam!);
            sym = paramVal != null
                ? _valueToChar(paramVal as int)
                : kindDef.symbol;
          } else if (kindSymbolOverrides != null &&
              kindSymbolOverrides.containsKey(entity.kind)) {
            sym = kindSymbolOverrides[entity.kind];
          } else {
            sym = kindDef.symbol;
          }
          if (layerId == 'ground') {
            groundSymbol = sym;
          } else {
            objectSymbol = sym;
            break;
          }
        }

        sb.write(objectSymbol ?? mcoSymbol ?? groundSymbol ?? '.');
      }
      lines.add(sb.toString());
    }

    final gridStr = lines.join('\n');

    final parts = <String>[gridStr];

    if (includeLegend) {
      final legend = _buildLegend(state, effectiveGame, gridAvatarPos != null,
          kindSymbolOverrides: kindSymbolOverrides,
          concealedPositions: concealedPositions,
          layerOrder: layerOrder);
      parts.add(
          'Each character is one cell, each line is one row. Legend: $legend');
    }

    final numbersBlock = _buildNumbersBlock(
        state, effectiveGame, concealedPositions, layerOrder);
    if (numbersBlock.isNotEmpty) parts.add(numbersBlock);

    final overlayBlock = _buildOverlayBlock(
        state, effectiveGame, mcoSymbols, concealedPositions, layerOrder,
        kindSymbolOverrides: kindSymbolOverrides);
    if (overlayBlock.isNotEmpty) parts.add(overlayBlock);

    final stackedBlock = _buildStackedBlock(state, effectiveGame, gridAvatarPos,
        mcoSymbols, concealedPositions, layerOrder,
        kindSymbolOverrides: kindSymbolOverrides);
    if (stackedBlock.isNotEmpty) parts.add(stackedBlock);

    final mcoBlock = _buildMcoBlock(state, effectiveGame,
        kindSymbolOverrides: kindSymbolOverrides);
    if (mcoBlock.isNotEmpty) parts.add(mcoBlock);

    final targetStatusBlock = _buildElasticTargetStatusBlock(
        state, effectiveGame, level,
        kindSymbolOverrides: kindSymbolOverrides);
    if (targetStatusBlock.isNotEmpty) parts.add(targetStatusBlock);

    return parts.join('\n\n');
  }

  /// True when the legend entry adds no information beyond the symbol itself.
  /// Catches single-digit symbols whose only label is the digit itself or
  /// the auto-derived "num <digit>" — e.g. "8=num 8" from diagonal_swipes
  /// where each digit tile is its own entity kind.
  static bool _isLegendRedundant(String sym, String label) {
    final s = sym.trim();
    final l = label.trim().toLowerCase();
    if (s.length != 1) return false;
    final c = s.codeUnitAt(0);
    if (c < 0x30 || c > 0x39) return false; // not a digit
    return l == s || l == 'num $s';
  }

  /// Board-layer contents hidden by an opaque authored multi-cell piece.
  ///
  /// This is opt-in so games that intentionally expose overlap (for example,
  /// a body covering a target) keep their existing observation contract.
  static Set<Position> _observationConcealedPositions(
      LevelState state, GameDefinition game) {
    return {
      for (final mco in state.board.multiCellObjects)
        if (game.hasTag(mco.kind, 'observation_occluder')) ...mco.cells,
    };
  }

  /// Board layers from visually topmost to bottommost.
  ///
  /// The DSL declaration is bottom-to-top, matching the Flutter board. Text
  /// observations reverse that exact order when choosing a cell's top symbol.
  static List<String> _orderedLayerIds(LevelState state, GameDefinition game) {
    final declared = [
      for (final layer in game.layers)
        if (state.board.layers.containsKey(layer.id)) layer.id,
    ];
    final declaredSet = declared.toSet();
    final remaining = [
      for (final layerId in state.board.layers.keys)
        if (!declaredSet.contains(layerId)) layerId,
    ];
    return [...declared, ...remaining].reversed.toList(growable: false);
  }

  static String _buildLegend(
      LevelState state, GameDefinition game, bool hasAvatar,
      {Map<String, String>? kindSymbolOverrides,
      required Set<Position> concealedPositions,
      required List<String> layerOrder}) {
    final seen = <String, String>{}; // symbol -> label
    if (hasAvatar) seen[_avatarSymbol] = 'avatar (you)';

    for (final layerId in layerOrder) {
      final layer = state.board.layers[layerId]!;
      for (final entry in layer.entries()) {
        if (concealedPositions.contains(entry.key)) continue;
        final entity = entry.value;
        final kindDef = game.entityKinds[entity.kind];
        if (kindDef == null) continue;

        String sym;
        String label;
        if (kindDef.symbolParam != null) {
          // Number tiles always 'N'; exact values in "Number values" block.
          sym = 'N';
          if (kindSymbolOverrides != null) {
            label = '? (exact value in "Number values")';
          } else {
            final name = kindDef.uiName ?? kindDef.id.replaceAll('_', ' ');
            final extra =
                kindDef.description != null ? '; ${kindDef.description}' : '';
            label = '$name (exact value in "Number values"$extra)';
          }
        } else if (kindSymbolOverrides != null &&
            kindSymbolOverrides.containsKey(entity.kind)) {
          sym = kindSymbolOverrides[entity.kind]!;
          label = '?';
        } else {
          sym = kindDef.symbol;
          final desc =
              kindDef.description != null ? ' (${kindDef.description})' : '';
          label = '${kindDef.uiName ?? kindDef.id.replaceAll('_', ' ')}$desc';
        }

        if (seen.containsKey(sym) || _isLegendRedundant(sym, label)) continue;
        seen[sym] = label;
      }
    }

    if (state.board.multiCellObjects.isNotEmpty) {
      final labels = <String>[];
      for (final mco in state.board.multiCellObjects) {
        final label = kindSymbolOverrides != null
            ? '?'
            : (game.entityKinds[mco.kind]?.uiName ??
                mco.kind.replaceAll('_', ' '));
        if (!labels.contains(label)) labels.add(label);
      }
      seen['║/═/╬'] = labels.length == 1
          ? '${labels.first} body'
          : 'multi-cell object body';
      if (state.board.multiCellObjects
          .any((mco) => mco.params['exitPosition'] != null)) {
        seen['▲/▼/◄/►'] = 'multi-cell object exit (arrow = exit direction)';
      }
    }

    return seen.entries.map((e) => '${e.key}=${e.value}').join('  ');
  }

  /// Show the overlay region as a focused mini-view of its cells. Without this
  /// the model would only see the bounds ("Overlay region: (0,0)–(1,1)") and
  /// have to mentally re-extract the contents from the full grid each turn.
  static String _buildOverlayBlock(
      LevelState state,
      GameDefinition game,
      Map<Position, String> mcoSymbols,
      Set<Position> concealedPositions,
      List<String> layerOrder,
      {Map<String, String>? kindSymbolOverrides}) {
    final overlay = state.overlay;
    if (overlay == null) return '';

    final x1 = overlay.x;
    final y1 = overlay.y;
    final x2 = overlay.x + overlay.width - 1;
    final y2 = overlay.y + overlay.height - 1;

    final rows = <String>[];
    for (int dy = 0; dy < overlay.height; dy++) {
      final buf = StringBuffer();
      for (int dx = 0; dx < overlay.width; dx++) {
        final x = x1 + dx, y = y1 + dy;
        final pos = Position(x, y);
        if (concealedPositions.contains(pos) && mcoSymbols.containsKey(pos)) {
          buf.write(mcoSymbols[pos]);
          continue;
        }
        String sym = '.';
        for (final layerId in layerOrder) {
          final entity = state.board.getEntity(layerId, pos);
          if (entity == null) continue;
          final kindDef = game.entityKinds[entity.kind];
          if (kindDef == null) continue;
          if (kindDef.symbolParam != null) {
            final paramVal = entity.param(kindDef.symbolParam!);
            sym = paramVal != null
                ? _valueToChar(paramVal as int)
                : kindDef.symbol;
          } else if (kindSymbolOverrides != null &&
              kindSymbolOverrides.containsKey(entity.kind)) {
            sym = kindSymbolOverrides[entity.kind]!;
          } else {
            sym = kindDef.symbol;
          }
          break;
        }
        buf.write(sym);
      }
      rows.add(buf.toString());
    }
    final contents = rows.join('\n');
    return 'Overlay region: ($x1,$y1)–($x2,$y2). These are the '
        '${overlay.width}×${overlay.height} cells your selection-based actions '
        'operate on:\n$contents';
  }

  /// Reports cells where more than one layer has a visible entity, so the LLM
  /// knows the grid symbol hides additional content beneath it.
  static String _buildStackedBlock(
      LevelState state,
      GameDefinition game,
      Position? avatarPos,
      Map<Position, String> mcoSymbols,
      Set<Position> concealedPositions,
      List<String> layerOrder,
      {Map<String, String>? kindSymbolOverrides}) {
    final entries = <String>[];

    final w = state.board.width;
    final h = state.board.height;
    for (int y = 0; y < h; y++) {
      for (int x = 0; x < w; x++) {
        final pos = Position(x, y);
        final symbols = <String>[];

        if (!concealedPositions.contains(pos)) {
          for (final layerId in layerOrder) {
            final entity = state.board.getEntity(layerId, pos);
            if (entity == null) continue;
            final kindDef = game.entityKinds[entity.kind];
            String sym;
            String label;
            if (kindDef == null) {
              sym = entity.kind[0].toUpperCase();
              label = kindSymbolOverrides != null
                  ? '?'
                  : entity.kind.replaceAll('_', ' ');
            } else if (kindDef.symbolParam != null) {
              final paramVal = entity.param(kindDef.symbolParam!);
              sym = paramVal != null
                  ? _valueToChar(paramVal as int)
                  : kindDef.symbol;
              label = kindSymbolOverrides != null
                  ? '?'
                  : (kindDef.uiName ?? kindDef.id.replaceAll('_', ' '));
            } else if (kindSymbolOverrides != null &&
                kindSymbolOverrides.containsKey(entity.kind)) {
              sym = kindSymbolOverrides[entity.kind]!;
              label = '?';
            } else {
              sym = kindDef.symbol;
              label = kindDef.uiName ?? kindDef.id.replaceAll('_', ' ');
            }
            // Skip void/empty cells. In anon mode the symbol may be
            // overridden, so check both the display symbol and the original
            // game symbol.
            final originalSym = kindDef?.symbol ?? sym;
            if (sym == '.' ||
                sym == ' ' ||
                originalSym == '.' ||
                originalSym == ' ') continue;
            symbols.add('[$layerId] $sym($label)');
          }
        }

        // Avatar counts as an extra layer on top (only when shown in grid).
        if (avatarPos == pos) symbols.insert(0, '[avatar] @(avatar)');

        final mcoSymbol = mcoSymbols[pos];
        if (mcoSymbol != null) {
          MultiCellObjectInstance? mco;
          for (final item in state.board.multiCellObjects) {
            if (item.cells.contains(pos)) {
              mco = item;
              break;
            }
          }
          final label = kindSymbolOverrides != null
              ? '?'
              : (mco == null
                  ? 'multi-cell object'
                  : (game.entityKinds[mco.kind]?.uiName ??
                      mco.kind.replaceAll('_', ' ')));
          final layer = mco == null
              ? 'structures'
              : (game.entityKinds[mco.kind]?.layer ?? 'structures');
          symbols.add('[$layer] $mcoSymbol($label)');
        }

        if (symbols.length >= 2) {
          entries.add('  ($x,$y): ${symbols.join(' + ')}');
        }
      }
    }

    if (entries.isEmpty) return '';
    return 'Stacked cells (grid shows only top symbol):\n${entries.join('\n')}';
  }

  static String _buildElasticTargetStatusBlock(
      LevelState state, GameDefinition game, LevelDefinition? level,
      {Map<String, String>? kindSymbolOverrides}) {
    if (level == null || kindSymbolOverrides != null) return '';

    SystemDef? system;
    for (final candidate in game.systems) {
      if (candidate.type == 'elastic_block' && candidate.enabled) {
        system = candidate;
        break;
      }
    }
    if (system == null) return '';
    final config = system.config;
    final targets = config['targets'] as List? ?? const [];
    if (targets.isEmpty) return '';

    final objectKind = config['objectKind']?.toString() ?? 'elastic_block';
    final objectName =
        game.entityKinds[objectKind]?.uiName ?? objectKind.replaceAll('_', ' ');
    MultiCellObjectInstance? block;
    for (final mco in state.board.multiCellObjects) {
      if (mco.kind == objectKind) {
        block = mco;
        break;
      }
    }
    final blockCells = block?.cells.toSet() ?? <Position>{};
    final completedKey = config['completedTargetIdsVariable']?.toString() ??
        'completedTargetIds';
    final consumedKey =
        config['consumedTargetIdsVariable']?.toString() ?? 'consumedTargetIds';
    final completed = (state.variables[completedKey] as List? ?? const [])
        .map((value) => value.toString())
        .toSet();
    final consumed = (state.variables[consumedKey] as List? ?? const [])
        .map((value) => value.toString())
        .toSet();
    final defaultLayer = config['targetLayer']?.toString() ?? 'markers';
    final initialBoard = level.initialState().board;

    final lines = <String>[
      'Target status (exact $objectName footprint match required):'
    ];
    for (final rawTarget in targets) {
      if (rawTarget is! Map) continue;
      final target = Map<String, dynamic>.from(rawTarget);
      final markerKind = target['markerKind']?.toString() ?? '';
      final targetId = target['id']?.toString() ?? markerKind;
      if (markerKind.isEmpty || targetId.isEmpty) continue;
      final markerLayer = target['markerLayer']?.toString() ?? defaultLayer;
      final layer = initialBoard.layers[markerLayer];
      if (layer == null) continue;
      final cells = <Position>[
        for (final entry in layer.entries())
          if (entry.value.kind == markerKind) entry.key,
      ]..sort((left, right) {
          final byY = left.y.compareTo(right.y);
          return byY != 0 ? byY : left.x.compareTo(right.x);
        });
      if (cells.isEmpty) continue;

      final markerDef = game.entityKinds[markerKind];
      final targetName = markerDef?.uiName ?? markerKind.replaceAll('_', ' ');
      final displayName =
          markerDef == null ? targetName : '$targetName [${markerDef.symbol}]';
      final geometry = cells.map((cell) => '(${cell.x},${cell.y})').join(' ');
      final overlap = cells.where(blockCells.contains).length;
      final mode = target['onLeave']?.toString() ?? 'none';

      late final String status;
      if (consumed.contains(targetId)) {
        if (mode == 'wall') {
          final wallKind = target['wallKind']?.toString() ?? 'wall';
          final wallName = game.entityKinds[wallKind]?.uiName ??
              wallKind.replaceAll('_', ' ');
          status = 'completed and converted to $wallName after full vacancy';
        } else if (mode == 'void') {
          status = 'completed and converted to void after full vacancy';
        } else {
          status = 'completed and removed after full vacancy';
        }
      } else if (completed.contains(targetId)) {
        final suffix = switch (mode) {
          'wall' =>
            '; becomes a wall only after the $objectName fully vacates it',
          'void' =>
            '; becomes void only after the $objectName fully vacates it',
          _ => '',
        };
        status = 'completed, still occupied by $objectName$suffix';
      } else {
        status = 'unfinished ($overlap/${cells.length} cells covered)';
      }
      lines.add('  $displayName: cells $geometry; $status');
    }

    return lines.length > 1 ? lines.join('\n') : '';
  }

  /// Returns the grid symbol for a numeric tile value.
  /// Always 'N' — exact values are listed in the "Number values" block.
  static String _valueToChar(int v) => 'N';

  /// Lists all number-valued tiles with their exact decimal values.
  /// Appears below the legend so the LLM always knows precise values even when
  /// the grid symbol is compressed (A–F or ?).
  static String _buildNumbersBlock(LevelState state, GameDefinition game,
      Set<Position> concealedPositions, List<String> layerOrder) {
    final entries = <String>[];
    final w = state.board.width;
    final h = state.board.height;
    for (int y = 0; y < h; y++) {
      for (int x = 0; x < w; x++) {
        final pos = Position(x, y);
        if (concealedPositions.contains(pos)) continue;
        for (final layerId in layerOrder) {
          final entity = state.board.getEntity(layerId, pos);
          if (entity == null) continue;
          final kindDef = game.entityKinds[entity.kind];
          if (kindDef?.symbolParam == null) continue;
          final paramVal = entity.param(kindDef!.symbolParam!);
          if (paramVal == null) break;
          entries.add('($x,$y)=${paramVal as int}');
          break;
        }
      }
    }
    if (entries.isEmpty) return '';
    return 'Number values: ${entries.join('  ')}';
  }

  /// Renders each multi-cell object as a labeled block (separate from the grid).
  static String _buildMcoBlock(LevelState state, GameDefinition game,
      {Map<String, String>? kindSymbolOverrides}) {
    if (state.board.multiCellObjects.isEmpty) return '';

    final sb = StringBuffer();
    sb.writeln('Multi-cell objects:');

    var publicPieceIndex = 0;
    for (final mco in state.board.multiCellObjects) {
      final kindDef = game.entityKinds[mco.kind];
      final label = kindSymbolOverrides != null
          ? '?'
          : (kindDef?.uiName ?? mco.kind.replaceAll('_', ' '));
      final isPublicPiece = game.hasTag(mco.kind, 'public_piece');
      final pieceName = isPublicPiece ? 'Piece ${++publicPieceIndex}' : mco.id;
      sb.writeln('  $pieceName [$label]');

      final axis = mco.params['axis']?.toString();
      if (axis != null && axis.isNotEmpty) {
        sb.writeln('    axis: $axis');
      }

      // Cells with exit marker including direction.
      final exitList = mco.params['exitPosition'] as List?;
      final exitPos = exitList != null
          ? Position(exitList[0] as int, exitList[1] as int)
          : null;
      final exitDir = mco.params['exitDirection'] as String?;
      final exitTag = exitDir != null ? '[exit→$exitDir]' : '[exit]';
      final cellStr = mco.cells.map((p) {
        final tag = p == exitPos ? exitTag : '';
        return '(${p.x},${p.y})$tag';
      }).join(' ');
      sb.writeln('    ${isPublicPiece ? 'footprint' : 'cells'}: $cellStr');

      // Compute spawn position: one step from exit in exitDirection.
      Position? spawnPos;
      if (exitPos != null && exitDir != null) {
        spawnPos = switch (exitDir) {
          'right' => Position(exitPos.x + 1, exitPos.y),
          'left' => Position(exitPos.x - 1, exitPos.y),
          'down' => Position(exitPos.x, exitPos.y + 1),
          'up' => Position(exitPos.x, exitPos.y - 1),
          _ => null,
        };
      }

      // Queue contents — skip already-emitted items (tracked by currentIndex).
      // Items are released one per turn at the spawn cell when it is empty.
      final queue = mco.params['queue'] as List?;
      if (queue != null) {
        final currentIndex = (mco.params['currentIndex'] as int?) ?? 0;
        final remaining = queue.skip(currentIndex).toList();
        final spawnStr = spawnPos != null
            ? ' (next spawns at (${spawnPos.x},${spawnPos.y}))'
            : '';
        if (remaining.isNotEmpty) {
          final queueStr = remaining.map((v) => '$v').join(' → ');
          sb.writeln('    queue$spawnStr: $queueStr');
        } else {
          sb.writeln('    queue$spawnStr: (empty)');
        }
      }
    }

    // Remove trailing newline from writeln.
    return sb.toString().trimRight();
  }
}
