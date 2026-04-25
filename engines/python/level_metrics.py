"""
Level-derived metrics used by analytics tools (benchmarks, charts, etc).

Centralised so that future schema changes (e.g. new ground-cell tokens
that should not count toward grid size) only need to be reflected once.
"""
from __future__ import annotations


def playable_cell_count(level_def: dict) -> int:
    """Number of grid cells that aren't 'void' tiles.

    The board ground layer comes in two formats:
    - Dense: a 2-D array of cell tokens (most packs).
    - Sparse: ``{format: 'sparse', entries: [{position, kind}]}`` listing
      only cells that differ from the implicit empty default (twinseed).

    Returns 0 if the board has no size declared.
    """
    board = level_def.get("board", {})
    size = board.get("size") or [0, 0]
    total = size[0] * size[1] if isinstance(size, list) and len(size) >= 2 else 0

    ground = board.get("layers", {}).get("ground")
    if isinstance(ground, list):
        void = sum(1 for row in ground for c in row if c == "void")
    elif isinstance(ground, dict) and ground.get("format") == "sparse":
        # Sparse format has an implicit non-void default; only entries can be void.
        void = sum(1 for e in ground.get("entries", []) if e.get("kind") == "void")
    else:
        void = 0

    return total - void
