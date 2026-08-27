// The orthogonal sightline relation, shared by `line_of_sight` and
// `follower_npcs` so the two cannot disagree about the same pair of cells.
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

bool coveredByOtherMultiCellObject(
  Position target,
  String? sourceMultiCellObjectId,
  LevelState state,
) {
  for (final object in state.board.multiCellObjects) {
    if (object.id != sourceMultiCellObjectId &&
        object.cells.contains(target)) {
      return true;
    }
  }
  return false;
}

bool hasClearLine(
  Position source,
  Position target,
  String? sourceMultiCellObjectId,
  LevelState state,
  GameDefinition game,
  List<String> blockingLayers,
  List<String> blockingTags,
  bool multiCellObjectsBlock,
) {
  if (source == target) return false;
  if (source.x != target.x && source.y != target.y) return false;

  final dx = source.x == target.x ? 0 : (target.x > source.x ? 1 : -1);
  final dy = source.y == target.y ? 0 : (target.y > source.y ? 1 : -1);
  var position = Position(source.x + dx, source.y + dy);
  while (position != target) {
    if (state.board.isVoid(position)) return false;
    if (multiCellObjectsBlock &&
        coveredByOtherMultiCellObject(
          position,
          sourceMultiCellObjectId,
          state,
        )) {
      return false;
    }
    for (final layerId in blockingLayers) {
      final entity = state.board.getEntity(layerId, position);
      if (entity == null) continue;
      if (blockingTags.isEmpty ||
          blockingTags.any((tag) => game.hasTag(entity.kind, tag))) {
        return false;
      }
    }
    position = Position(position.x + dx, position.y + dy);
  }
  return true;
}
