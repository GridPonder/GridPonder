"""Shared runtime-variable reading for systems that keep a counter (a tape
index, an edit budget) in ``state.variables``. Single home so `coupled_actors`
and `terrain_edit` cannot drift on how a malformed value is tolerated.
"""
from __future__ import annotations

import math

from .._models import GameState


def read_int_variable(state: GameState, name: str | None, default: int = 0) -> int:
    """Read ``name`` from ``state.variables`` as an int, defaulting when the
    variable is absent, not a plain number, or a non-finite float.

    Only ``int`` and finite ``float`` are accepted. ``bool`` (a Python ``int``
    subclass) and numeric strings fall back to ``default`` too, so a stray
    boolean or string written into a level's ``variables`` is tolerated
    identically to the Dart engine's ``num?`` cast, rather than silently
    coercing the way bare ``int(...)`` would.
    """
    if name is None:
        return default
    value = state.variables.get(name, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) else default
    return default
