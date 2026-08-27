"""SonarSystem — see docs/dsl/04_systems.md.

Writes a distance reading per source entity kind into ``state.variables`` every
turn: for each source, the distance to its paired (or nearest) target entity.
The system is **read-only with respect to the board** — it mutates variables
and nothing else, and emits no events.

This is the generic hook for "warmer/colder" sensing: a game can hide the
target layer from the player and let them locate it by moving and reading, or
use the reading as a proximity alarm, a heat-seeker, or a scoring input.

Phase: ``npc_resolution``. That is the last phase running unconditionally for
every system on every turn, after action, movement and cascade resolution have
all settled the board, and before goal evaluation. A reading therefore always
describes the board the player is looking at when the turn ends.

Because readings live in ``state.variables`` they are inside ``to_key()``, so
undo, ``previewTurn`` and solver dedup work with no extra handling. They are a
pure function of board state, so they add no new state distinctions and cannot
inflate a solver's search space.

Tolerance contract (both engines must agree, so it is stated rather than
implied): a missing or non-string ``targetLayer`` makes the system **inert** —
it writes nothing at all. A non-object ``pairing`` is treated as absent, which
selects nearest-target-of-any-kind mode. A ``metric`` other than
``"manhattan"`` falls back to ``"manhattan"`` rather than raising. A
non-string ``variablePrefix`` falls back to ``"echo_"``. When a source kind
has no reachable target (no target entities, or none paired to it) its
variable is set to ``-1`` rather than being left unwritten, so a level can
never read a stale value from a previous turn.

Two source entities sharing a kind both write the same variable; the value is
the **minimum** over them, so the reading is deterministic regardless of
iteration order.

An ``aggregate`` of ``"sum"``, ``"min"`` or ``"max"`` makes the system write a
single combined reading to ``aggregateVariable`` (default
``variablePrefix + "total"``) instead of one variable per source kind; any
other value, or none, selects per-kind mode. A non-string
``aggregateVariable`` falls back to the default. Under ``sum`` a single source
without a target makes the whole reading ``-1``, because a partial sum is
numerically indistinguishable from a real one; ``min`` and ``max`` instead skip
target-less sources and return ``-1`` only when no source has a target. An
empty source layer reads ``-1``; a *missing* source layer leaves the system
inert, exactly as today.

One number reducing N sources is one equation in N unknowns, and under
lockstep movement consecutive readings are redundant — so a pack using an
aggregate for deduction must supply asymmetry through terrain that stops some
sources and not others. A gauge over sources that always move together yields
no information at all.
"""
from __future__ import annotations

from .._models import GameState
from .._game_def import GameDef
from ._base import GameSystem


def _read_config(config: dict) -> dict | None:
    """Normalise the sonar config. Returns None when the system is inert."""
    target_layer = config.get("targetLayer")
    if not isinstance(target_layer, str) or not target_layer:
        return None

    source_layer = config.get("sourceLayer")
    if not isinstance(source_layer, str) or not source_layer:
        source_layer = "actors"

    pairing = config.get("pairing")
    if not isinstance(pairing, dict):
        pairing = None

    prefix = config.get("variablePrefix")
    if not isinstance(prefix, str):
        prefix = "echo_"

    # `metric` is reserved for future distance functions; anything we do not
    # recognise falls back to manhattan rather than raising, so a typo cannot
    # make one engine throw while the other silently continues.
    # An unrecognised reduction degrades to per-kind mode rather than raising,
    # for the same reason `metric` does: a typo must not make one engine throw
    # while the other silently continues.
    aggregate = config.get("aggregate")
    if aggregate not in ("sum", "min", "max"):
        aggregate = None

    aggregate_variable = config.get("aggregateVariable")
    if not isinstance(aggregate_variable, str) or not aggregate_variable:
        aggregate_variable = prefix + "total"

    return {
        "sourceLayer": source_layer,
        "targetLayer": target_layer,
        "pairing": pairing,
        "variablePrefix": prefix,
        "aggregate": aggregate,
        "aggregateVariable": aggregate_variable,
    }


def _reduce(mode: str, distances: list[int]) -> int:
    """Combine per-source distances into one crew reading.

    The asymmetry between ``sum`` and ``min``/``max`` is deliberate. A partial
    sum is numerically indistinguishable from a real reading, so a missing
    target poisons the whole value and must yield -1. A min or max over the
    sources that *do* have targets is a well-defined answer to the question
    that reduction asks, so those skip the target-less sources instead.
    """
    if not distances:
        return -1
    if mode == "sum":
        if any(d < 0 for d in distances):
            return -1
        return sum(distances)
    found = [d for d in distances if d >= 0]
    if not found:
        return -1
    return min(found) if mode == "min" else max(found)


class SonarSystem(GameSystem):
    def __init__(self, sys_id: str):
        super().__init__(sys_id, "sonar")

    def execute_npc_resolution(self, state: GameState, game: GameDef) -> list[dict]:
        config = game.system_config(self.id)
        cfg = _read_config(config)
        if cfg is None:
            return []

        board = state.board
        source_layer = board.layers.get(cfg["sourceLayer"])
        target_layer = board.layers.get(cfg["targetLayer"])
        if source_layer is None:
            return []

        targets = list(target_layer.entries()) if target_layer is not None else []
        pairing = cfg["pairing"]
        prefix = cfg["variablePrefix"]

        aggregate = cfg["aggregate"]
        distances: list[int] = []
        readings: dict[str, int] = {}
        for pos, entity in source_layer.entries():
            # A source kind absent from a *present* pairing map is not sensed
            # by this instance at all — it is skipped rather than falling
            # through to nearest-of-any. Without this, two sonar instances
            # sharing a source layer contaminate each other: the second would
            # sense the first's sources against whatever target happened to be
            # closest. Pairing omitted entirely still means nearest-of-any.
            if pairing is not None and entity.kind not in pairing:
                continue
            wanted = pairing.get(entity.kind) if pairing is not None else None
            best = -1
            for tpos, tentity in targets:
                if wanted is not None and tentity.kind != wanted:
                    continue
                dist = abs(pos.x - tpos.x) + abs(pos.y - tpos.y)
                if best < 0 or dist < best:
                    best = dist

            if aggregate is not None:
                # In aggregate mode the per-source distance is an input to the
                # reduction and is never published on its own — a pack wanting
                # both surfaces declares two sonar instances.
                distances.append(best)
                continue

            # Two sources of the same kind collapse to the minimum, so the
            # written value does not depend on iteration order. -1 (no target)
            # loses to any real distance.
            name = prefix + entity.kind
            prev = readings.get(name)
            if prev is None or prev < 0 or (best >= 0 and best < prev):
                readings[name] = best

        if aggregate is not None:
            state.variables[cfg["aggregateVariable"]] = _reduce(
                aggregate, distances)
            return []

        state.variables.update(readings)
        return []
