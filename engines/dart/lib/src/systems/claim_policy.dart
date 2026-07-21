import '../models/board.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/position.dart';

bool _isOverwritable(
  Board board,
  GameDefinition game,
  Position pos,
  Map<String, dynamic> claim,
  String groundLayerId,
) {
  final overwrite = claim['overwrite'] as Map<String, dynamic>? ?? const {};
  final mode = overwrite['mode'] as String? ?? 'never';
  if (mode == 'always') return true;
  if (mode == 'tagged') {
    final tag = overwrite['tag'] as String?;
    if (tag == null || tag.isEmpty) return false;
    final layerId = overwrite['layer'] as String? ?? groundLayerId;
    return board.hasTagAt(layerId, pos, tag, game.entityKinds);
  }
  return false;
}

/// Claims [target] for [actorKind]. Returns a cellClaimed event, or null when
/// nothing changed.
///
/// Single home for the `claim` block (`{layer, map, overwrite}`) so that
/// `coupled_actors` and `individual_actors` cannot drift apart. See
/// docs/dsl/04_systems.md.
///
/// - empty cell                         -> claimed
/// - owned by another, overwritable     -> repainted
/// - owned by another, not overwritable -> untouched (a transit)
/// - already owned by this kind         -> untouched, no event
GameEvent? applyClaim(
  Board board,
  GameDefinition game,
  Map<String, dynamic>? claim,
  String groundLayerId,
  Position target,
  String actorKind,
) {
  if (claim == null) return null;
  final claimMap = claim['map'] as Map<String, dynamic>? ?? const {};
  final claimKind = claimMap[actorKind] as String?;
  if (claimKind == null) return null;

  final claimLayerId = claim['layer'] as String;
  final current = board.getEntity(claimLayerId, target);
  if (current != null) {
    if (current.kind == claimKind) return null;
    if (!_isOverwritable(board, game, target, claim, groundLayerId))
      return null;
  }

  board.setEntity(claimLayerId, target, EntityInstance(claimKind));
  return GameEvent.cellClaimed(target, claimLayerId, claimKind, actorKind);
}
