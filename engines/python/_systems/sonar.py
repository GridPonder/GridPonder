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
    return {
        "sourceLayer": source_layer,
        "targetLayer": target_layer,
        "pairing": pairing,
        "variablePrefix": prefix,
    }


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

        readings: dict[str, int] = {}
        for pos, entity in source_layer.entries():
            wanted = pairing.get(entity.kind) if pairing is not None else None
            best = -1
            for tpos, tentity in targets:
                if wanted is not None and tentity.kind != wanted:
                    continue
                dist = abs(pos.x - tpos.x) + abs(pos.y - tpos.y)
                if best < 0 or dist < best:
                    best = dist
            # Two sources of the same kind collapse to the minimum, so the
            # written value does not depend on iteration order. -1 (no target)
            # loses to any real distance.
            name = prefix + entity.kind
            prev = readings.get(name)
            if prev is None or prev < 0 or (best >= 0 and best < prev):
                readings[name] = best

        state.variables.update(readings)
        return []
