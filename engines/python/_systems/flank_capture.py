"""FlankCaptureSystem.

Reversi/Othello-style bracket capture, applied after an actor moves.

When a piece moves, any straight run of one kind that ends up bracketed
between two of the opposing kind (or a terminating wall) is flipped to the
bracketing kind. Two configured ``pairs`` let the same rule work both ways:
an ``alien`` bracketing a run of ``human`` **possesses** it, while a run of
``alien`` bracketed by ``human`` is **exposed** and flips back — the mover
included.

The moved piece anchors every capture: a victim run flips only when the moved
piece is one of its two bracketing terminals (an *attack*) or a cell inside the
run itself (a *self-capture / exposure*). This keeps captures tied to the move
that caused them — a pair sitting between two walls is not silently flipped the
first time any actor happens onto its row.

A single pre-flip snapshot of the piece layer is taken up front; every pass
reads that snapshot, so a cell can never flip twice in one move and the possess
and expose passes never observe each other's fresh cells.

Generic: any game with two opposing piece kinds that flip on a straight-line
bracket names its own ``pairs`` and layer (contagion-by-flanking, tug-of-war
captures, Reversi puzzles).

An aggressor may name several victim kinds (``"alien": ["human", "splinter"]``).
Each victim kind is scanned on its own pass, so runs stay homogeneous — a run
that mixes two victim kinds is not a maximal run of either, and is therefore
immune. When two aggressors share a victim kind, ``order`` decides: flips dedupe
first-writer-wins, so the aggressor listed earlier claims a contested cell.
"""
from __future__ import annotations

from .._game_def import GameDef
from .._models import CARDINALS, Entity, GameState, Pos
from .. import _events as ev
from ._base import GameSystem


# Axis unit steps. A "line through B" is the full row (horizontal) and/or full
# column (vertical) that contains the moved cell B.
_AXES: dict[str, tuple[int, int]] = {
    "horizontal": (1, 0),
    "vertical": (0, 1),
}


class FlankCaptureSystem(GameSystem):
    def __init__(self, sys_id: str, config: dict | None = None):
        super().__init__(sys_id, "flank_capture")
        self._config = config

    def execute_cascade_resolution(
        self,
        trigger_events: list[dict],
        state: GameState,
        game: GameDef,
    ) -> list[dict]:
        config = self._config if self._config is not None else game.system_config(self.id)

        triggers = {
            str(value)
            for value in config.get("triggerEvents", ["actor_moved"])
        }
        dests = _dest_cells(trigger_events, triggers)
        if not dests:
            return []

        piece_layer_id = str(config.get("pieceLayer", "pieces"))
        layer = state.board.layers.get(piece_layer_id)
        if layer is None:
            return []

        pairs = config.get("pairs") or {}
        if not pairs:
            return []
        order = [str(k) for k in (config.get("order") or list(pairs.keys()))]
        directions = {str(d) for d in config.get("directions", list(CARDINALS))}
        axes = _axes_from_directions(directions)
        if not axes:
            return []
        wall_terminates = bool(config.get("wallTerminates", True))
        wall_layer = str(config.get("wallLayer", "ground"))
        wall_tag = str(config.get("wallTag", "solid"))

        # Single pre-flip snapshot: (x, y) -> piece kind for every occupied cell.
        snapshot: dict[tuple[int, int], str] = {
            (pos.x, pos.y): entity.kind for pos, entity in layer.entries()
        }

        def piece_at(x: int, y: int) -> str | None:
            return snapshot.get((x, y))

        def is_wall(x: int, y: int) -> bool:
            return wall_terminates and state.board.has_tag_at(
                wall_layer, Pos(x, y), wall_tag, game.entity_kinds)

        width = state.board.width
        height = state.board.height

        # Deterministic flip accumulation, deduped by cell. Possess-then-expose
        # over one snapshot targets disjoint cell sets, so a plain dict is safe.
        flips: dict[tuple[int, int], str] = {}
        ordered: list[tuple[int, int]] = []

        for aggressor in order:
            raw_victim = pairs.get(aggressor)
            if raw_victim is None:
                continue
            victims = (
                [str(v) for v in raw_victim]
                if isinstance(raw_victim, (list, tuple))
                else [str(raw_victim)]
            )
            for victim in victims:
                for b in dests:
                    for axis, (adx, _ady) in _AXES.items():
                        if axis not in axes:
                            continue
                        if adx:  # horizontal row through b.y
                            line = [(x, b.y) for x in range(width)]
                            b_index = b.x
                        else:    # vertical column through b.x
                            line = [(b.x, y) for y in range(height)]
                            b_index = b.y
                        _scan_line(
                            line, b_index, aggressor, victim,
                            piece_at, is_wall, flips, ordered)

        if not flips:
            return []

        events: list[dict] = []
        for (x, y) in ordered:
            to_kind = flips[(x, y)]
            from_kind = snapshot.get((x, y))
            pos = Pos(x, y)
            layer.set(pos, Entity(to_kind))
            events.append(
                ev.cell_transformed(pos, from_kind, to_kind, piece_layer_id))
        return events


def _dest_cells(trigger_events: list[dict], triggers: set[str]) -> list[Pos]:
    dests: list[Pos] = []
    seen: set[tuple[int, int]] = set()
    for event in trigger_events:
        if event.get("type") not in triggers:
            continue
        raw = event.get("position")
        if isinstance(raw, Pos):
            pos = raw
        elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
            pos = Pos(int(raw[0]), int(raw[1]))
        else:
            continue
        key = (pos.x, pos.y)
        if key not in seen:
            seen.add(key)
            dests.append(pos)
    return dests


def _axes_from_directions(directions: set[str]) -> set[str]:
    axes: set[str] = set()
    if directions & {"left", "right"}:
        axes.add("horizontal")
    if directions & {"up", "down"}:
        axes.add("vertical")
    return axes


def _scan_line(
    line: list[tuple[int, int]],
    b_index: int,
    aggressor: str,
    victim: str,
    piece_at,
    is_wall,
    flips: dict[tuple[int, int], str],
    ordered: list[tuple[int, int]],
) -> None:
    """Flip every maximal victim-run on ``line`` that is bracketed by an
    aggressor/wall terminal on both ends *and* is anchored to the moved cell at
    ``b_index`` (the mover is a bracketing terminal, or lies inside the run).
    The board edge is never a terminal — only a wall or an aggressor piece is.
    """
    n = len(line)

    def terminal(idx: int) -> bool:
        if idx < 0 or idx >= n:
            return False  # board edge is not a terminal
        x, y = line[idx]
        if is_wall(x, y):
            return True
        return piece_at(x, y) == aggressor

    i = 0
    while i < n:
        x, y = line[i]
        if piece_at(x, y) != victim:
            i += 1
            continue
        # Maximal victim run [i..j].
        j = i
        while j + 1 < n and piece_at(*line[j + 1]) == victim:
            j += 1
        if terminal(i - 1) and terminal(j + 1):
            anchored = (i <= b_index <= j) or b_index == i - 1 or b_index == j + 1
            if anchored:
                for k in range(i, j + 1):
                    cell = line[k]
                    if cell not in flips:
                        flips[cell] = aggressor
                        ordered.append(cell)
        i = j + 1
