import 'position.dart';

/// Resolves "$ref" strings against event payload + board/avatar state.
/// Called by the effect executor before applying each effect.
dynamic resolveRef(
  dynamic value, {
  required Map<String, dynamic> eventPayload,
  required PositionResolver board,
  required AvatarResolver avatar,
}) {
  if (value is! String || !value.startsWith(r'$')) return value;

  final parts = value.substring(1).split('.');

  if (parts[0] == 'event') {
    // $event.<field>
    if (parts.length < 2) return null;
    final raw = eventPayload[parts[1]];
    // Convert Position to [x, y] list for JSON consumers
    if (raw is Position) return [raw.x, raw.y];
    return raw;
  }

  if (parts[0] == 'cell') {
    // $cell.<layer>.kind  OR  $cell.<layer>.param.<key>
    final pos = eventPayload['position'];
    if (pos == null) return null;
    final position = pos is Position ? pos : Position.fromJson(pos);
    if (parts.length < 3) return null;
    final layerId = parts[1];
    if (parts[2] == 'kind') {
      return board.entityKindAt(layerId, position);
    }
    if (parts[2] == 'param' && parts.length >= 4) {
      return board.entityParamAt(layerId, position, parts[3]);
    }
    return null;
  }

  if (parts[0] == 'avatar') {
    if (parts.length < 2) return null;
    switch (parts[1]) {
      case 'position':
        final p = avatar.position;
        return p != null ? [p.x, p.y] : null;
      case 'item':
        return avatar.item;
    }
    return null;
  }

  return null; // unknown ref
}

abstract class PositionResolver {
  String? entityKindAt(String layerId, Position pos);
  dynamic entityParamAt(String layerId, Position pos, String key);
}

abstract class AvatarResolver {
  Position? get position;
  String? get item;
}
