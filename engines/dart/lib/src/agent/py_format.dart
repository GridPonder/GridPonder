/// Formatting helpers that reproduce Python's text output byte for byte.
///
/// The benchmark has two prompt builders — the Python reference
/// (engines/python, tools/benchmark/runner.py) and this Dart port — and their
/// prompts must be identical. Python prints actions with
/// `json.dumps(a, sort_keys=True)` and entity parameters with `str(value)`;
/// these helpers produce the same strings from Dart values.
library;

/// Equivalent of Python `json.dumps(value, sort_keys=True)` with the default
/// separators (`', '` and `': '`) and `ensure_ascii=True`.
///
/// With [compact], uses `separators=(",", ":")` instead.
String pyJsonDumps(Object? value, {bool compact = false}) {
  final sb = StringBuffer();
  _writeJson(sb, value, compact ? ',' : ', ', compact ? ':' : ': ');
  return sb.toString();
}

void _writeJson(StringBuffer sb, Object? value, String itemSep, String keySep) {
  if (value == null) {
    sb.write('null');
  } else if (value is bool) {
    sb.write(value ? 'true' : 'false');
  } else if (value is int) {
    sb.write(value);
  } else if (value is double) {
    sb.write(_pyFloat(value));
  } else if (value is String) {
    _writeJsonString(sb, value);
  } else if (value is Map) {
    final keys = value.keys.map((k) => k.toString()).toList()..sort();
    sb.write('{');
    for (int i = 0; i < keys.length; i++) {
      if (i > 0) sb.write(itemSep);
      _writeJsonString(sb, keys[i]);
      sb.write(keySep);
      _writeJson(sb, value[keys[i]], itemSep, keySep);
    }
    sb.write('}');
  } else if (value is Iterable) {
    sb.write('[');
    var first = true;
    for (final item in value) {
      if (!first) sb.write(itemSep);
      first = false;
      _writeJson(sb, item, itemSep, keySep);
    }
    sb.write(']');
  } else {
    _writeJsonString(sb, value.toString());
  }
}

void _writeJsonString(StringBuffer sb, String s) {
  sb.write('"');
  for (final c in s.codeUnits) {
    switch (c) {
      case 0x22:
        sb.write(r'\"');
      case 0x5C:
        sb.write(r'\\');
      case 0x0A:
        sb.write(r'\n');
      case 0x0D:
        sb.write(r'\r');
      case 0x09:
        sb.write(r'\t');
      case 0x08:
        sb.write(r'\b');
      case 0x0C:
        sb.write(r'\f');
      default:
        if (c < 0x20 || c > 0x7E) {
          sb.write(r'\u');
          sb.write(c.toRadixString(16).padLeft(4, '0'));
        } else {
          sb.writeCharCode(c);
        }
    }
  }
  sb.write('"');
}

/// Equivalent of Python `str(value)` for JSON-shaped values.
String pyStr(Object? value) => value is String ? value : pyRepr(value);

/// Equivalent of Python `repr(value)` for JSON-shaped values.
String pyRepr(Object? value) {
  if (value == null) return 'None';
  if (value is bool) return value ? 'True' : 'False';
  if (value is int) return '$value';
  if (value is double) return _pyFloat(value);
  if (value is String) return _pyStringRepr(value);
  if (value is Map) {
    return '{${value.entries.map((e) => '${pyRepr(e.key)}: ${pyRepr(e.value)}').join(', ')}}';
  }
  if (value is Iterable) return '[${value.map(pyRepr).join(', ')}]';
  return value.toString();
}

String _pyStringRepr(String s) {
  final quote = (s.contains("'") && !s.contains('"')) ? '"' : "'";
  final sb = StringBuffer(quote);
  for (final rune in s.runes) {
    if (rune == 0x5C) {
      sb.write(r'\\');
    } else if (rune == quote.codeUnitAt(0)) {
      sb.write('\\$quote');
    } else if (rune == 0x0A) {
      sb.write(r'\n');
    } else if (rune == 0x0D) {
      sb.write(r'\r');
    } else if (rune == 0x09) {
      sb.write(r'\t');
    } else if (rune < 0x20 || rune == 0x7F) {
      sb.write('\\x${rune.toRadixString(16).padLeft(2, '0')}');
    } else {
      sb.writeCharCode(rune);
    }
  }
  sb.write(quote);
  return sb.toString();
}

/// Python float repr for the common cases (integral values keep a `.0`).
String _pyFloat(double v) {
  if (v.isNaN) return 'NaN';
  if (v.isInfinite) return v > 0 ? 'Infinity' : '-Infinity';
  if (v == v.truncateToDouble() && v.abs() < 1e16) {
    return '${v.toInt()}.0';
  }
  return v.toString();
}
