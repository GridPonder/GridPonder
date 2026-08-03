"""SupportCollapseSystem — see docs/dsl/04_systems.md."""
from __future__ import annotations

from collections import deque
from typing import Optional

from .._game_def import GameDef
from .._models import Entity, GameState, Pos, dir_delta
from .. import _events as ev
from ._base import GameSystem

_CARDINALS = [Pos(0, -1), Pos(0, 1), Pos(-1, 0), Pos(1, 0)]
_DIAGONALS = _CARDINALS + [Pos(-1, -1), Pos(1, -1), Pos(-1, 1), Pos(1, 1)]


class SupportCollapseSystem(GameSystem):
    """Cells that lose their connection to a support root fall as rigid bodies.

    A structure is held up by cells tagged as roots. After any cell is removed,
    every maximal group of member cells that can no longer reach a root is an
    orphan, and each orphan translates in the configured direction — keeping its
    exact shape — until one of its cells is blocked. Components fall
    simultaneously, one step at a time, so stacked orphans resolve
    deterministically without an ordering rule.

    Generic: any game with a structure hanging from fixed roots names its own
    root/member tags and fall direction. The player-facing sever verb is
    optional — omit `severAction` and drive the collapse from `triggerEvents`
    when cells are removed by rules or other systems instead.
    """

    def __init__(self, sys_id: str, config: Optional[dict] = None):
        super().__init__(sys_id, "support_collapse")
        self.config = config or {}

    # ── config ──────────────────────────────────────────────────────────────
    def _cfg(self, game: GameDef) -> dict:
        return self.config or game.system_config(self.id)

    @staticmethod
    def _default_kind(game: GameDef, layer_id: str) -> Optional[str]:
        """The kind an emptied cell reverts to on an exactly_one layer."""
        for layer in game.layers:
            if layer.get("id") == layer_id:
                if layer.get("isExactlyOne"):
                    return layer.get("defaultKind") or "empty"
                return None
        return None

    def _empty(self, game: GameDef, layer_id: str) -> Optional[Entity]:
        kind = self._default_kind(game, layer_id)
        return Entity(kind) if kind else None

    # ── phase 2: the sever verb ─────────────────────────────────────────────
    def execute_action_resolution(
        self, action: dict, state: GameState, game: GameDef
    ) -> list[dict]:
        cfg = self._cfg(game)
        sever_action = cfg.get("severAction")
        if not sever_action or action.get("actionId") != sever_action:
            return []

        dir_str = action.get("params", {}).get("direction")
        if not dir_str:
            return [ev.action_vetoed()]

        avatar = state.avatar
        if not avatar.enabled or avatar.position is None:
            return [ev.action_vetoed()]

        layer_id = cfg.get("layer", "ground")
        layer = state.board.layers.get(layer_id)
        if layer is None:
            return [ev.action_vetoed()]

        dx, dy = dir_delta(dir_str)
        if dx == 0 and dy == 0:
            return [ev.action_vetoed()]
        target = Pos(avatar.position.x + dx, avatar.position.y + dy)
        if not state.board.is_in_bounds(target):
            return [ev.action_vetoed()]

        entity = layer.get(target)
        severable = cfg.get("severableTags", ["severable"])
        if entity is None or not any(
            game.has_tag(entity.kind, tag) for tag in severable
        ):
            return [ev.action_vetoed()]

        previous_kind = entity.kind
        layer.set(target, self._empty(game, layer_id))
        events = [ev.cell_cleared(target, previous_kind)]
        events.extend(self._collapse(state, game, cfg))
        return events

    # ── phase 5: event-driven collapse ──────────────────────────────────────
    def execute_cascade_resolution(
        self, trigger_events: list[dict], state: GameState, game: GameDef
    ) -> list[dict]:
        cfg = self._cfg(game)
        triggers = set(cfg.get("triggerEvents", []))
        if not triggers:
            return []
        if not any(e.get("type") in triggers for e in trigger_events):
            return []
        return self._collapse(state, game, cfg)

    # ── the algorithm ───────────────────────────────────────────────────────
    def _collapse(self, state: GameState, game: GameDef, cfg: dict) -> list[dict]:
        layer_id = cfg.get("layer", "ground")
        layer = state.board.layers.get(layer_id)
        if layer is None:
            return []
        board = state.board

        root_tags = cfg.get("rootTags", ["support_root"])
        member_tags = cfg.get("memberTags", ["supported"])
        deltas = _DIAGONALS if cfg.get("connectivity") == "diagonal" else _CARDINALS

        def is_root(pos: Pos) -> bool:
            e = layer.get(pos)
            return e is not None and any(game.has_tag(e.kind, t) for t in root_tags)

        def is_member(pos: Pos) -> bool:
            e = layer.get(pos)
            return e is not None and any(game.has_tag(e.kind, t) for t in member_tags)

        # 1. BFS the supported set outward from every root.
        supported: set[Pos] = set()
        queue: deque[Pos] = deque()
        for y in range(board.height):
            for x in range(board.width):
                p = Pos(x, y)
                if is_root(p):
                    supported.add(p)
                    queue.append(p)
        while queue:
            cur = queue.popleft()
            for d in deltas:
                nb = Pos(cur.x + d.x, cur.y + d.y)
                if nb in supported or not board.is_in_bounds(nb):
                    continue
                if is_member(nb):
                    supported.add(nb)
                    queue.append(nb)

        # 2. Group the unsupported members into maximal connected components.
        remaining = {
            Pos(x, y)
            for y in range(board.height)
            for x in range(board.width)
            if is_member(Pos(x, y)) and Pos(x, y) not in supported
        }
        if not remaining:
            return []

        components: list[list[Pos]] = []
        while remaining:
            seed = next(iter(remaining))
            remaining.discard(seed)
            comp = [seed]
            q: deque[Pos] = deque([seed])
            while q:
                cur = q.popleft()
                for d in deltas:
                    nb = Pos(cur.x + d.x, cur.y + d.y)
                    if nb in remaining:
                        remaining.discard(nb)
                        comp.append(nb)
                        q.append(nb)
            components.append(comp)

        # 3. Lift every orphan cell off the board first, so a component is never
        #    blocked by the hole it is falling out of, nor by another orphan
        #    that is falling alongside it.
        kinds: list[dict[Pos, Entity]] = []
        for comp in components:
            kinds.append({p: layer.get(p) for p in comp})
            for p in comp:
                layer.set(p, self._empty(game, layer_id))

        dx, dy = dir_delta(cfg.get("direction", "down"))
        rest_layers = cfg.get("restLayers", [layer_id])
        rest_tags = cfg.get("restTags", ["solid"])

        def blocked(cells: list[Pos]) -> bool:
            for c in cells:
                nxt = Pos(c.x + dx, c.y + dy)
                if not board.is_in_bounds(nxt):
                    continue  # leaving the board never blocks
                for rl in rest_layers:
                    rlayer = board.layers.get(rl)
                    if rlayer is None:
                        continue
                    e = rlayer.get(nxt)
                    if e is not None and any(
                        game.has_tag(e.kind, t) for t in rest_tags
                    ):
                        return True
            return False

        # 4. Step every unfrozen component one cell at a time until none move.
        positions = [list(comp) for comp in components]
        frozen: set[int] = set()
        for _ in range(board.width + board.height + 1):
            moved_any = False
            for idx, cells in enumerate(positions):
                if idx in frozen:
                    continue
                if not any(board.is_in_bounds(c) for c in cells):
                    frozen.add(idx)
                    continue
                if blocked(cells):
                    frozen.add(idx)
                    continue
                positions[idx] = [Pos(c.x + dx, c.y + dy) for c in cells]
                moved_any = True
            if not moved_any:
                break

        # 5. Write the landed cells back, applying settleTransform.
        settle = {k: str(v) for k, v in cfg.get("settleTransform", {}).items()}
        events: list[dict] = []
        avatar_pos = state.avatar.position if state.avatar.enabled else None
        avatar_component: Optional[int] = None
        avatar_destination: Optional[Pos] = None

        for idx, comp in enumerate(components):
            for src, dst in zip(comp, positions[idx]):
                if avatar_pos is not None and src == avatar_pos:
                    avatar_component = idx
                    avatar_destination = dst
                if not board.is_in_bounds(dst):
                    continue  # this cell left the world
                entity = kinds[idx][src]
                new_kind = settle.get(entity.kind, entity.kind)
                layer.set(dst, Entity(new_kind, dict(entity.params)))
                events.append(ev.object_settled(new_kind, dst, src))

        # 6. The avatar rides its component down.
        if avatar_component is not None and cfg.get("carryAvatar", True):
            if avatar_destination is not None and board.is_in_bounds(
                avatar_destination
            ):
                state.avatar.position = avatar_destination
            var = cfg.get("avatarFellVariable")
            if var:
                old = state.variables.get(var, 0) or 0
                state.variables[var] = old + 1
                events.append(ev.variable_changed(var, old, state.variables[var]))

        return events
