import '../engine/game_system.dart';
import '../models/entity.dart';
import '../models/event.dart';
import '../models/game_definition.dart';
import '../models/game_state.dart';
import '../models/position.dart';

/// A settle pass can only repeat because a body fell, and a fall strictly
/// removes weight, so the loop terminates after (bodies + 1) passes. The cap is
/// a guard against a malformed level, not part of the semantics.
const int _maxSettlePasses = 4;

/// BalanceRegionsSystem — see docs/dsl/04_systems.md.
///
/// Terrain driven by where bodies stand. Each group owns two *pans* — floor
/// regions identified by ground tags. Every body on a pan contributes its
/// weight; the heavier pan is down and equal weight is level. The attitude is
/// written to `stateVariable` as -1 (first pan down), 0 (level) or +1 (second
/// pan down).
///
/// *Leaves* are cells carrying an inert marker entity. The ground under a
/// marker is set to `solidKind` while the attitude is one of the leaf's
/// `solidWhen` values and to `openKind` (default `void`) otherwise, so
/// passability flows through the existing tag machinery: the avatar is stopped
/// by ground without its navigation tag, and NPCs are stopped by `void`. A body
/// on a leaf that opens falls: actors are removed, and the avatar increments
/// `fallVariable` so an ordinary `variable_threshold` lose condition fires the
/// same turn.
///
/// Leaves are found through their markers rather than by scanning the ground
/// for leaf kinds, because an open leaf *is* `void` — indistinguishable from
/// every wall in the level — and could never be found again.
///
/// Phase: `npc_resolution` — declare it after the NPC system. It also runs once
/// at level load so an authored board cannot contradict its own attitude.
///
/// Tolerance contract (both engines must agree): a missing or non-map `groups`
/// makes the system inert. A group whose `pans` is not a list of exactly two
/// entries is skipped. Non-integer weights are ignored, as is a marker naming
/// no leaf spec. Ground under a marker that is neither `solidKind` nor
/// `openKind` is left untouched. Objects on a falling leaf do not fall; only
/// `weightLayers` entities and the avatar do.
class BalanceRegionsSystem extends GameSystem {
  const BalanceRegionsSystem({required super.id})
      : super(type: 'balance_regions');

  @override
  List<GameEvent> executeNpcResolution(LevelState state, GameDefinition game) =>
      _settleAll(state, game);

  @override
  List<GameEvent> executeLoadSettle(LevelState state, GameDefinition game) =>
      _settleAll(state, game);

  List<Map<String, dynamic>> _groups(GameDefinition game) {
    final config = game.systemConfig(id, {});
    final groups = config['groups'];
    if (groups is! Map) return const [];
    final names = groups.keys.map((k) => k.toString()).toList()..sort();
    return [
      for (final name in names)
        if (groups[name] is Map<String, dynamic>)
          groups[name] as Map<String, dynamic>
    ];
  }

  List<GameEvent> _settleAll(LevelState state, GameDefinition game) {
    final events = <GameEvent>[];
    for (final group in _groups(game)) {
      events.addAll(_settleGroup(group, state, game));
    }
    return events;
  }

  List<GameEvent> _settleGroup(
      Map<String, dynamic> group, LevelState state, GameDefinition game) {
    final pans = group['pans'];
    if (pans is! List || pans.length != 2) return const [];
    final events = <GameEvent>[];
    for (var pass = 0; pass < _maxSettlePasses; pass++) {
      final attitude = _attitude(group, pans, state, game);
      final variable = group['stateVariable'];
      if (variable is String && variable.isNotEmpty) {
        state.variables[variable] = attitude.value;
      }
      if (!_applyLeaves(group, attitude.name, state, game, events)) break;
    }
    return events;
  }

  int? _panIndex(Map<String, dynamic> group, List pans, Position pos,
      LevelState state, GameDefinition game) {
    final groundLayer = (group['groundLayer'] as String?) ?? 'ground';
    final ground = state.board.getEntity(groundLayer, pos);
    if (ground == null) return null;
    for (var index = 0; index < pans.length; index++) {
      final pan = pans[index];
      if (pan is! Map) continue;
      final tags = pan['groundTags'];
      if (tags is! List) continue;
      for (final tag in tags) {
        if (game.hasTag(ground.kind, tag.toString())) return index;
      }
    }
    return null;
  }

  _Attitude _attitude(Map<String, dynamic> group, List pans, LevelState state,
      GameDefinition game) {
    final rawWeights = group['weights'];
    final weights = rawWeights is Map ? rawWeights : const {};
    final rawLayers = group['weightLayers'];
    final layers = rawLayers is List ? rawLayers : const ['actors'];
    final totals = [0, 0];

    for (final layerId in layers) {
      final layer = state.board.layers[layerId.toString()];
      if (layer == null) continue;
      for (final entry in layer.entries()) {
        final weight = weights[entry.value.kind];
        if (weight is! int || weight == 0) continue;
        final index = _panIndex(group, pans, entry.key, state, game);
        if (index != null) totals[index] += weight;
      }
    }

    final avatarWeight = group['avatarWeight'] ?? 1;
    final avatarPos = state.avatar.position;
    if (avatarWeight is int &&
        avatarWeight != 0 &&
        state.avatar.enabled &&
        avatarPos != null) {
      final index = _panIndex(group, pans, avatarPos, state, game);
      if (index != null) totals[index] += avatarWeight;
    }

    String nameOf(int i, String fallback) {
      final pan = pans[i];
      return (pan is Map && pan['name'] is String)
          ? pan['name'] as String
          : fallback;
    }

    if (totals[0] > totals[1]) return _Attitude(-1, nameOf(0, 'first'));
    if (totals[1] > totals[0]) return _Attitude(1, nameOf(1, 'second'));
    return const _Attitude(0, 'level');
  }

  Map<String, dynamic>? _leafSpec(List leaves, String markerKind) {
    for (final spec in leaves) {
      if (spec is Map<String, dynamic> && spec['marker'] == markerKind) {
        return spec;
      }
    }
    return null;
  }

  bool _applyLeaves(Map<String, dynamic> group, String attitudeName,
      LevelState state, GameDefinition game, List<GameEvent> events) {
    final leaves = group['leaves'];
    if (leaves is! List || leaves.isEmpty) return false;
    final markerLayer = (group['markerLayer'] as String?) ?? 'objects';
    final groundLayer = (group['groundLayer'] as String?) ?? 'ground';
    final layer = state.board.layers[markerLayer];
    if (layer == null) return false;

    var changed = false;
    for (final entry in layer.entries().toList()) {
      final spec = _leafSpec(leaves, entry.value.kind);
      if (spec == null) continue;
      final solidKind = spec['solidKind'];
      final openKind = spec['openKind'] ?? 'void';
      if (solidKind is! String || openKind is! String) continue;
      final solidWhen = spec['solidWhen'];
      final solid = solidWhen is List &&
          solidWhen.any((a) => a.toString() == attitudeName);
      final wanted = solid ? solidKind : openKind;

      final ground = state.board.getEntity(groundLayer, entry.key);
      final current = ground?.kind;
      if (current == wanted) continue;
      if (current != solidKind && current != openKind) continue;

      state.board.setEntity(
          groundLayer,
          entry.key,
          EntityInstance(
              wanted, Map<String, dynamic>.from(ground?.params ?? const {})));
      events.add(GameEvent.cellTransformed(
          entry.key, current ?? '', wanted, groundLayer));
      changed = true;
      if (wanted == openKind) {
        events.addAll(_dropBodies(group, entry.key, state));
      }
    }
    return changed;
  }

  List<GameEvent> _dropBodies(
      Map<String, dynamic> group, Position pos, LevelState state) {
    final out = <GameEvent>[];
    final rawLayers = group['weightLayers'];
    final layers = rawLayers is List ? rawLayers : const ['actors'];
    for (final layerId in layers) {
      final id = layerId.toString();
      final entity = state.board.getEntity(id, pos);
      if (entity == null) continue;
      state.board.setEntity(id, pos, null);
      out.add(GameEvent.entityFell(pos, entity.kind, id));
    }
    if (state.avatar.enabled && state.avatar.position == pos) {
      final variable = (group['fallVariable'] as String?) ?? 'fell';
      final current = state.variables[variable];
      state.variables[variable] = (current is int ? current : 0) + 1;
      out.add(GameEvent.entityFell(pos, 'avatar', 'avatar'));
    }
    return out;
  }
}

class _Attitude {
  final int value;
  final String name;
  const _Attitude(this.value, this.name);
}
