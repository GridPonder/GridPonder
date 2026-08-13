import 'position.dart';

/// An event emitted by a system or effect during turn execution.
class GameEvent {
  final String type;
  final Map<String, dynamic> payload;

  const GameEvent(this.type, this.payload);

  dynamic operator [](String key) => payload[key];

  Position? get position {
    final p = payload['position'];
    if (p == null) return null;
    if (p is Position) return p;
    return Position.fromJson(p);
  }

  // --- Named constructors ---

  static GameEvent avatarEntered(
          Position pos, Position from, String direction) =>
      GameEvent('avatar_entered', {
        'position': pos,
        'fromPosition': from,
        'direction': direction,
      });

  static GameEvent avatarExited(Position pos) =>
      GameEvent('avatar_exited', {'position': pos});

  static GameEvent moveBlocked(Position target, Position from, String direction,
          String blockerKind) =>
      GameEvent('move_blocked', {
        'position': target,
        'fromPosition': from,
        'direction': direction,
        'blockerKind': blockerKind,
      });

  static GameEvent objectPlaced(Position pos, String kind,
          [Map<String, dynamic> params = const {}]) =>
      GameEvent('object_placed', {
        'position': pos,
        'kind': kind,
        'params': params,
      });

  static GameEvent objectRemoved(Position pos, String kind) =>
      GameEvent('object_removed', {'position': pos, 'kind': kind});

  static GameEvent lineOfSightDetected(Position source, Position target,
          String targetKind, String sourceId, String sourceKind) =>
      GameEvent('line_of_sight_detected', {
        'sourcePosition': source,
        'position': target,
        'kind': targetKind,
        'sourceId': sourceId,
        'sourceKind': sourceKind,
      });

  /// Like [objectRemoved] but signals that [animationName] should play first.
  static GameEvent objectRemovedAnimated(
          Position pos, String kind, String animationName) =>
      GameEvent('object_removed',
          {'position': pos, 'kind': kind, 'animation': animationName});

  static GameEvent cellCleared(Position pos, String previousKind,
          {String layer = 'objects'}) =>
      GameEvent('cell_cleared',
          {'position': pos, 'previousKind': previousKind, 'layer': layer});

  static GameEvent cellTransformed(
          Position pos, String fromKind, String toKind, String layer) =>
      GameEvent('cell_transformed', {
        'position': pos,
        'fromKind': fromKind,
        'toKind': toKind,
        'layer': layer,
      });

  static GameEvent inventoryChanged(String? oldItem, String? newItem) =>
      GameEvent('inventory_changed', {'oldItem': oldItem, 'newItem': newItem});

  static GameEvent objectPushed(
          String kind, Position from, Position to, String direction) =>
      GameEvent('object_pushed', {
        'kind': kind,
        'fromPosition': from,
        'toPosition': to,
        'direction': direction,
      });

  static GameEvent tilesMerged(
          Position pos, int resultValue, List<int> inputValues,
          {List<Position>? sources, String? kind}) =>
      GameEvent('tiles_merged', {
        'position': pos,
        'resultValue': resultValue,
        'inputValues': inputValues,
        if (sources != null) 'sources': sources,
        if (kind != null) 'kind': kind,
      });

  /// A single tile slid from [from] to [to] without merging.
  /// Carries enough information for the renderer to play an `entity_move`
  /// animation; engines that don't render simply ignore it.
  static GameEvent tileMoved(Position from, Position to, String kind,
          {Map<String, dynamic> params = const {}, String layer = 'objects'}) =>
      GameEvent('tile_moved', {
        'fromPosition': from,
        'position': to,
        'kind': kind,
        'params': params,
        'layer': layer,
      });

  static GameEvent tilesSlid(String direction, int movedCount) =>
      GameEvent('tiles_slid', {
        'direction': direction,
        'movedCount': movedCount,
      });

  static GameEvent itemReleased(String emitterId, String kind, Position pos,
          [Map<String, dynamic> params = const {}]) =>
      GameEvent('item_released', {
        'emitterId': emitterId,
        'kind': kind,
        'position': pos,
        'params': params,
      });

  /// [layer] lets a UI animate the travel from [from] to [pos] with the right
  /// sprite. Gravity-style effects that only ever move the `objects` layer keep
  /// the default.
  ///
  /// [fromKind] is what the entity looked like on the way — [kind] is what it
  /// became on arrival, which for a system with a settle transform is not the
  /// same thing. A UI that animates the travel should draw [fromKind], or the
  /// entity appears to transform before it has landed.
  static GameEvent objectSettled(String kind, Position pos, Position from,
          {String layer = 'objects', String? fromKind}) =>
      GameEvent('object_settled', {
        'kind': kind,
        'position': pos,
        'fromPosition': from,
        'layer': layer,
        'fromKind': fromKind ?? kind,
      });

  static GameEvent npcMoved(String npcId, Position from, Position to) =>
      GameEvent('npc_moved', {
        'npcId': npcId,
        'fromPosition': from,
        'toPosition': to,
      });

  // --- Coupled actors (movement + territory claiming) ---

  static GameEvent actorMoved(
          String kind, Position from, Position to, String direction) =>
      GameEvent('actor_moved', {
        'kind': kind,
        'fromPosition': from,
        'position': to,
        'direction': direction,
      });

  static GameEvent actorEntered(
          String kind, Position pos, Position from, String direction) =>
      GameEvent('actor_entered', {
        'kind': kind,
        'fromPosition': from,
        'position': pos,
        'direction': direction,
      });

  /// A reactive (non-player) actor answered the player's move.
  ///
  /// Deliberately distinct from [actorMoved] so move counters and budgets keyed
  /// on player movement are unaffected; systems that should treat a rival
  /// landing as an anchor name this event explicitly.
  static GameEvent actorReacted(
          String kind, Position from, Position to, String direction) =>
      GameEvent('actor_reacted', {
        'kind': kind,
        'fromPosition': from,
        'position': to,
        'direction': direction,
      });

  static GameEvent actorBlocked(String kind, Position pos) =>
      GameEvent('actor_blocked', {'kind': kind, 'position': pos});

  static GameEvent actorSelected(String kind, Position pos) =>
      GameEvent('actor_selected', {'kind': kind, 'position': pos});

  static GameEvent cellClaimed(
          Position pos, String layer, String kind, String ownerKind) =>
      GameEvent('cell_claimed', {
        'position': pos,
        'layer': layer,
        'kind': kind,
        'ownerKind': ownerKind,
      });

  static GameEvent goalStepCompleted(String goalId, int stepIndex) =>
      GameEvent('goal_step_completed', {
        'goalId': goalId,
        'stepIndex': stepIndex,
      });

  static GameEvent variableChanged(
          String name, dynamic oldVal, dynamic newVal) =>
      GameEvent('variable_changed', {
        'variable': name,
        'oldValue': oldVal,
        'newValue': newVal,
      });

  static GameEvent turnEnded(int turnNumber) =>
      GameEvent('turn_ended', {'turnNumber': turnNumber});

  static GameEvent overlayMoved(List<int> pos) =>
      GameEvent('overlay_moved', {'position': pos});

  static GameEvent cellsFlooded(List<Position> cells) =>
      GameEvent('cells_flooded', {'cells': cells});

  /// Signals that a system explicitly rejects the action (turn should not
  /// count as a move). Used by flood_fill when no adjacent target cells exist.
  static GameEvent actionVetoed() => const GameEvent('action_vetoed', {});

  static GameEvent boxesMerged(
          Position pos, int resultSides, int aSides, int bSides) =>
      GameEvent('boxes_merged', {
        'position': pos,
        'resultSides': resultSides,
        'aSides': aSides,
        'bSides': bSides,
      });

  @override
  String toString() => '$type($payload)';
}
