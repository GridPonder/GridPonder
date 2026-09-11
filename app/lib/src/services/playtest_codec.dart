import 'dart:convert';

import 'package:gridponder_engine/engine.dart';

/// Pure encoders for the playtest fields that describe game state: the
/// per-turn board delta (`bd`) and the level revision (`rev`). Kept out of the
/// play screen so they can be tested without a widget tree.

/// Level-file keys that only change what the player reads, not how the level
/// plays. Everything else in the file — board, state, goals, lose conditions,
/// rules, system overrides, solution — is covered by [levelRevision].
const _levelPresentationKeys = {'title', 'guide', 'metadata'};

/// `game.json` keys that only change presentation or the order levels are
/// offered in. Everything else — layers, entity kinds, actions, systems,
/// rules, defaults — is covered by [levelRevision]. Entity kinds carry display
/// data next to their tags; they are kept whole because a tag change alters
/// play, and a spurious revision split is cheaper than mixing two games.
const _gamePresentationKeys = {'ui', 'levelSequence', 'goalDescriptions'};

/// JSON with every map's keys sorted, recursively, so that two structurally
/// equal values always serialize to the same string regardless of the order
/// their maps were built in. [Position]s encode as `[x, y]`.
String canonicalJson(Object? value) => jsonEncode(_canonical(value));

Object? _canonical(Object? value) {
  if (value is Map) {
    final keys = value.keys.map((k) => '$k').toList()..sort();
    return {for (final k in keys) k: _canonical(value[k])};
  }
  if (value is Iterable) return [for (final v in value) _canonical(v)];
  if (value is Position) return [value.x, value.y];
  if (value == null || value is num || value is bool || value is String) {
    return value;
  }
  return '$value';
}

/// 32-bit FNV-1a over the UTF-8 bytes of [input], as 8 hex digits.
///
/// The multiply is split so no intermediate exceeds 2^53: on the web every
/// int is a double, and a plain `hash * 0x01000193` loses bits there, which
/// would give the same level a different revision in web and native builds.
String fnv1a32(String input) {
  var hash = 0x811c9dc5;
  for (final byte in utf8.encode(input)) {
    hash ^= byte;
    // hash * 0x01000193 mod 2^32 == hash * 0x193 + (hash mod 2^8) * 2^24.
    hash = (hash * 0x193 + (hash & 0xff) * 0x1000000) % 0x100000000;
  }
  return hash.toRadixString(16).padLeft(8, '0');
}

/// A short hash of everything in a level that affects how it plays: the level
/// file minus its presentation keys, and the pack's `game.json` minus its
/// presentation keys. Logged with `level_start` so analysis never pools events
/// from two versions of a level whose rules, goals, overrides, gold path or
/// board differ.
String levelRevision(
  Map<String, dynamic> levelJson,
  Map<String, dynamic> gameJson,
) {
  final level = {
    for (final e in levelJson.entries)
      if (!_levelPresentationKeys.contains(e.key)) e.key: e.value,
  };
  final game = {
    for (final e in gameJson.entries)
      if (!_gamePresentationKeys.contains(e.key)) e.key: e.value,
  };
  return fnv1a32(canonicalJson({'level': level, 'game': game}));
}

/// The board's content serialized up front, so a later [boardDelta] compares
/// against what the board held *then*. Taken from the live board before a
/// turn runs rather than from a copy of it: systems edit entity params in
/// place, and a copy that shares those maps would change along with the
/// board and hide exactly the changes [boardDelta] exists to report.
class BoardSnapshot {
  BoardSnapshot.of(Board board)
    : cells = {
        for (final e in board.layers.entries) e.key: _cellTokens(e.value),
      },
      objects = _objectTokens(board.multiCellObjects);

  /// Layer id → `x.y` → canonical JSON of the cell's content.
  final Map<String, Map<String, String>> cells;

  /// Multi-cell object id → canonical JSON of `[kind, cells, params]`.
  final Map<String, String> objects;
}

/// Every piece of board content that changed between [before] and [after],
/// as canonical JSON, or `''` when nothing did:
///
/// ```json
/// {"cells": {"objects": {"2.1": ["box_fragment", {"sides": ["n"]}],
///                        "3.1": "rock",
///                        "4.1": null}},
///  "objects": {"blk": ["elastic_block", ["1.1", "2.1"], {}]}}
/// ```
///
/// `cells` maps layer id → `x.y` → the cell's new content: the bare kind when
/// the entity has no params, `[kind, params]` when it has, `null` when the
/// cell was vacated. A cell appears when its kind *or* any param changed.
/// `objects` maps multi-cell object id → `[kind, cells, params]` (cells in
/// board order), or `null` when the object is gone. Both keys are omitted when
/// they have nothing to report.
String boardDelta(BoardSnapshot before, BoardSnapshot after) {
  final cells = <String, Map<String, Object?>>{};
  final layerIds = {...before.cells.keys, ...after.cells.keys};
  for (final id in layerIds) {
    final changed = _changed(before.cells[id] ?? const {}, after.cells[id] ?? const {});
    if (changed.isNotEmpty) cells[id] = changed;
  }
  final objects = _changed(before.objects, after.objects);
  if (cells.isEmpty && objects.isEmpty) return '';
  return canonicalJson({
    if (cells.isNotEmpty) 'cells': cells,
    if (objects.isNotEmpty) 'objects': objects,
  });
}

Map<String, Object?> _changed(Map<String, String> was, Map<String, String> now) {
  final out = <String, Object?>{};
  for (final key in {...was.keys, ...now.keys}) {
    final a = was[key];
    final b = now[key];
    if (a == b) continue;
    out[key] = b == null ? null : jsonDecode(b);
  }
  return out;
}

/// `x.y` → canonical JSON of the cell's content, for comparison and output.
Map<String, String> _cellTokens(BoardLayer layer) {
  return {
    for (final entry in layer.entries())
      '${entry.key.x}.${entry.key.y}': canonicalJson(
        entry.value.params.isEmpty
            ? entry.value.kind
            : [entry.value.kind, entry.value.params],
      ),
  };
}

Map<String, String> _objectTokens(List<MultiCellObjectInstance> objects) {
  return {
    for (final o in objects)
      o.id: canonicalJson([
        o.kind,
        (o.cells.toList()..sort(
              (a, b) => a.y != b.y ? a.y.compareTo(b.y) : a.x.compareTo(b.x),
            ))
            .map((c) => '${c.x}.${c.y}')
            .toList(),
        o.params,
      ]),
  };
}
