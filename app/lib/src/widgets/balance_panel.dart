import 'package:flutter/material.dart';
import 'package:gridponder_engine/engine.dart';
import 'board_renderer.dart' show cellNamedColor;

/// Reads the configured balance regions from the displayed board, including
/// during animation. No pack names or machine kinds are assumed.
class BalancePanel extends StatelessWidget {
  final GameDefinition game;
  final LevelState state;
  final Map<String, String>? palette;

  const BalancePanel({
    super.key,
    required this.game,
    required this.state,
    this.palette,
  });

  @override
  Widget build(BuildContext context) {
    final panels = <Widget>[];
    for (final system in game.systems) {
      if (!system.enabled || system.type != 'balance_regions') continue;
      final groups = system.config['groups'];
      if (groups is! Map) continue;
      for (final group in groups.values) {
        if (group is! Map) continue;
        final pans = group['pans'];
        if (pans is! List || pans.length != 2 || pans.any((p) => p is! Map)) {
          continue;
        }
        final groundLayer = group['groundLayer'] as String? ?? 'ground';
        int? panAt(Position pos) {
          final ground = state.board.getEntity(groundLayer, pos);
          if (ground == null) return null;
          for (var i = 0; i < 2; i++) {
            final tags = pans[i]['groundTags'];
            if (tags is List &&
                tags.any((tag) => game.hasTag(ground.kind, '$tag'))) {
              return i;
            }
          }
          return null;
        }

        final ground = state.board.layers[groundLayer];
        if (ground == null ||
            !ground.entries().any((e) => panAt(e.key) != null)) {
          continue;
        }
        final names = [
          for (var i = 0; i < 2; i++) '${pans[i]['name'] ?? 'Side ${i + 1}'}',
        ];
        final totals = [0, 0];
        final weights = group['weights'] is Map
            ? group['weights'] as Map
            : const {};
        final layers = group['weightLayers'] is List
            ? group['weightLayers'] as List
            : const ['actors'];
        for (final id in layers) {
          final layer = state.board.layers['$id'];
          if (layer == null) continue;
          for (final entry in layer.entries()) {
            final weight = weights[entry.value.kind];
            final index = panAt(entry.key);
            if (weight is int && index != null) totals[index] += weight;
          }
        }
        final avatarWeight = group['avatarWeight'] ?? 1;
        final position = state.avatar.position;
        if (state.avatar.enabled && position != null && avatarWeight is int) {
          final index = panAt(position);
          if (index != null) totals[index] += avatarWeight;
        }
        final colors = List<Color>.filled(
          2,
          Theme.of(context).colorScheme.primary,
        );
        for (final entry in ground.entries()) {
          final index = panAt(entry.key);
          if (index == null) continue;
          final color = game.entityKinds[entry.value.kind]?.display?['color'];
          if (color is String) {
            colors[index] = cellNamedColor(color, palette: palette);
          }
        }
        String title(String name) => name[0].toUpperCase() + name.substring(1);
        final winner = totals[0] == totals[1]
            ? null
            : totals[0] > totals[1]
            ? 0
            : 1;
        final status = winner == null
            ? 'Balanced'
            : '${title(names[winner])} heavier';
        final leaves = group['leaves'];
        final markers = state.board.layers[group['markerLayer'] ?? 'objects'];
        final bridges = <String>[];
        if (leaves is List && markers != null) {
          for (final leaf in leaves) {
            if (leaf is! Map) continue;
            final cells = markers
                .entries()
                .where((e) => e.value.kind == leaf['marker'])
                .toList();
            if (cells.isEmpty) continue;
            final solid = cells
                .where(
                  (e) =>
                      state.board.getEntity(groundLayer, e.key)?.kind ==
                      leaf['solidKind'],
                )
                .length;
            final label = game.entityKinds[leaf['marker']]?.uiName ?? 'Bridge';
            bridges.add(
              '$label: ${solid == cells.length
                  ? 'BRIDGE'
                  : solid == 0
                  ? 'GAP'
                  : '$solid/${cells.length} bridges'}',
            );
          }
        }
        panels.add(
          Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: Colors.white,
              border: Border.all(color: Colors.black26),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Wrap(
                  alignment: WrapAlignment.center,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  spacing: 12,
                  runSpacing: 6,
                  children: [
                    for (var i = 0; i < 2; i++)
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 5,
                        ),
                        decoration: BoxDecoration(
                          color: colors[i],
                          border: Border.all(color: Colors.black38),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(
                          '${title(names[i])}: ${totals[i]}',
                          style: const TextStyle(
                            color: Colors.black,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                    Text(
                      status,
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        color: Colors.black87,
                      ),
                    ),
                  ],
                ),
                if (bridges.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Text(
                      bridges.join('   •   '),
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontSize: 12,
                        color: Colors.black87,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        );
      }
    }
    return Column(mainAxisSize: MainAxisSize.min, children: panels);
  }
}
