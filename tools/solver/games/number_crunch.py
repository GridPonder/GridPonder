"""
Number Crunch game simulator for the GridPonder puzzle solver.

Faithfully implements the slide_merge, queued_emitters, and tile_teleport DSL
systems, plus the sequence_match (on_merge) goal evaluator, from the Dart
engine source.

State is immutable (frozen dataclass) so BFS can hash/deduplicate it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Direction vectors
# ---------------------------------------------------------------------------

DIRS: Dict[str, Tuple[int, int]] = {
    "up":    (0, -1),
    "down":  (0,  1),
    "left":  (-1, 0),
    "right": ( 1, 0),
}

ACTIONS: List[str] = ["up", "down", "left", "right"]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NCState:
    """
    Immutable snapshot of one Number Crunch turn.

    grid          — frozenset of (x, y, value) triples; one entry per tile.
    pipe_e1_idxs  — tuple of exit-1 emission counters, one per pipe.
                    Used for unidirectional pipes only.
    pipe_slots    — tuple of slot-tuples, one per pipe.  For bidirectional
                    pipes each inner tuple has length == pipe_length and
                    contains (int | None) per cell.  For unidirectional pipes
                    the inner tuple is empty.
    seq_idx       — how many steps of the goal sequence have been completed.
    """
    grid: FrozenSet[Tuple[int, int, int]]
    pipe_e1_idxs: Tuple[int, ...]
    pipe_slots: Tuple[Tuple[Optional[int], ...], ...]
    seq_idx: int


@dataclass
class PipeSpec:
    """Static pipe descriptor extracted from the level JSON."""
    exit_pos: Tuple[int, int]
    spawn_pos: Tuple[int, int]    # exitPos + one step in exitDirection
    exit2_pos: Optional[Tuple[int, int]]   # None for unidirectional pipes
    spawn2_pos: Optional[Tuple[int, int]]  # None for unidirectional pipes
    queue: List[int]
    pipe_length: int              # number of cells in the pipe MCO


@dataclass
class LevelInfo:
    """Static (immutable) data derived from a level JSON."""
    level_id: str
    width: int
    height: int
    void_cells: FrozenSet[Tuple[int, int]]
    teleporters: List[Tuple[Tuple[int, int], Tuple[int, int]]]  # list of (from, to) pairs
    pipes: List[PipeSpec]
    sequence: List[int]          # goal sequence (sequence_match / on_merge)
    max_turns: Optional[int]     # from loseConditions, or None


# ---------------------------------------------------------------------------
# Level loader
# ---------------------------------------------------------------------------

def load(level_json: Dict[str, Any]) -> Tuple[NCState, LevelInfo]:
    """Parse a level JSON dict into (initial_state, static_info)."""
    board = level_json["board"]
    w, h = board["size"]

    # Ground layer → void cells and portal pairs (supports dense and sparse)
    ground_data = board["layers"].get("ground", [])
    void_cells_list: List[Tuple[int, int]] = []
    portal_by_channel: Dict[str, List[Tuple[int, int]]] = {}

    if isinstance(ground_data, list):
        # Dense format: 2D array of kind strings
        for y, row in enumerate(ground_data):
            for x, cell in enumerate(row):
                if cell == "void":
                    void_cells_list.append((x, y))
                elif cell == "portal":
                    # Dense format has no channel param — treat all as channel ""
                    portal_by_channel.setdefault("", []).append((x, y))
    elif isinstance(ground_data, dict) and ground_data.get("format") == "sparse":
        for entry in ground_data.get("entries", []):
            px, py = entry["position"]
            kind = entry.get("kind", "empty")
            if kind in ("void", "pipe"):
                void_cells_list.append((px, py))
            elif kind == "portal":
                channel = entry.get("channel", "")
                portal_by_channel.setdefault(channel, []).append((px, py))

    void_cells: FrozenSet[Tuple[int, int]] = frozenset(void_cells_list)

    # Teleporters → list of (pos1, pos2) pairs (one per channel with 2 portals)
    teleporter_pairs: List[Tuple[Tuple[int, int], Tuple[int, int]]] = [
        (tuple(positions[0]), tuple(positions[1]))  # type: ignore[misc]
        for positions in portal_by_channel.values()
        if len(positions) == 2
    ]
    teleporter_set: FrozenSet[Tuple[int, int]] = frozenset(
        pos for pair in teleporter_pairs for pos in pair
    )

    # Objects layer → initial number tiles
    obj_layer = board["layers"].get("objects", {})
    grid_tiles: List[Tuple[int, int, int]] = []

    if isinstance(obj_layer, list):
        # Dense format: [[{kind, value}, ...], ...]
        for y, row in enumerate(obj_layer):
            for x, cell in enumerate(row):
                if cell and cell.get("kind") == "number":
                    grid_tiles.append((x, y, int(cell["value"])))
    elif isinstance(obj_layer, dict):
        if obj_layer.get("format") == "sparse":
            for entry in obj_layer.get("entries", []):
                if entry.get("kind") == "number":
                    px, py = entry["position"]
                    grid_tiles.append((px, py, int(entry["value"])))

    initial_grid: FrozenSet[Tuple[int, int, int]] = frozenset(grid_tiles)

    # Multi-cell objects → pipes
    pipes: List[PipeSpec] = []
    for mco in board.get("multiCellObjects", []):
        if mco.get("kind") != "pipe":
            continue
        params = mco.get("params", {})
        ex, ey = params["exitPosition"]
        exit_dir = params.get("exitDirection")
        if exit_dir:
            ddx, ddy = DIRS[exit_dir]
            spawn = (ex + ddx, ey + ddy)
        else:
            spawn = (ex, ey)
        # Bidirectional exit (optional)
        exit2: Optional[Tuple[int, int]] = None
        spawn2: Optional[Tuple[int, int]] = None
        if "exit2Position" in params:
            e2x, e2y = params["exit2Position"]
            exit2 = (e2x, e2y)
            exit2_dir = params.get("exit2Direction")
            if exit2_dir:
                d2x, d2y = DIRS[exit2_dir]
                spawn2 = (e2x + d2x, e2y + d2y)
            else:
                spawn2 = exit2
        queue = [int(v) for v in params.get("queue", [])]
        pipe_length = len(mco.get("cells", []))
        pipes.append(PipeSpec(
            exit_pos=(ex, ey),
            spawn_pos=spawn,
            exit2_pos=exit2,
            spawn2_pos=spawn2,
            queue=queue,
            pipe_length=pipe_length,
        ))

    # Goals → goal sequence (sequence_match with on_merge trigger)
    sequence: List[int] = []
    for goal in level_json.get("goals", []):
        if goal.get("type") == "sequence_match":
            sequence = [int(v) for v in goal["config"].get("sequence", [])]
            break  # assume one sequence goal per level

    # Lose conditions → optional move cap (max_turns or max_actions)
    max_turns: Optional[int] = None
    for lc in level_json.get("loseConditions", []):
        if lc.get("type") in ("max_turns", "max_actions"):
            max_turns = int(lc["config"]["limit"])
            break

    # Build initial pipe_slots for bidirectional pipes.
    initial_slots: List[Tuple[Optional[int], ...]] = []
    for pipe in pipes:
        if pipe.exit2_pos is not None:
            slots = [None] * pipe.pipe_length
            for j, v in enumerate(pipe.queue):
                if j < pipe.pipe_length:
                    slots[j] = v
            initial_slots.append(tuple(slots))
        else:
            initial_slots.append(())  # empty for unidirectional

    initial_state = NCState(
        grid=initial_grid,
        pipe_e1_idxs=tuple(0 for _ in pipes),
        pipe_slots=tuple(initial_slots),
        seq_idx=0,
    )
    info = LevelInfo(
        level_id=level_json.get("id", ""),
        width=w,
        height=h,
        void_cells=void_cells,
        teleporters=teleporter_pairs,
        pipes=pipes,
        sequence=sequence,
        max_turns=max_turns,
    )
    return initial_state, info


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def apply(
    state: NCState,
    direction: str,
    info: LevelInfo,
) -> Tuple[NCState, bool, List]:
    """
    Apply one move and return (new_state, won).

    Turn phases (mirrors the Dart engine):
      1. slide_merge     (Action Resolution, Phase 2)
      2. sequence_match  (Goal Evaluation, Phase 7 — on_merge)
      3. queued_emitters (NPC Resolution, Phase 6)
      4. tile_teleport   (NPC Resolution, Phase 6 — after queued_emitters)
      5. Win check
    """
    # Phase 2: slide_merge
    new_grid, merge_events = _slide_merge(state.grid, direction, info)

    # Phase 7: advance sequence index for every matching merge event
    seq_idx = state.seq_idx
    for merged_val in merge_events:
        if seq_idx < len(info.sequence) and merged_val == info.sequence[seq_idx]:
            seq_idx += 1

    # Phase 6: queued_emitters — emit items from pipes
    new_e1_idxs = list(state.pipe_e1_idxs)
    new_pipe_slots = [list(s) for s in state.pipe_slots]

    for i, pipe in enumerate(info.pipes):
        if pipe.exit2_pos is None:
            # ── Unidirectional (counter model, unchanged) ────────────────────
            e1 = new_e1_idxs[i]
            n = len(pipe.queue)
            if e1 >= n:
                continue
            exit_clear  = not _has_tile(new_grid, pipe.exit_pos)
            spawn_clear = not _has_tile(new_grid, pipe.spawn_pos)
            if exit_clear and spawn_clear:
                sx, sy = pipe.spawn_pos
                new_grid = new_grid | frozenset([(sx, sy, pipe.queue[e1])])
                new_e1_idxs[i] += 1
        else:
            # ── Bidirectional (slot model) ───────────────────────────────────
            slots = new_pipe_slots[i]
            pl = len(slots)
            last = pl - 1

            if all(v is None for v in slots):
                continue

            can1 = (not _has_tile(new_grid, pipe.exit_pos) and
                    not _has_tile(new_grid, pipe.spawn_pos))
            can2 = (not _has_tile(new_grid, pipe.exit2_pos) and
                    not _has_tile(new_grid, pipe.spawn2_pos))

            # Phase 1: emit items at exit cells.
            if slots[0] is not None and can1:
                sx, sy = pipe.spawn_pos
                new_grid = new_grid | frozenset([(sx, sy, slots[0])])
                slots[0] = None
            if slots[last] is not None and can2:
                sx, sy = pipe.spawn2_pos
                new_grid = new_grid | frozenset([(sx, sy, slots[last])])
                slots[last] = None

            # Phase 2: move remaining items one step toward nearest exit.
            moved = [None] * pl
            for j in range(pl):
                if slots[j] is None:
                    continue
                dist_e1 = j
                dist_e2 = last - j
                if dist_e1 < dist_e2:
                    target = j - 1
                elif dist_e2 < dist_e1:
                    target = j + 1
                else:
                    # Equidistant — midpoint stuck rule.
                    if can1 and not can2:
                        target = j - 1
                    elif can2 and not can1:
                        target = j + 1
                    else:
                        target = j  # stuck
                target = max(0, min(last, target))
                if moved[target] is not None:
                    target = j  # blocked by another item
                moved[target] = slots[j]

            new_pipe_slots[i] = moved

    # Phase 6b: tile_teleport — one pass per teleporter pair
    new_grid = _apply_teleporters(new_grid, info.teleporters)

    new_state = NCState(
        grid=new_grid,
        pipe_e1_idxs=tuple(new_e1_idxs),
        pipe_slots=tuple(tuple(s) for s in new_pipe_slots),
        seq_idx=seq_idx,
    )
    won = seq_idx >= len(info.sequence)
    return new_state, won, []


def _apply_teleporters(
    grid: FrozenSet[Tuple[int, int, int]],
    teleporters: List[Tuple[Tuple[int, int], Tuple[int, int]]],
) -> FrozenSet[Tuple[int, int, int]]:
    """
    Single-pass bidirectional tile teleportation (mirrors TileTeleportSystem).

    For each teleporter pair: if a tile is on one endpoint and the other is
    empty, move the tile to the other endpoint.  One pass only — no cascades.
    """
    if not teleporters:
        return grid

    working: Dict[Tuple[int, int], int] = {(x, y): v for x, y, v in grid}

    for (fx, fy), (tx, ty) in teleporters:
        from_val = working.get((fx, fy))
        to_val   = working.get((tx, ty))
        if from_val is not None and to_val is None:
            del working[(fx, fy)]
            working[(tx, ty)] = from_val
        elif to_val is not None and from_val is None:
            del working[(tx, ty)]
            working[(fx, fy)] = to_val

    return frozenset((x, y, v) for (x, y), v in working.items())


def _has_tile(grid: FrozenSet[Tuple[int, int, int]], pos: Tuple[int, int]) -> bool:
    px, py = pos
    return any(x == px and y == py for x, y, _ in grid)


def _slide_merge(
    grid: FrozenSet[Tuple[int, int, int]],
    direction: str,
    info: LevelInfo,
) -> Tuple[FrozenSet[Tuple[int, int, int]], List[int]]:
    """
    Simulate the slide_merge system for one swipe direction.

    Algorithm (faithful to SlideMergeSystem.dart):
      - Sort tiles from the leading edge inward (so the tile nearest the wall
        in the swipe direction is processed first).
      - For each tile, slide it forward until it hits a boundary, void,
        teleporter endpoint, or another tile.  On meeting another tile: if
        neither has already merged this action (mergeLimit=1), merge them into
        their sum.
      - Commit the working board to the new grid.

    Returns (new_grid, merge_events) where merge_events is a list of merged
    result values in the order they were produced (used for on_merge goal
    checking).
    """
    dx, dy = DIRS[direction]

    # Build a fast set of all teleporter endpoint positions.
    teleporter_positions: set = set()
    for (fx, fy), (tx, ty) in info.teleporters:
        teleporter_positions.add((fx, fy))
        teleporter_positions.add((tx, ty))

    # Sort from leading edge first
    def _sort_key(t: Tuple[int, int, int]) -> int:
        x, y, _ = t
        if direction == "right": return -x
        if direction == "left":  return  x
        if direction == "down":  return -y
        return y  # up

    tiles = sorted(grid, key=_sort_key)

    # Working board: (x, y) → value  (reflects committed moves so far)
    working: Dict[Tuple[int, int], int] = {(x, y): v for x, y, v in tiles}

    # Positions that have already been the *target* of a merge this action.
    # A position in this set cannot receive another merge (mergeLimit = 1).
    merge_targets: set = set()
    merge_events: List[int] = []

    for x0, y0, _ in tiles:
        if (x0, y0) not in working:
            continue  # this tile was consumed as the source of an earlier merge

        val = working[(x0, y0)]
        cx, cy = x0, y0          # current sliding position
        nx, ny = cx + dx, cy + dy

        did_merge = False

        while True:
            # Boundary check
            if not (0 <= nx < info.width and 0 <= ny < info.height):
                break
            # Void check
            if (nx, ny) in info.void_cells:
                break

            if (nx, ny) in working:
                # Another tile is here.
                if (nx, ny) in merge_targets:
                    break  # mergeLimit exceeded at this destination
                # same_kind predicate: always true (all objects are "number")
                result = val + working[(nx, ny)]
                del working[(x0, y0)]
                working[(nx, ny)] = result
                merge_targets.add((nx, ny))
                merge_events.append(result)
                did_merge = True
                break
            else:
                # Move to next cell; stop ON teleporter endpoints.
                cx, cy = nx, ny
                if (cx, cy) in teleporter_positions:
                    break
                nx, ny = cx + dx, cy + dy

        if not did_merge and (cx, cy) != (x0, y0):
            # Tile slid without merging; commit to new position
            working[(cx, cy)] = working.pop((x0, y0))

    new_grid = frozenset((x, y, v) for (x, y), v in working.items())
    return new_grid, merge_events


# ---------------------------------------------------------------------------
# Pruning hints
# ---------------------------------------------------------------------------

def can_prune(
    state: NCState,
    info: LevelInfo,
    depth: int,
    max_depth: int,
) -> bool:
    """
    Return True if this branch is provably unsolvable and can be cut.

    Three checks (all conservative — they never prune valid solutions):

    1. Deadline: remaining sequence steps > remaining moves.
       Every goal step requires at least one merge, so we need at least
       (len(sequence) - seq_idx) more moves.

    2. Empty grid: no tiles on the board but sequence not done.
       No tiles → no merges possible → can never reach any more targets.

    3. Min-value: the smallest tile value exceeds the next sequence target.
       Merges only produce values ≥ (a + b) > max(a, b) ≥ min(grid).
       So if min(grid) > next_target, we can never produce next_target.
    """
    remaining_steps = len(info.sequence) - state.seq_idx
    remaining_moves = max_depth - depth

    if remaining_steps > remaining_moves:
        return True

    if not state.grid and remaining_steps > 0:
        return True

    if state.grid and remaining_steps > 0:
        min_val = min(v for _, _, v in state.grid)
        next_target = info.sequence[state.seq_idx]
        if min_val > next_target:
            return True

    return False
