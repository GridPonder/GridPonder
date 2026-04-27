"""Engine parity guard.

Catches drift between the Dart and Python engines at the structural level:
1. Every system file in engines/dart/lib/src/systems/ must have a matching
   submodule in engines/python/_systems/ (and vice versa).
2. Both engines' system registries must register the same set of system
   `type` strings.

This complements test_gold_paths.py — gold paths catch *behavioural* drift
(a system that diverges in semantics will fail to replay), while parity
catches *catalog* drift (a system that exists in only one engine).

Run from the repo root:  python engines/python/test_engine_parity.py
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

DART_SYS_DIR = ROOT / "engines" / "dart" / "lib" / "src" / "systems"
PY_SYS_DIR = ROOT / "engines" / "python" / "_systems"


def dart_system_files() -> set[str]:
    """Files matching <name>_system.dart → returns {<name>, ...}."""
    out = set()
    for f in DART_SYS_DIR.glob("*_system.dart"):
        # Skip system_registry.dart — it's the catalog, not a system.
        if f.stem == "system_registry":
            continue
        out.add(f.stem.removesuffix("_system"))
    return out


def python_system_files() -> set[str]:
    """Files in _systems/ excluding the package machinery."""
    out = set()
    for f in PY_SYS_DIR.glob("*.py"):
        name = f.stem
        if name.startswith("_"):  # __init__, _base
            continue
        out.add(name)
    return out


def dart_registry_types() -> set[str]:
    """Parses system_registry.dart for the map-literal keys
       `'<type>': (id, _) => …`."""
    src = (DART_SYS_DIR / "system_registry.dart").read_text()
    return set(re.findall(r"'([a-z_]+)'\s*:\s*\(", src))


def python_registry_types() -> set[str]:
    from engines.python._systems import _REGISTRY
    return set(_REGISTRY.keys())


def main() -> int:
    failed = []

    dart_files = dart_system_files()
    py_files = python_system_files()
    if dart_files != py_files:
        only_dart = dart_files - py_files
        only_py = py_files - dart_files
        if only_dart:
            failed.append(f"  Dart-only system files: {sorted(only_dart)}")
        if only_py:
            failed.append(f"  Python-only system files: {sorted(only_py)}")

    dart_types = dart_registry_types()
    py_types = python_registry_types()
    if dart_types != py_types:
        only_dart = dart_types - py_types
        only_py = py_types - dart_types
        if only_dart:
            failed.append(f"  Dart registry knows: {sorted(only_dart)} (Python doesn't)")
        if only_py:
            failed.append(f"  Python registry knows: {sorted(only_py)} (Dart doesn't)")

    if failed:
        print("Engine parity: FAIL")
        for line in failed:
            print(line)
        return 1

    print(f"Engine parity: OK  ({len(dart_files)} systems, "
          f"{len(dart_types)} registry types)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
