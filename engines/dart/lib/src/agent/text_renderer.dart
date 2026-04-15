import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// Renders a [LevelState] as a compact text grid using Unicode symbols.
///
/// Each cell shows the "most prominent" entity across all layers.
/// Priority (highest first): avatar, actors, markers, objects, MCO body, ground.
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
      {bool includeLegend = true, Map<String, String>? kindSymbolOverrides}) {
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
        mcoSymbols[cell] = (h && !v) ? '═' : (!h && v) ? '║' : '╬';
      }
    }

    final layerOrder = ['actors', 'markers', 'objects', 'ground'];

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

        // Find the most prominent symbol, with priority:
        //   avatar > objects/markers/actors > MCO body > ground
        // MCO is placed above ground so pipe shapes are visible even when
        // the ground layer is void/empty.
        String? objectSymbol; // from actors, markers, or objects layers
        String? groundSymbol; // from ground layer only
        final mcoSymbol = mcoSymbols[pos];
        for (final layerId in layerOrder) {
          final entity = board.getEntity(layerId, pos);
          if (entity == null) continue;
          final kindDef = game.entityKinds[entity.kind];
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
      final legend = _buildLegend(state, game, gridAvatarPos != null,
          kindSymbolOverrides: kindSymbolOverrides);
      parts.add('Each character is one cell, each line is one row. Legend: $legend');
    }

    final numbersBlock = _buildNumbersBlock(state, game);
    if (numbersBlock.isNotEmpty) parts.add(numbersBlock);

    final overlayBlock = _buildOverlayBlock(state, game);
    if (overlayBlock.isNotEmpty) parts.add(overlayBlock);

    final stackedBlock = _buildStackedBlock(state, game, gridAvatarPos,
        kindSymbolOverrides: kindSymbolOverrides);
    if (stackedBlock.isNotEmpty) parts.add(stackedBlock);

    final mcoBlock = _buildMcoBlock(state, game,
        kindSymbolOverrides: kindSymbolOverrides);
    if (mcoBlock.isNotEmpty) parts.add(mcoBlock);

    return parts.join('\n\n');
  }

  static String _buildLegend(
      LevelState state, GameDefinition game, bool hasAvatar,
      {Map<String, String>? kindSymbolOverrides}) {
    final seen = <String, String>{}; // symbol -> label
    if (hasAvatar) seen[_avatarSymbol] = 'avatar (you)';

    for (final layer in state.board.layers.values) {
      for (final entry in layer.entries()) {
        final entity = entry.value;
        final kindDef = game.entityKinds[entity.kind];
        if (kindDef == null) continue;

        String sym;
        String label;
        if (kindDef.symbolParam != null) {
          // Number tiles always 'N'; exact values in "Number values" block.
          sym = 'N';
          label = kindSymbolOverrides != null
              ? '? (exact value in "Number values")'
              : '${kindDef.uiName ?? kindDef.id.replaceAll('_', ' ')} (exact value in "Number values")';
        } else if (kindSymbolOverrides != null &&
            kindSymbolOverrides.containsKey(entity.kind)) {
          sym = kindSymbolOverrides[entity.kind]!;
          label = '?';
        } else {
          sym = kindDef.symbol;
          final desc = kindDef.description != null
              ? ' (${kindDef.description})'
              : '';
          label = '${kindDef.uiName ?? kindDef.id.replaceAll('_', ' ')}$desc';
        }

        if (!seen.containsKey(sym)) seen[sym] = label;
      }
    }

    if (state.board.multiCellObjects.isNotEmpty) {
      seen['║/═'] = 'pipe body';
      seen['▲/▼/◄/►'] = 'pipe exit (arrow = exit direction)';
    }

    return seen.entries.map((e) => '${e.key}=${e.value}').join('  ');
  }

  /// Renders the active overlay region as a labeled block showing its bounds
  /// and the content of every cell it covers. The avatar position is included
  /// when the overlay is active (since @ is suppressed from the grid).
  static String _buildOverlayBlock(LevelState state, GameDefinition game) {
    final overlay = state.overlay;
    if (overlay == null) return '';

    final x1 = overlay.x;
    final y1 = overlay.y;
    final x2 = overlay.x + overlay.width - 1;
    final y2 = overlay.y + overlay.height - 1;

    return 'Overlay region: ($x1,$y1)–($x2,$y2)';
  }

  /// Reports cells where more than one layer has a visible entity, so the LLM
  /// knows the grid symbol hides additional content beneath it.
  static String _buildStackedBlock(
      LevelState state, GameDefinition game, Position? avatarPos,
      {Map<String, String>? kindSymbolOverrides}) {
    final layerOrder = ['actors', 'markers', 'objects', 'ground'];
    final entries = <String>[];

    final w = state.board.width;
    final h = state.board.height;
    for (int y = 0; y < h; y++) {
      for (int x = 0; x < w; x++) {
        final pos = Position(x, y);
        final symbols = <String>[];

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
          // Skip void/empty cells. In anon mode the symbol may be overridden,
          // so check both the display symbol and the original game symbol.
          final originalSym = kindDef?.symbol ?? sym;
          if (sym == '.' || sym == ' ' || originalSym == '.' || originalSym == ' ') continue;
          symbols.add('$sym($label)');
        }

        // Avatar counts as an extra layer on top (only when shown in grid).
        if (avatarPos == pos) symbols.insert(0, '@(avatar)');

        if (symbols.length >= 2) {
          entries.add('  ($x,$y): ${symbols.join(' + ')}');
        }
      }
    }

    if (entries.isEmpty) return '';
    return 'Stacked cells (grid shows only top symbol):\n${entries.join('\n')}';
  }

  /// Returns the grid symbol for a numeric tile value.
  /// Always 'N' — exact values are listed in the "Number values" block.
  static String _valueToChar(int v) => 'N';

  /// Lists all number-valued tiles with their exact decimal values.
  /// Appears below the legend so the LLM always knows precise values even when
  /// the grid symbol is compressed (A–F or ?).
  static String _buildNumbersBlock(LevelState state, GameDefinition game) {
    final entries = <String>[];
    final w = state.board.width;
    final h = state.board.height;
    const layerOrder = ['actors', 'markers', 'objects', 'ground'];
    for (int y = 0; y < h; y++) {
      for (int x = 0; x < w; x++) {
        final pos = Position(x, y);
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

    for (final mco in state.board.multiCellObjects) {
      final kindDef = game.entityKinds[mco.kind];
      final label = kindSymbolOverrides != null
          ? '?'
          : (kindDef?.uiName ?? mco.kind.replaceAll('_', ' '));
      sb.writeln('  ${mco.id} [$label]');

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
      sb.writeln('    cells: $cellStr');

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
        final spawnStr =
            spawnPos != null ? ' (next spawns at (${spawnPos.x},${spawnPos.y}))' : '';
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
