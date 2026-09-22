"""TrailingBodySystem — see docs/dsl/04_systems.md §2.26.

Makes a mover drag a body of variable length behind it, Snake-style, with
cells behind the tail freed as the mover advances (unlike Snake Tunnel's
permanent trail).

Systems are re-instantiated every turn (see `instantiate_systems`), so this
class holds no mutable fields of its own. Everything it needs to remember
between turns — the mover's position before its most recent move, and the
ordered list of segment (position, color) pairs — is persisted in
``state.variables`` under keys namespaced by this system's ``id``. That is
the "internal ordered list" the DSL doc describes; it just has to live in
state rather than instance memory.

Growth is detected *structurally*, not by comparing ``lengthVariable`` across
turns. This system runs in ``movement_resolution`` (phase 3), one phase
before rules run in ``cascade_resolution`` (phase 5) — the phase where a
pickup rule (Recipe A, ``docs/dsl/05_rules.md``) would destroy the consumed
entity and increment the length variable. Reading ``lengthVariable`` here
would therefore always be one phase stale within the pickup's own turn.
Instead, this system checks the board directly, at the mover's *new* cell,
for an entity tagged ``growthTriggerTag`` on ``growthKindSource`` — which is
still there, since the rule that will destroy it hasn't run yet.
``lengthVariable`` is read fresh each turn only to reconcile the incidental
drift case (padding/shrinking when the variable and the structural trail
disagree, e.g. a level that starts the mover already carrying cargo) — never
to detect this turn's own growth.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .. import _events as ev
from .._game_def import GameDef
from .._models import Entity, GameState, Pos
from ._base import GameSystem


@dataclass(frozen=True)
class _Segment:
    """One body segment: a fixed appearance (assigned once, at creation)
    plus a position that is rewritten every turn. ``color`` drives the
    templated kind (``segmentKindTemplate``); ``literal_kind``, when set,
    bypasses the template entirely — used only for the best-effort load-time
    backfill documented on the class above.
    """

    position: Pos
    color: Optional[str] = None
    literal_kind: Optional[str] = None

    @classmethod
    def from_json(cls, j: dict) -> "_Segment":
        return cls(
            Pos.from_json(j["position"]),
            j.get("color"),
            j.get("literalKind"),
        )

    def to_json(self) -> dict:
        out: dict[str, Any] = {"position": [self.position.x, self.position.y]}
        if self.color is not None:
            out["color"] = self.color
        if self.literal_kind is not None:
            out["literalKind"] = self.literal_kind
        return out


def _cfg(config: dict, key: str, default):
    value = config.get(key)
    return default if value is None else value


def _read_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _direction_between(from_pos: Pos, to_pos: Pos) -> Optional[str]:
    dx = to_pos.x - from_pos.x
    dy = to_pos.y - from_pos.y
    if dx == 0 and dy == -1:
        return "up"
    if dx == 0 and dy == 1:
        return "down"
    if dx == -1 and dy == 0:
        return "left"
    if dx == 1 and dy == 0:
        return "right"
    return None


def _compute_shape(pos: Pos, inward: Pos, outward: Optional[Pos]) -> str:
    """Straight/corner shape token from a segment's up-to-two neighbors.

    Names match the six-sprite convention this system was designed against
    (``horizontal``/``vertical`` plus the four ``corner_<a>_<b>``
    combinations), but nothing here is game-specific — any pack can reuse
    these tokens or point ``segmentKindTemplate`` at kinds using its own
    names.
    """
    dir_in = _direction_between(pos, inward)
    if outward is None:
        return "horizontal" if dir_in in ("left", "right") else "vertical"
    dir_out = _direction_between(pos, outward)
    if dir_in is None or dir_out is None:
        return "horizontal"
    pair = {dir_in, dir_out}
    if pair == {"up", "down"}:
        return "vertical"
    if pair == {"left", "right"}:
        return "horizontal"
    if pair == {"up", "right"}:
        return "corner_up_right"
    if pair == {"right", "down"}:
        return "corner_right_down"
    if pair == {"down", "left"}:
        return "corner_down_left"
    if pair == {"left", "up"}:
        return "corner_left_up"
    return "horizontal"


def _render_kind(template: str, color: str, shape: str) -> str:
    return template.replace("{color}", color).replace("{shape}", shape)


def _is_adjacent(a: Pos, b: Pos) -> bool:
    return abs(a.x - b.x) + abs(a.y - b.y) == 1


class TrailingBodySystem(GameSystem):
    def __init__(self, sys_id: str, config: Optional[dict] = None):
        super().__init__(sys_id, "trailing_body")
        self._config = config

    def _config_for(self, game: GameDef) -> dict:
        if self._config is not None:
            return self._config
        return game.system_config(self.id)

    @property
    def _prev_pos_key(self) -> str:
        return f"_trailingBody_{self.id}_prevPos"

    @property
    def _segments_key(self) -> str:
        return f"_trailingBody_{self.id}_segments"

    def _resolve_mover_position(
        self, state: GameState, game: GameDef, config: dict
    ) -> Optional[Pos]:
        mover_tag = str(_cfg(config, "moverTag", "avatar"))
        if mover_tag == "avatar":
            return state.avatar.position if state.avatar.enabled else None
        mover_layer = str(_cfg(config, "moverLayer", "objects"))
        layer = state.board.layers.get(mover_layer)
        if layer is None:
            return None
        for pos, entity in layer.entries():
            if game.has_tag(entity.kind, mover_tag):
                return pos
        return None

    def execute_load_settle(self, state: GameState, game: GameDef) -> list[dict]:
        config = self._config_for(game)
        mover_pos = self._resolve_mover_position(state, game, config)
        if mover_pos is None:
            return []
        state.variables[self._prev_pos_key] = [mover_pos.x, mover_pos.y]

        length_var = config.get("lengthVariable")
        fresh_l = _read_int(state.variables.get(length_var)) if length_var else 0
        if fresh_l <= 0:
            state.variables[self._segments_key] = []
            return []

        # Best-effort backfill: a level that starts the mover already
        # carrying cargo has no real trail to source positions from, so
        # every backfilled segment is stacked on the mover's own starting
        # cell using a fixed defaultSegmentKind (not the color+shape
        # template, since there is no growth event to source a color from).
        # Documented limitation — Hitch never uses this path, since the
        # truck always starts empty.
        default_kind = config.get("defaultSegmentKind")
        segments: list[_Segment] = []
        if default_kind is not None:
            segments = [
                _Segment(mover_pos, None, str(default_kind)) for _ in range(fresh_l)
            ]
            body_layer = str(_cfg(config, "bodyLayer", "tail"))
            for seg in segments:
                state.board.set_entity(body_layer, seg.position, Entity(seg.literal_kind))
        state.variables[self._segments_key] = [seg.to_json() for seg in segments]
        return []

    def execute_movement_resolution(self, state: GameState, game: GameDef) -> list[dict]:
        config = self._config_for(game)
        mover_pos = self._resolve_mover_position(state, game, config)
        if mover_pos is None:
            return []

        prev_pos_raw = state.variables.get(self._prev_pos_key)
        prev_pos = Pos.from_json(prev_pos_raw) if prev_pos_raw is not None else mover_pos

        if mover_pos == prev_pos:
            # Mover didn't move this turn (e.g. a non-movement action, or a
            # blocked move) — the body doesn't move either.
            state.variables[self._prev_pos_key] = [mover_pos.x, mover_pos.y]
            return []

        body_layer = str(_cfg(config, "bodyLayer", "tail"))
        segments_raw = state.variables.get(self._segments_key) or []
        old_segments = [_Segment.from_json(e) for e in segments_raw]

        # Structural growth detection — see module docstring for why this
        # can't be "did lengthVariable increase since last turn".
        growth_layer = config.get("growthKindSource")
        growth_tag = str(_cfg(config, "growthTriggerTag", "pickup"))
        color_param = str(_cfg(config, "growthColorParam", "color"))
        growth_entity: Optional[Entity] = None
        if growth_layer:
            candidate = state.board.get_entity(str(growth_layer), mover_pos)
            if candidate is not None and game.has_tag(candidate.kind, growth_tag):
                growth_entity = candidate
        is_growth = growth_entity is not None

        # Positions always shift: prepend the cell the mover just left, and
        # keep every old position at its own index — the body doesn't slide
        # on a growth turn, so nothing is dropped; on an ordinary turn, the
        # last (farthest) position falls off the end.
        old_positions = [seg.position for seg in old_segments]
        target_len = len(old_segments) + 1 if is_growth else len(old_segments)
        new_positions = [prev_pos, *old_positions][:target_len]

        # Appearances (color/literal_kind) shift independently of position:
        # on an ordinary turn each existing segment's fixed appearance moves
        # forward into the cell the segment ahead of it just vacated (a real
        # train's cars each pull into the spot the car ahead just left) — so
        # the appearance list itself is untouched, just re-paired with the
        # new, shifted position list. On a growth turn a brand new
        # appearance is appended after every existing one, the way a new
        # car couples onto the back of a train: the earliest-picked-up
        # cargo stays closest to the mover, and each later pickup joins
        # further back.
        if is_growth:
            color = growth_entity.param(color_param) or growth_entity.kind
            appearance_source = [*old_segments, _Segment(mover_pos, str(color))]
        else:
            appearance_source = old_segments
        appearances = appearance_source[:target_len]

        length = min(len(new_positions), len(appearances))
        raw_segments = [
            _Segment(new_positions[i], appearances[i].color, appearances[i].literal_kind)
            for i in range(length)
        ]

        # Unloading: a segment that lands exactly on a matching-color
        # unloader tile this turn is spliced out of the chain — not freed
        # off the tail end the way the farthest segment naturally is, but
        # removed from wherever it sits, with every segment behind it
        # pulled forward into the gap so the chain stays contiguous ("Red
        # and Blue become connected directly" — see
        # docs/dsl/04_systems.md §2.26). Opt-in via unloadLayer; a pack that
        # never sets it pays nothing here and raw_segments passes through
        # unchanged.
        #
        # original_index_of[i] tracks, for each surviving segment, its
        # index in old_segments — the tile_moved loop below needs this to
        # find each segment's *own* old position, since a pulled-forward
        # segment's slot in raw_segments no longer matches its slot in
        # old_segments once something ahead of it has been spliced out.
        unload_layer = config.get("unloadLayer")
        new_segments = raw_segments
        original_index_of = list(range(len(raw_segments)))
        unload_events: list[dict] = []
        if unload_layer:
            unload_tag = str(_cfg(config, "unloadTag", "unloader"))
            unload_color_param = str(_cfg(config, "unloadColorParam", "color"))
            layer = state.board.layers.get(str(unload_layer))
            kept: list[_Segment] = []
            kept_original_index: list[int] = []
            for i, seg in enumerate(raw_segments):
                unloader = layer.get(seg.position) if layer else None
                matches = (
                    unloader is not None
                    and game.has_tag(unloader.kind, unload_tag)
                    and unloader.param(unload_color_param) == seg.color
                )
                if matches:
                    unload_events.append({
                        "type": "body_segment_unloaded",
                        "position": seg.position,
                        "color": seg.color,
                    })
                else:
                    kept.append(seg)
                    kept_original_index.append(i)
            if len(kept) != len(raw_segments):
                new_segments = [
                    _Segment(new_positions[k], kept[k].color, kept[k].literal_kind)
                    for k in range(len(kept))
                ]
                original_index_of = kept_original_index

        # Reconcile against lengthVariable — only when this wasn't a
        # structural growth turn. On the growth turn itself, lengthVariable
        # is still the pre-increment value (rules haven't run yet this
        # turn), so comparing against it here would immediately undo the
        # growth just computed above. By next turn lengthVariable has caught
        # up and this is a no-op.
        if not is_growth:
            length_var = config.get("lengthVariable")
            if length_var:
                fresh_l = _read_int(state.variables.get(length_var))
                if fresh_l > len(new_segments):
                    default_kind = config.get("defaultSegmentKind")
                    if default_kind is not None:
                        anchor = new_segments[-1].position if new_segments else prev_pos
                        while len(new_segments) < fresh_l:
                            new_segments.append(_Segment(anchor, None, str(default_kind)))
                            original_index_of.append(-1)  # no history to animate from
                elif fresh_l < len(new_segments):
                    new_segments = new_segments[:fresh_l]
                    original_index_of = original_index_of[:fresh_l]

        events: list[dict] = list(unload_events)
        old_pos_set = set(old_positions)
        new_pos_set = {seg.position for seg in new_segments}
        # Iterate the ordered lists (not raw set difference) so event order is
        # deterministic and matches the Dart engine's LinkedHashSet-derived order.
        seen_added: set = set()
        added_positions = []
        for seg in new_segments:
            if seg.position not in old_pos_set and seg.position not in seen_added:
                seen_added.add(seg.position)
                added_positions.append(seg.position)
        seen_freed: set = set()
        freed_positions = []
        for pos in old_positions:
            if pos not in new_pos_set and pos not in seen_freed:
                seen_freed.add(pos)
                freed_positions.append(pos)

        if is_growth:
            events.append({
                "type": "body_grown",
                "position": prev_pos,
                "color": new_segments[0].color if new_segments else None,
                "length": len(new_segments),
            })
        for pos in added_positions:
            seg = next(s for s in new_segments if s.position == pos)
            events.append({"type": "body_segment_added", "position": pos, "color": seg.color})
        for pos in freed_positions:
            state.board.set_entity(body_layer, pos, None)
            events.append({"type": "body_segment_freed", "position": pos})

        # Rewrite every current segment's entity — even one whose position
        # didn't change may need a new shape, since its neighbors moved.
        #
        # A *persisting* appearance (original_index_of[i] < len(old_segments),
        # i.e. not a brand-new segment coupling on this turn, and not a
        # lengthVariable-padded placeholder) moved exactly one cell this turn
        # — from its own old position to its new one — by construction (see
        # the module docstring), UNLESS something ahead of it in the chain
        # was spliced out by an unloader this same turn, in which case it
        # was pulled forward more than one cell to close the gap — a hop
        # this system doesn't try to animate as a slide (there is no single
        # legal one-cell path for the renderer to walk), so it is left to
        # appear at rest, same as a brand-new segment already does.
        # Emitting tile_moved for the ordinary case lets the renderer's
        # generic entity-glide pipeline carry these segments in lockstep
        # with the avatar's own step animation instead of snapping — the
        # presentation layer decides whether to actually play them
        # concurrently, this system only has to describe the motion.
        template = str(_cfg(config, "segmentKindTemplate", "segment"))
        for i, seg in enumerate(new_segments):
            inward = mover_pos if i == 0 else new_segments[i - 1].position
            outward = None if i == len(new_segments) - 1 else new_segments[i + 1].position
            shape = _compute_shape(seg.position, inward, outward)
            kind = seg.literal_kind or _render_kind(template, seg.color or "", shape)
            original_index = original_index_of[i] if i < len(original_index_of) else -1
            if 0 <= original_index < len(old_segments):
                from_pos = old_segments[original_index].position
                if from_pos != seg.position and _is_adjacent(from_pos, seg.position):
                    events.append(ev.tile_moved(from_pos, seg.position, kind, layer=body_layer))
            state.board.set_entity(body_layer, seg.position, Entity(kind))

        state.variables[self._segments_key] = [seg.to_json() for seg in new_segments]
        state.variables[self._prev_pos_key] = [mover_pos.x, mover_pos.y]

        return events
