"""Shared excavation for the actor systems.

Single home for the `excavate` config block (`{diggableTag, clearedKind,
backfillKind}`) so that any actor system adopting it cannot drift from the
others. See docs/dsl/04_systems.md.

An excavating mover treats terrain tagged `diggableTag` as passable at a
price: the target cell is cut down to `clearedKind`, the mover takes it, and
the cell the mover *left* is backfilled with `backfillKind` — unless another
mover ends the turn standing on it, in which case that partner hauls the spoil
out and nothing is placed. That last clause is why backfill has to run after
every mover has resolved rather than inside the per-mover loop, and it is what
makes formation, rather than a chosen target cell, decide what the board looks
like afterwards.

Tolerance contract (both engines must agree, so it is stated rather than
implied): a non-object `excavate`, or one whose `clearedKind` is missing or
not a non-empty string, is **inert** — the system behaves exactly as if the
block were absent. A missing or non-string `backfillKind` means *no backfill*,
which is a legitimate configuration: a pure tunneller that removes terrain and
leaves an open corridor. A missing or non-string `diggableTag` falls back to
`"diggable"`. `extraDiggableTags` maps a mover's entity kind to extra ground
tags that kind alone may excavate, on top of `diggableTag`; a missing or
non-object `extraDiggableTags` grants nothing, and any entry whose value is
not a list of non-empty strings is dropped rather than coerced.
"""
from __future__ import annotations

from .._models import Entity
from .. import _events as ev


def read_excavate(config: dict) -> dict | None:
    """Normalise the `excavate` block. Returns None when excavation is off."""
    raw = config.get("excavate")
    if not isinstance(raw, dict):
        return None

    cleared = raw.get("clearedKind")
    if not isinstance(cleared, str) or not cleared:
        return None

    backfill = raw.get("backfillKind")
    if not isinstance(backfill, str) or not backfill:
        backfill = None

    tag = raw.get("diggableTag")
    if not isinstance(tag, str) or not tag:
        tag = "diggable"

    return {
        "diggableTag": tag,
        "clearedKind": cleared,
        "backfillKind": backfill,
        "extraDiggableTags": _read_extra_tags(raw.get("extraDiggableTags")),
    }


def _read_extra_tags(raw) -> dict[str, tuple[str, ...]]:
    """Mover kind → extra ground tags that kind may excavate, on top of
    `diggableTag`. Anything malformed is dropped rather than coerced: a
    non-object grants nothing, an entry whose value is not a list of non-empty
    strings is ignored for that kind, and an empty list is indistinguishable
    from an absent entry."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for kind, tags in raw.items():
        if not isinstance(kind, str) or not kind or not isinstance(tags, list):
            continue
        clean = tuple(t for t in tags if isinstance(t, str) and t)
        if clean:
            out[kind] = clean
    return out


def is_diggable(board, game, layer_id, pos, excavate, kind: str | None = None) -> bool:
    """Whether `pos` is terrain this mover cuts through instead of being
    blocked by. Callers check the wall tag separately: only a cell that is
    *both* solid and diggable is excavated, so untagged open ground is an
    ordinary move and never triggers a backfill.

    `kind` is the mover's entity kind. Terrain carrying `diggableTag` is
    diggable by every mover; `extraDiggableTags` grants additional tags to
    named kinds, which is what makes one cell a wall for one mover and a
    doorway for another.
    """
    if excavate is None:
        return False
    if board.has_tag_at(layer_id, pos, excavate["diggableTag"], game.entity_kinds):
        return True
    for tag in excavate["extraDiggableTags"].get(kind or "", ()):
        if board.has_tag_at(layer_id, pos, tag, game.entity_kinds):
            return True
    return False


def _transform(board, layer_id, pos, to_kind: str) -> dict:
    current = board.get_entity(layer_id, pos)
    # "" rather than None for an empty cell, so the payload type matches
    # Dart's non-nullable `fromKind` and the two engines stay comparable.
    previous = current.kind if current is not None else ""
    board.set_entity(layer_id, pos, Entity(to_kind))
    return ev.cell_transformed(pos, previous, to_kind, layer_id)


def cut(board, layer_id, pos, excavate) -> dict:
    """Cut `pos` down to `clearedKind`. Returns a cell_transformed event."""
    return _transform(board, layer_id, pos, excavate["clearedKind"])


def backfill(board, layer_id, pending, occupied, excavate) -> list[dict]:
    """Fill each pending cell with spoil, skipping any cell a mover ends the
    turn on — that mover hauled the spoil out, and a `spoil_hauled` event is
    emitted in place of the `cell_transformed` that would have fired.

    `pending` is iterated in the order cells were vacated so the event stream
    is deterministic; `occupied` must be the *final* actor positions for the
    turn, which is exactly what the caller's live occupancy set holds once its
    loop has finished.
    """
    if excavate is None or excavate["backfillKind"] is None:
        return []
    events = []
    for pos in pending:
        if pos in occupied:
            events.append(ev.spoil_hauled(pos, layer_id))
            continue
        events.append(_transform(board, layer_id, pos, excavate["backfillKind"]))
    return events
