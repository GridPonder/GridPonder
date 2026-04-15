import 'position.dart';
import 'direction.dart';

class InventoryState {
  final String? slot;

  const InventoryState({this.slot});

  factory InventoryState.fromJson(Map<String, dynamic> j) =>
      InventoryState(slot: j['slot'] as String?);

  Map<String, dynamic> toJson() => {'slot': slot};

  InventoryState copyWith({Object? slot = _sentinel}) {
    if (slot == _sentinel) return InventoryState(slot: this.slot);
    return InventoryState(slot: slot as String?);
  }

  static const _sentinel = Object();
}

/// Runtime avatar state.
class AvatarState {
  final bool enabled;
  final Position? position;
  final Direction facing;
  final InventoryState inventory;

  const AvatarState({
    required this.enabled,
    this.position,
    this.facing = Direction.right,
    this.inventory = const InventoryState(),
  });

  factory AvatarState.fromJson(Map<String, dynamic> j) {
    final enabled = (j['enabled'] as bool?) ?? true;
    return AvatarState(
      enabled: enabled,
      position: j['position'] != null
          ? Position.fromJson(j['position'])
          : null,
      facing: j['facing'] != null
          ? Direction.fromJson(j['facing'] as String)
          : Direction.right,
      inventory: j['inventory'] != null
          ? InventoryState.fromJson(j['inventory'] as Map<String, dynamic>)
          : const InventoryState(),
    );
  }

  AvatarState copyWith({
    bool? enabled,
    Object? position = _sentinel,
    Direction? facing,
    InventoryState? inventory,
  }) =>
      AvatarState(
        enabled: enabled ?? this.enabled,
        position:
            position == _sentinel ? this.position : position as Position?,
        facing: facing ?? this.facing,
        inventory: inventory ?? this.inventory,
      );

  static const _sentinel = Object();
}
