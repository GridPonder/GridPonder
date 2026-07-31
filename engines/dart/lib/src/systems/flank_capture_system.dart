import '../engine/game_system.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// Reversi/Othello-style bracket capture, applied after an actor moves.
///
/// When a piece moves, any straight run of one kind that ends up bracketed
/// between two of the opposing kind (or a terminating wall) is flipped to the
/// bracketing kind. Two configured [pairs] let the same rule work both ways: an
/// `alien` bracketing a run of `human` **possesses** it, while a run of `alien`
/// bracketed by `human` is **exposed** and flips back — the mover included.
///
/// The moved piece anchors every capture: a victim run flips only when the
/// mover is one of its two bracketing terminals (an attack) or a cell inside
/// the run itself (a self-capture). A single pre-flip snapshot of the piece
/// layer is taken up front; every pass reads it, so a cell can never flip twice
/// per move and the possess and expose passes never see each other's fresh
/// cells.
///
/// Generic: any game with two opposing piece kinds that flip on a straight-line
/// bracket names its own [pairs] and layer.
///
/// An aggressor may name several victim kinds (`"alien": ["human", "splinter"]`).
/// Each victim kind is scanned on its own pass, so runs stay homogeneous — a run
/// that mixes two victim kinds is not a maximal run of either, and is therefore
/// immune. When two aggressors share a victim kind, `order` decides: flips
/// dedupe first-writer-wins, so the aggressor listed earlier claims a contested
/// cell.
class FlankCaptureSystem extends GameSystem {
  final Map<String, dynamic>? config;

  const FlankCaptureSystem({required super.id, this.config})
      : super(type: 'flank_capture');

  @override
  List<GameEvent> executeCascadeResolution(
    List<GameEvent> triggerEvents,
    LevelState state,
    GameDefinition game,
  ) {
    final effectiveConfig = config ?? game.systemConfig(id, {});

    final configuredTriggers =
        (effectiveConfig['triggerEvents'] as List? ?? const ['actor_moved'])
            .map((value) => value.toString())
            .toSet();
    final dests = <Position>[];
    final seen = <String>{};
    for (final event in triggerEvents) {
      if (!configuredTriggers.contains(event.type)) continue;
      final pos = event.position;
      if (pos == null) continue;
      if (seen.add('${pos.x},${pos.y}')) dests.add(pos);
    }
    if (dests.isEmpty) return const [];

    final pieceLayerId = effectiveConfig['pieceLayer'] as String? ?? 'pieces';
    final layer = state.board.layers[pieceLayerId];
    if (layer == null) return const [];

    final pairs = (effectiveConfig['pairs'] as Map?)?.map(
          (k, v) => MapEntry(
            k.toString(),
            v is List
                ? v.map((e) => e.toString()).toList()
                : <String>[v.toString()],
          ),
        ) ??
        const <String, List<String>>{};
    if (pairs.isEmpty) return const [];
    final order = (effectiveConfig['order'] as List?)
            ?.map((value) => value.toString())
            .toList() ??
        pairs.keys.toList();
    final directions = (effectiveConfig['directions'] as List? ??
            const ['up', 'down', 'left', 'right'])
        .map((value) => value.toString())
        .toSet();
    final horizontal =
        directions.contains('left') || directions.contains('right');
    final vertical = directions.contains('up') || directions.contains('down');
    if (!horizontal && !vertical) return const [];
    final wallTerminates = effectiveConfig['wallTerminates'] as bool? ?? true;
    final wallLayer = effectiveConfig['wallLayer'] as String? ?? 'ground';
    final wallTag = effectiveConfig['wallTag'] as String? ?? 'solid';

    // Single pre-flip snapshot: "x,y" -> piece kind for every occupied cell.
    final snapshot = <String, String>{};
    for (final entry in layer.entries()) {
      snapshot['${entry.key.x},${entry.key.y}'] = entry.value.kind;
    }
    String? pieceAt(int x, int y) => snapshot['$x,$y'];
    bool isWall(int x, int y) =>
        wallTerminates &&
        state.board
            .hasTagAt(wallLayer, Position(x, y), wallTag, game.entityKinds);

    final width = state.board.width;
    final height = state.board.height;

    final flips = <String, String>{}; // "x,y" -> aggressor kind
    final ordered = <Position>[];

    void scanLine(
        List<Position> line, int bIndex, String aggressor, String victim) {
      final n = line.length;
      bool terminal(int idx) {
        if (idx < 0 || idx >= n) return false; // board edge is not a terminal
        final c = line[idx];
        if (isWall(c.x, c.y)) return true;
        return pieceAt(c.x, c.y) == aggressor;
      }

      var i = 0;
      while (i < n) {
        if (pieceAt(line[i].x, line[i].y) != victim) {
          i++;
          continue;
        }
        var j = i;
        while (j + 1 < n && pieceAt(line[j + 1].x, line[j + 1].y) == victim) {
          j++;
        }
        if (terminal(i - 1) && terminal(j + 1)) {
          final anchored = (bIndex >= i && bIndex <= j) ||
              bIndex == i - 1 ||
              bIndex == j + 1;
          if (anchored) {
            for (var k = i; k <= j; k++) {
              final cell = line[k];
              final key = '${cell.x},${cell.y}';
              if (!flips.containsKey(key)) {
                flips[key] = aggressor;
                ordered.add(cell);
              }
            }
          }
        }
        i = j + 1;
      }
    }

    for (final aggressor in order) {
      final victims = pairs[aggressor];
      if (victims == null) continue;
      for (final victim in victims) {
        for (final b in dests) {
          if (horizontal) {
            scanLine(
              [for (var x = 0; x < width; x++) Position(x, b.y)],
              b.x,
              aggressor,
              victim,
            );
          }
          if (vertical) {
            scanLine(
              [for (var y = 0; y < height; y++) Position(b.x, y)],
              b.y,
              aggressor,
              victim,
            );
          }
        }
      }
    }

    if (flips.isEmpty) return const [];

    final events = <GameEvent>[];
    for (final cell in ordered) {
      final key = '${cell.x},${cell.y}';
      final toKind = flips[key]!;
      final fromKind = snapshot[key] ?? '';
      state.board.setEntity(pieceLayerId, cell, EntityInstance(toKind));
      events
          .add(GameEvent.cellTransformed(cell, fromKind, toKind, pieceLayerId));
    }
    return events;
  }
}
