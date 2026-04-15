"""
Core data models: Position, Direction, Entity, Board, GameState.

These mirror the Dart engine's models (engine/lib/src/models/) but use
idiomatic Python: frozen dataclasses for value types, mutable classes for
runtime state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Pos:
    x: int
    y: int

    def moved(self, direction: str) -> "Pos":
        dx, dy = _DIR_DELTA[direction]
        return Pos(self.x + dx, self.y + dy)

    def is_valid(self, w: int, h: int) -> bool:
        return 0 <= self.x < w and 0 <= self.y < h

    def __iter__(self):
        yield self.x
        yield self.y

    @classmethod
    def from_json(cls, j) -> "Pos":
        if isinstance(j, (list, tuple)):
            return cls(int(j[0]), int(j[1]))
        if isinstance(j, dict):
            return cls(int(j["x"]), int(j["y"]))
        raise ValueError(f"Cannot parse Pos from {j!r}")


# ---------------------------------------------------------------------------
# Direction
# ---------------------------------------------------------------------------

_DIR_DELTA: dict[str, tuple[int, int]] = {
    "up":         (0, -1),
    "down":       (0,  1),
    "left":       (-1, 0),
    "right":      (1,  0),
    "up_left":    (-1, -1),
    "up_right":   (1, -1),
    "down_left":  (-1, 1),
    "down_right": (1,  1),
}

_DIR_OPPOSITE: dict[str, str] = {
    "up":         "down",
    "down":       "up",
    "left":       "right",
    "right":      "left",
    "up_left":    "down_right",
    "down_right": "up_left",
    "up_right":   "down_left",
    "down_left":  "up_right",
}

CARDINALS = frozenset({"up", "down", "left", "right"})


def dir_delta(d: str) -> tuple[int, int]:
    return _DIR_DELTA.get(d, (0, 0))


def dir_opposite(d: str) -> str:
    return _DIR_OPPOSITE.get(d, d)


def is_cardinal(d: str) -> bool:
    return d in CARDINALS


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------

@dataclass
class Entity:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)

    def param(self, key: str) -> Any:
        return self.params.get(key)

    def copy(self) -> "Entity":
        return Entity(self.kind, dict(self.params))

    def to_key(self) -> tuple:
        return (self.kind, tuple(sorted(self.params.items())))

    @classmethod
    def from_json(cls, j) -> "Entity":
        if isinstance(j, str):
            return cls(j)
        if isinstance(j, dict):
            kind = j["kind"]
            params = {k: v for k, v in j.items() if k != "kind"}
            return cls(kind, params)
        raise ValueError(f"Cannot parse Entity from {j!r}")

    def __repr__(self) -> str:
        if not self.params:
            return self.kind
        p = ",".join(f"{k}:{v}" for k, v in self.params.items())
        return f"{self.kind}({p})"


# ---------------------------------------------------------------------------
# MultiCellObject (pipe / emitter)
# ---------------------------------------------------------------------------

@dataclass
class MultiCellObject:
    id: str
    kind: str
    cells: list[Pos]
    params: dict[str, Any] = field(default_factory=dict)

    def copy(self) -> "MultiCellObject":
        return MultiCellObject(
            self.id,
            self.kind,
            list(self.cells),
            {k: (list(v) if isinstance(v, list) else v) for k, v in self.params.items()},
        )

    @classmethod
    def from_json(cls, j: dict) -> "MultiCellObject":
        cells = []
        for c in j.get("cells", []):
            if isinstance(c, (list, tuple)):
                cells.append(Pos.from_json(c))
            elif isinstance(c, dict):
                cells.append(Pos.from_json(c["position"]))
        params = dict(j.get("params", {}))
        return cls(j["id"], j["kind"], cells, params)


# ---------------------------------------------------------------------------
# Board layer
# ---------------------------------------------------------------------------

class BoardLayer:
    """Dense 2-D grid [y][x] of optional Entity, matching Dart's BoardLayer."""

    __slots__ = ("width", "height", "_cells")

    def __init__(self, width: int, height: int, cells: list[list[Optional[Entity]]]):
        self.width = width
        self.height = height
        self._cells = cells

    @classmethod
    def empty(cls, width: int, height: int, default_kind: Optional[str] = None) -> "BoardLayer":
        cells = [
            [Entity(default_kind) if default_kind else None for _ in range(width)]
            for _ in range(height)
        ]
        return cls(width, height, cells)

    @classmethod
    def from_json(cls, json_val, width: int, height: int, default_kind: Optional[str] = None) -> "BoardLayer":
        layer = cls.empty(width, height, default_kind)
        if json_val is None:
            return layer
        if isinstance(json_val, list):
            # Dense format: json_val[y][x]
            for y, row in enumerate(json_val):
                if y >= height:
                    break
                if row is None:
                    continue
                for x, cell in enumerate(row):
                    if x >= width:
                        break
                    layer._cells[y][x] = Entity.from_json(cell) if cell is not None else None
            return layer
        if isinstance(json_val, dict) and json_val.get("format") == "sparse":
            for entry in json_val.get("entries", []):
                pos = Pos.from_json(entry["position"])
                if not pos.is_valid(width, height):
                    continue
                kind = entry.get("kind")
                if kind is not None:
                    params = {k: v for k, v in entry.items() if k not in ("position", "kind")}
                    layer._cells[pos.y][pos.x] = Entity(kind, params)
            return layer
        raise ValueError(f"Unknown layer format: {json_val!r}")

    def get(self, pos: Pos) -> Optional[Entity]:
        if not pos.is_valid(self.width, self.height):
            return None
        return self._cells[pos.y][pos.x]

    def set(self, pos: Pos, entity: Optional[Entity]) -> None:
        if not pos.is_valid(self.width, self.height):
            return
        self._cells[pos.y][pos.x] = entity

    def entries(self):
        """Yield (Pos, Entity) for all non-null cells."""
        for y in range(self.height):
            for x in range(self.width):
                e = self._cells[y][x]
                if e is not None:
                    yield Pos(x, y), e

    def copy(self) -> "BoardLayer":
        cells = [[e.copy() if e is not None else None for e in row] for row in self._cells]
        return BoardLayer(self.width, self.height, cells)


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------

class Board:
    """Full game board: all layers + multi-cell objects."""

    __slots__ = ("width", "height", "layers", "multi_cell_objects")

    def __init__(
        self,
        width: int,
        height: int,
        layers: dict[str, BoardLayer],
        multi_cell_objects: list[MultiCellObject],
    ):
        self.width = width
        self.height = height
        self.layers = layers
        self.multi_cell_objects = multi_cell_objects

    @classmethod
    def from_json(cls, j: dict, layer_defs: list) -> "Board":
        size = j["size"]
        w, h = int(size[0]), int(size[1])
        raw_layers = j.get("layers", {})
        layers: dict[str, BoardLayer] = {}
        for ldef in layer_defs:
            default_kind = ldef["defaultKind"] if ldef["isExactlyOne"] else None
            layers[ldef["id"]] = BoardLayer.from_json(
                raw_layers.get(ldef["id"]), w, h, default_kind
            )
        mcos = [MultiCellObject.from_json(m) for m in j.get("multiCellObjects", [])]
        return cls(w, h, layers, mcos)

    def get_entity(self, layer_id: str, pos: Pos) -> Optional[Entity]:
        layer = self.layers.get(layer_id)
        return layer.get(pos) if layer else None

    def set_entity(self, layer_id: str, pos: Pos, entity: Optional[Entity]) -> None:
        layer = self.layers.get(layer_id)
        if layer:
            layer.set(pos, entity)

    def is_in_bounds(self, pos: Pos) -> bool:
        return pos.is_valid(self.width, self.height)

    def is_void(self, pos: Pos) -> bool:
        ground = self.get_entity("ground", pos)
        return ground is not None and ground.kind == "void"

    def has_tag_at(self, layer_id: str, pos: Pos, tag: str, entity_kinds: dict) -> bool:
        entity = self.get_entity(layer_id, pos)
        if entity is None:
            return False
        kind_def = entity_kinds.get(entity.kind)
        return tag in (kind_def.get("tags", []) if kind_def else [])

    def get_multi_cell_object(self, mco_id: str) -> Optional[MultiCellObject]:
        for m in self.multi_cell_objects:
            if m.id == mco_id:
                return m
        return None

    def copy(self) -> "Board":
        return Board(
            self.width,
            self.height,
            {k: v.copy() for k, v in self.layers.items()},
            [m.copy() for m in self.multi_cell_objects],
        )


# ---------------------------------------------------------------------------
# Avatar / Inventory
# ---------------------------------------------------------------------------

@dataclass
class AvatarState:
    enabled: bool = True
    position: Optional[Pos] = None
    facing: str = "right"
    item: Optional[str] = None  # inventory slot

    def copy(self) -> "AvatarState":
        return AvatarState(self.enabled, self.position, self.facing, self.item)

    @classmethod
    def from_json(cls, j: dict, game_defaults: dict) -> "AvatarState":
        enabled = j.get("enabled", game_defaults.get("avatarEnabled", True))
        pos_raw = j.get("position")
        pos = Pos.from_json(pos_raw) if pos_raw is not None else None
        facing = j.get("facing", game_defaults.get("avatarFacing", "right"))
        inv = j.get("inventory", {})
        item = inv.get("slot") if isinstance(inv, dict) else None
        return cls(enabled, pos, facing, item)


# ---------------------------------------------------------------------------
# Overlay cursor
# ---------------------------------------------------------------------------

@dataclass
class OverlayCursor:
    x: int
    y: int
    width: int
    height: int

    def copy(self) -> "OverlayCursor":
        return OverlayCursor(self.x, self.y, self.width, self.height)

    @classmethod
    def from_json(cls, j: dict) -> "OverlayCursor":
        pos = j.get("position", [0, 0])
        size = j.get("size", [2, 2])
        return cls(int(pos[0]), int(pos[1]), int(size[0]), int(size[1]))


# ---------------------------------------------------------------------------
# Pending move (set when solidHandling == "delegate")
# ---------------------------------------------------------------------------

@dataclass
class PendingMove:
    from_pos: Pos
    to_pos: Pos
    direction: str


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------

class GameState:
    """Full mutable runtime state for one level."""

    __slots__ = (
        "board", "avatar", "variables", "overlay",
        "turn_count", "action_count", "pending_move",
        "sequence_indices", "once_fired_rules",
        "is_won", "is_lost",
    )

    def __init__(
        self,
        board: Board,
        avatar: AvatarState,
        variables: dict[str, Any],
        overlay: Optional[OverlayCursor] = None,
        turn_count: int = 0,
        action_count: int = 0,
        pending_move: Optional[PendingMove] = None,
        sequence_indices: Optional[dict[str, int]] = None,
        once_fired_rules: Optional[set[str]] = None,
        is_won: bool = False,
        is_lost: bool = False,
    ):
        self.board = board
        self.avatar = avatar
        self.variables = variables
        self.overlay = overlay
        self.turn_count = turn_count
        self.action_count = action_count
        self.pending_move = pending_move
        self.sequence_indices = sequence_indices if sequence_indices is not None else {}
        self.once_fired_rules = once_fired_rules if once_fired_rules is not None else set()
        self.is_won = is_won
        self.is_lost = is_lost

    @classmethod
    def from_json(cls, state_json: dict, board: Board, game_defaults: dict) -> "GameState":
        avatar_j = state_json.get("avatar", {})
        avatar = AvatarState.from_json(avatar_j, game_defaults)
        variables = dict(state_json.get("variables", {}))
        overlay_j = state_json.get("overlay")
        overlay = OverlayCursor.from_json(overlay_j) if overlay_j else None
        return cls(board, avatar, variables, overlay)

    def copy(self) -> "GameState":
        return GameState(
            self.board.copy(),
            self.avatar.copy(),
            dict(self.variables),
            self.overlay.copy() if self.overlay else None,
            self.turn_count,
            self.action_count,
            self.pending_move,  # immutable dataclass, safe to share
            dict(self.sequence_indices),
            set(self.once_fired_rules),
            self.is_won,
            self.is_lost,
        )

    def to_key(self) -> tuple:
        """Hashable snapshot for BFS/A* deduplication."""
        board_key = tuple(
            (lid, tuple(
                (x, y, e.to_key())
                for y in range(layer.height)
                for x in range(layer.width)
                if (e := layer._cells[y][x]) is not None
            ))
            for lid, layer in sorted(self.board.layers.items())
        )
        mco_key = tuple(
            (m.id, tuple(sorted(m.params.items())))
            for m in self.board.multi_cell_objects
        )
        av = self.avatar
        avatar_key = (av.enabled, av.position, av.facing, av.item)
        vars_key = tuple(sorted(self.variables.items()))
        return (board_key, mco_key, avatar_key, vars_key)
