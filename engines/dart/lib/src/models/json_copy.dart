/// Deep copies of the JSON-shaped values that models keep in mutable maps
/// (entity params, state variables). Maps, lists and sets are copied all the
/// way down; everything else is an immutable scalar and is shared.
library;

Map<String, dynamic> deepCopyMap(Map<String, dynamic> source) {
  return source.map((key, value) => MapEntry(key, deepCopyValue(value)));
}

dynamic deepCopyValue(dynamic value) {
  if (value is Map) {
    return value.map((k, v) => MapEntry(k, deepCopyValue(v)));
  }
  if (value is List) {
    return value.map(deepCopyValue).toList();
  }
  if (value is Set) {
    return value.map(deepCopyValue).toSet();
  }
  return value;
}
