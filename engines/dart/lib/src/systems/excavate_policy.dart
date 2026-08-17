import '../models/board.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/position.dart';

/// A normalised `excavate` config block.
///
/// Single home for the block (`{diggableTag, clearedKind, backfillKind}`) so
/// that any actor system adopting it cannot drift from the others. See
/// docs/dsl/04_systems.md.
///
/// An excavating mover treats terrain tagged [diggableTag] as passable at a
/// price: the target cell is cut down to [clearedKind], the mover takes it,
/// and the cell the mover *left* is backfilled with [backfillKind] — unless
/// another mover ends the turn standing on it, in which case that partner
/// hauls the spoil out and nothing is placed. That last clause is why
/// backfill has to run after every mover has resolved rather than inside the
/// per-mover loop, and it is what makes formation, rather than a chosen
/// target cell, decide what the board looks like afterwards.
class ExcavatePolicy {
  final String diggableTag;
  final String clearedKind;
  final String? backfillKind;

  /// Mover kind → extra ground tags that kind may excavate, on top of
  /// [diggableTag]. This is what makes one cell a wall for one mover and a
  /// doorway for another.
  final Map<String, List<String>> extraDiggableTags;

  const ExcavatePolicy({
    required this.diggableTag,
    required this.clearedKind,
    required this.backfillKind,
    this.extraDiggableTags = const {},
  });

  /// Normalises the `excavate` block. Returns null when excavation is off.
  ///
  /// Tolerance contract (both engines must agree, so it is stated rather than
  /// implied): a non-object `excavate`, or one whose `clearedKind` is missing
  /// or not a non-empty string, is **inert** — the system behaves exactly as
  /// if the block were absent. A missing or non-string `backfillKind` means
  /// *no backfill*, which is a legitimate configuration: a pure tunneller
  /// that removes terrain and leaves an open corridor. A missing or
  /// non-string `diggableTag` falls back to `'diggable'`. `extraDiggableTags`
  /// maps a mover's entity kind to extra ground tags that kind alone may
  /// excavate, on top of `diggableTag`; a missing or non-object
  /// `extraDiggableTags` grants nothing, and any entry whose value is not a
  /// list of non-empty strings is dropped rather than coerced.
  static ExcavatePolicy? read(Map<String, dynamic> config) {
    final raw = config['excavate'];
    if (raw is! Map<String, dynamic>) return null;

    final cleared = raw['clearedKind'];
    if (cleared is! String || cleared.isEmpty) return null;

    final rawBackfill = raw['backfillKind'];
    final backfill =
        (rawBackfill is String && rawBackfill.isNotEmpty) ? rawBackfill : null;

    final rawTag = raw['diggableTag'];
    final tag = (rawTag is String && rawTag.isNotEmpty) ? rawTag : 'diggable';

    return ExcavatePolicy(
      diggableTag: tag,
      clearedKind: cleared,
      backfillKind: backfill,
      extraDiggableTags: _readExtraTags(raw['extraDiggableTags']),
    );
  }

  /// Anything malformed is dropped rather than coerced: a non-object grants
  /// nothing, an entry whose value is not a list of non-empty strings is
  /// ignored for that kind, and an empty list is indistinguishable from an
  /// absent entry. Python's `_read_extra_tags` implements the same contract.
  static Map<String, List<String>> _readExtraTags(Object? raw) {
    if (raw is! Map) return const {};
    final out = <String, List<String>>{};
    raw.forEach((key, value) {
      if (key is! String || key.isEmpty || value is! List) return;
      final clean =
          value.whereType<String>().where((t) => t.isNotEmpty).toList();
      if (clean.isNotEmpty) out[key] = clean;
    });
    return out;
  }
}

/// Whether [pos] is terrain this mover cuts through instead of being blocked
/// by. Callers check the wall tag separately: only a cell that is *both*
/// solid and diggable is excavated, so untagged open ground stays an ordinary
/// move and never triggers a backfill.
///
/// [kind] is the mover's entity kind. Terrain carrying `diggableTag` is
/// diggable by every mover; `extraDiggableTags` grants additional tags to
/// named kinds, which is what makes one cell a wall for one mover and a
/// doorway for another.
bool isDiggable(
  Board board,
  GameDefinition game,
  String layerId,
  Position pos,
  ExcavatePolicy? excavate, [
  String? kind,
]) {
  if (excavate == null) return false;
  if (board.hasTagAt(layerId, pos, excavate.diggableTag, game.entityKinds)) {
    return true;
  }
  final extra = excavate.extraDiggableTags[kind];
  if (extra == null) return false;
  for (final tag in extra) {
    if (board.hasTagAt(layerId, pos, tag, game.entityKinds)) return true;
  }
  return false;
}

GameEvent _transform(
  Board board,
  String layerId,
  Position pos,
  String toKind,
) {
  final current = board.getEntity(layerId, pos);
  board.setEntity(layerId, pos, EntityInstance(toKind));
  // "" rather than null for an empty cell, matching the Python payload.
  return GameEvent.cellTransformed(pos, current?.kind ?? '', toKind, layerId);
}

/// Cuts [pos] down to `clearedKind`. Returns a cellTransformed event.
GameEvent cut(
  Board board,
  String layerId,
  Position pos,
  ExcavatePolicy excavate,
) =>
    _transform(board, layerId, pos, excavate.clearedKind);

/// Fills each pending cell with spoil, skipping any cell a mover ends the turn
/// on — that mover hauled the spoil out, and a `spoil_hauled` event is emitted
/// in place of the `cell_transformed` that would have fired.
///
/// [pending] is iterated in the order cells were vacated so the event stream
/// is deterministic; [occupied] must be the *final* actor positions for the
/// turn, which is exactly what the caller's live occupancy set holds once its
/// loop has finished.
List<GameEvent> backfill(
  Board board,
  String layerId,
  List<Position> pending,
  Set<Position> occupied,
  ExcavatePolicy? excavate,
) {
  final backfillKind = excavate?.backfillKind;
  if (backfillKind == null) return const [];
  final events = <GameEvent>[];
  for (final pos in pending) {
    if (occupied.contains(pos)) {
      events.add(GameEvent.spoilHauled(pos, layerId));
      continue;
    }
    events.add(_transform(board, layerId, pos, backfillKind));
  }
  return events;
}
