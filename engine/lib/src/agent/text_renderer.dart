import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// Renders a [LevelState] as a compact text grid using Unicode symbols.
///
/// Each cell shows the "most prominent" entity across all layers.
/// Priority (highest first): avatar, actors, markers, objects, MCO body, ground.
///
/// The text symbol for each entity kind is defined by [EntityKindDef.symbol]
/// in game.json. All symbols must be single Unicode characters with display
/// width 1 (narrow). The only hardcoded symbol is '@' for the avatar (an
/// engine concept, not an entity kind). Entity kinds with [EntityKindDef.symbolParam]
/// show the value of that instance parameter at render time (e.g. number tiles
/// show their numeric value).
///
/// Multi-cell objects (e.g. pipes) are rendered with direction-aware symbols
/// in the grid (═ horizontal, ║ vertical, ╬ junction, ▼ exit) and additionally
/// described in a labeled block below the grid that includes queue contents.
class TextRenderer {
  static const _avatarSymbol = '@';

  /// Render the board to a text string.
  ///
  /// Returns a multi-line string where each character is one cell.
  /// Includes an overlay region marker if present.
  /// Set [includeLegend] to false to omit the legend line.
  static String render(LevelState state, GameDefinition game,
      {bool includeLegend = true}) {
    final board = state.board;
    final w = board.width;
    final h = board.height;

    // Build overlay set for highlighting.
    final Set<Position> overlayPositions = {};
    final overlay = state.overlay;
    if (overlay != null) {
      for (int dy = 0; dy < overlay.height; dy++) {
        for (int dx = 0; dx < overlay.width; dx++) {
          overlayPositions.add(Position(overlay.x + dx, overlay.y + dy));
        }
      }
    }

    final avatarPos = state.avatar.enabled ? state.avatar.position : null;

    // Build a position→symbol map for multi-cell objects (pipe bodies, etc.)
    // Exit cell gets ▼. Body cells get a direction-aware Unicode box-drawing symbol:
    //   ═ horizontal, ║ vertical, ╬ corner/junction.
    final mcoSymbols = <Position, String>{};
    for (final mco in state.board.multiCellObjects) {
      final exitList = mco.params['exitPosition'] as List?;
      final exitPos = exitList != null
          ? Position(exitList[0] as int, exitList[1] as int)
          : null;
      final cellSet = mco.cells.toSet();
      for (final cell in mco.cells) {
        if (cell == exitPos) {
          mcoSymbols[cell] = '▼';
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

        // Avatar takes highest priority.
        if (avatarPos == pos) {
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
            final paramVal = entity.param(kindDef.symbolParam!);
            sym = paramVal != null ? '${paramVal % 10}' : kindDef.symbol;
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

        final char = objectSymbol ?? mcoSymbol ?? groundSymbol ?? '.';

        // Overlay region: mark corners with bracket characters.
        if (overlay != null && overlayPositions.contains(pos)) {
          final isTopLeft = pos == Position(overlay.x, overlay.y);
          final isTopRight =
              pos == Position(overlay.x + overlay.width - 1, overlay.y);
          final isBottomLeft =
              pos == Position(overlay.x, overlay.y + overlay.height - 1);
          final isBottomRight = pos ==
              Position(overlay.x + overlay.width - 1,
                  overlay.y + overlay.height - 1);
          if (isTopLeft) sb.write('[');
          else if (isTopRight) sb.write(']');
          else if (isBottomLeft) sb.write('{');
          else if (isBottomRight) sb.write('}');
          else sb.write(char);
        } else {
          sb.write(char);
        }
      }
      lines.add(sb.toString());
    }

    final gridStr = lines.join('\n');

    final parts = <String>[gridStr];

    if (includeLegend) {
      final legend = _buildLegend(state, game, avatarPos != null);
      parts.add('Legend: $legend');
    }

    final mcoBlock = _buildMcoBlock(state, game);
    if (mcoBlock.isNotEmpty) parts.add(mcoBlock);

    return parts.join('\n\n');
  }

  static String _buildLegend(
      LevelState state, GameDefinition game, bool hasAvatar) {
    final seen = <String, String>{}; // symbol -> label
    if (hasAvatar) seen[_avatarSymbol] = 'avatar (you)';

    for (final layer in state.board.layers.values) {
      for (final entry in layer.entries()) {
        final entity = entry.value;
        final kindDef = game.entityKinds[entity.kind];
        if (kindDef == null) continue;

        final sym = kindDef.symbol; // legend always uses the static symbol
        if (!seen.containsKey(sym)) {
          final label = kindDef.uiName ?? kindDef.id.replaceAll('_', ' ');
          final suffix = kindDef.symbolParam != null ? ' (0–9)' : '';
          seen[sym] = '$label$suffix';
        }
      }
    }

    if (state.overlay != null) seen['[...]'] = 'overlay region';

    return seen.entries.map((e) => '${e.key}=${e.value}').join('  ');
  }

  /// Renders each multi-cell object as a labeled block (separate from the grid).
  static String _buildMcoBlock(LevelState state, GameDefinition game) {
    if (state.board.multiCellObjects.isEmpty) return '';

    final sb = StringBuffer();
    sb.writeln('Multi-cell objects:');

    for (final mco in state.board.multiCellObjects) {
      final kindDef = game.entityKinds[mco.kind];
      final label = kindDef?.uiName ?? mco.kind.replaceAll('_', ' ');
      sb.writeln('  ${mco.id} [$label]');

      // Cells with exit marker.
      final exitList = mco.params['exitPosition'] as List?;
      final exitPos = exitList != null
          ? Position(exitList[0] as int, exitList[1] as int)
          : null;
      final cellStr = mco.cells.map((p) {
        final tag = p == exitPos ? '[exit]' : '';
        return '(${p.x},${p.y})$tag';
      }).join(' ');
      sb.writeln('    cells: $cellStr');

      // Queue contents if present. Items are not yet on the board; they will
      // be released one per turn at the exit cell when it is empty.
      final queue = mco.params['queue'] as List?;
      if (queue != null && queue.isNotEmpty) {
        final exitStr =
            exitPos != null ? ' (releases at exit (${exitPos.x},${exitPos.y}))' : '';
        final queueStr = queue.map((v) => '$v').join(' → ');
        sb.writeln('    queue$exitStr: $queueStr');
      } else if (queue != null) {
        sb.writeln('    queue: (empty)');
      }
    }

    // Remove trailing newline from writeln.
    return sb.toString().trimRight();
  }
}
