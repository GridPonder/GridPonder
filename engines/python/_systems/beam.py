"""BeamSystem — see docs/dsl/04_systems.md.

Lets the player tap-select a source entity, aim it with a directional action,
and — every turn, unconditionally, like `sonar` — traces a ray from each
aimed source across the board: straight through empty cells, bent at cells
whose kind is a key in `reflectors` (via a plain incoming-direction ->
outgoing-direction map, so any reflector shape a game defines needs only its
own map entry), stopped by a blocking-tagged cell or the board edge, and
stopped — with the configured hit variable set — at a target-tagged cell. A
`hazardTags`-tagged cell also stops the trace, setting `hazardVariable`
instead of `hitVariable`; pairing that variable with a `variable_threshold`
`loseCondition` is what turns touching it into an immediate loss, so the
hazard itself is just another stop condition here, not a lose-condition
concept of its own.

The summed length of every hitting source's path (in cells, each source's own
cell excluded) is optionally published too, so a level can cap it with an
`lte` `variable_threshold` goal — a maximum-path-length budget that forces
the shorter of several otherwise-valid routes. Summing (rather than
reporting only one source's length) is what keeps this meaningful once a
level has more than one source: the budget reads as "total beam material
spent," which reduces to plain path length for today's single-source levels.

Whether every reflector currently on the board actually lies on a traced path
is optionally published as well, via `allReflectorsUsedVariable` — 1 when no
placed reflector sits unvisited, 0 if at least one does. This is deliberately
about *placement*, not budget: a `budgetVariable` reaching zero only proves
every reflector was placed *somewhere*, which a player can satisfy by
dropping the leftovers on cells the beam never reaches. Checking placement
against the traced path is what actually forces a route that uses all of
them — pair with a `gte 1` `variable_threshold` goal (and, separately,
budget-exhaustion goals if a level also requires every reflector to have been
placed at all).

The path painted on `pathLayer` can be more than a uniform `pathKind`:
`segmentKindHorizontal`/`segmentKindVertical` pick a marker by axis for plain
traversed cells, `reflectorGlowKinds` (entity kind -> incoming direction ->
marker kind) for cells that bent the beam, `blockedKinds` (incoming direction
-> marker kind) for the cell that stopped it — each keyed by the direction
the beam was moving when it *entered* that cell, so a mirror or wall can show
which side the beam is hitting it from — and `hitTargetKind` for the cell
that completed a hit. Any cell without a matching override falls back to
`pathKind`, so a game that doesn't need directional art keeps working
unchanged.

A `splitters`-configured entity kind forks a single incoming beam into
several outgoing ones (entity kind -> incoming direction -> list of outgoing
directions), each continuing independently from that cell — so one emitter
can, via a single divider, ultimately reach more than one target. Checked
before `reflectors`, so a kind can't be both. `allTargetsHitVariable` is the
splitter-era counterpart to `allReflectorsUsedVariable`: 1 when every
target-tagged entity on `blockingLayers` was reached by some branch this
turn (any source, any branch), 0 if at least one wasn't — `hitVariable`
alone only means "something reached something," which stops distinguishing
outcomes once a level has more than one target.

Selection and firing are two different actions on purpose: selection also
records the tapped cell as a generic "last selected position" (independent of
whether it held a source), so another system — e.g. `terrain_edit`'s
`positionVariable` — can use the same tap to target a placement.

Firing accepts either a single parameterized `fireAction` (direction carried
in the action's own params — e.g. a keyboard/gamepad binding) or a set of
fixed-direction `fireActions` (one zero-param action id per direction,
defaulting to `fire_up`/`fire_down`/`fire_left`/`fire_right`) — the latter is
what the reference app's control buttons need, since they only render
zero-param actions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .._models import Pos, GameState, Entity, is_cardinal
from .._game_def import GameDef
from ._base import GameSystem, config_list


@dataclass(frozen=True)
class _PathCell:
    """One traced cell: where it is, the direction the beam was moving when
    it entered (`incoming_direction`), and what it is (`role`: "segment" for
    a plain floor cell, "reflector", "blocked", or "target", with
    `entity_kind` set for the latter three)."""
    position: Pos
    incoming_direction: str
    role: str
    entity_kind: Optional[str]


def _parse_pos(raw) -> Optional[Pos]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None
    try:
        x, y = raw[0], raw[1]
        if not (isinstance(x, (int, float)) and isinstance(y, (int, float))):
            return None
        return Pos(int(x), int(y))
    except (TypeError, ValueError, OverflowError):
        return None


def _reflector_map(raw) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    if isinstance(raw, dict):
        for kind, dir_map in raw.items():
            if isinstance(dir_map, dict):
                result[str(kind)] = {str(k): str(v) for k, v in dir_map.items()}
    return result


def _splitter_map(raw) -> dict[str, dict[str, list[str]]]:
    """Same shape as `_reflector_map` but each incoming direction maps to a
    *list* of outgoing directions — a splitter kind absent from the map, or
    with no entry for the incoming direction, is not a splitter for that
    approach."""
    result: dict[str, dict[str, list[str]]] = {}
    if isinstance(raw, dict):
        for kind, dir_map in raw.items():
            if isinstance(dir_map, dict):
                result[str(kind)] = {
                    str(k): [str(d) for d in v] if isinstance(v, list) else []
                    for k, v in dir_map.items()
                }
    return result


_DEFAULT_FIRE_ACTIONS = {
    "fire_up": "up",
    "fire_down": "down",
    "fire_left": "left",
    "fire_right": "right",
}


def _fire_actions_map(raw) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    return _DEFAULT_FIRE_ACTIONS


class BeamSystem(GameSystem):
    def __init__(self, sys_id: str, config: dict | None = None):
        super().__init__(sys_id, "beam")
        self._config = config

    def _cfg(self, game: GameDef) -> dict:
        return self._config if self._config is not None else game.system_config(self.id)

    def execute_action_resolution(
        self, action: dict, state: GameState, game: GameDef
    ) -> list[dict]:
        cfg = self._cfg(game)
        select_action = cfg.get("selectAction", "tap_cell")
        action_id = action.get("actionId")

        if action_id == select_action:
            return self._handle_select(action, state, game, cfg)

        fire_action = cfg.get("fireAction")
        if fire_action is not None and action_id == fire_action:
            direction = action.get("params", {}).get("direction")
            if isinstance(direction, str):
                return self._handle_fire(direction, state, game, cfg)
            return []

        fire_actions = _fire_actions_map(cfg.get("fireActions"))
        mapped_direction = fire_actions.get(action_id)
        if mapped_direction is not None:
            return self._handle_fire(mapped_direction, state, game, cfg)
        return []

    def _handle_select(
        self, action: dict, state: GameState, game: GameDef, cfg: dict
    ) -> list[dict]:
        pos = _parse_pos(action.get("params", {}).get("position"))
        if pos is None or not state.board.is_in_bounds(pos):
            return []

        selected_cell_var = cfg.get("selectedCellVariable", "selectedCell")
        state.variables[selected_cell_var] = [pos.x, pos.y]

        source_layer = cfg.get("sourceLayer", "objects")
        source_tags = config_list(cfg, "sourceTags", ["beam_source"])
        entity = state.board.get_entity(source_layer, pos)
        if entity is None or not any(game.has_tag(entity.kind, t) for t in source_tags):
            return []

        selected_source_var = cfg.get("selectedSourceVariable", "selectedSource")
        state.variables[selected_source_var] = [pos.x, pos.y]
        return [{"type": "actor_selected", "position": pos, "kind": entity.kind}]

    def _handle_fire(
        self, direction: str, state: GameState, game: GameDef, cfg: dict
    ) -> list[dict]:
        if not is_cardinal(direction):
            return []

        selected_source_var = cfg.get("selectedSourceVariable", "selectedSource")
        src_pos = _parse_pos(state.variables.get(selected_source_var))
        if src_pos is None:
            return []

        source_layer = cfg.get("sourceLayer", "objects")
        entity = state.board.get_entity(source_layer, src_pos)
        if entity is None:
            return []

        facing_param = cfg.get("facingParam", "facing")
        new_params = dict(entity.params)
        new_params[facing_param] = direction
        state.board.set_entity(source_layer, src_pos, Entity(entity.kind, new_params))
        return [{"type": "beam_aimed", "position": src_pos, "direction": direction}]

    def execute_npc_resolution(self, state: GameState, game: GameDef) -> list[dict]:
        cfg = self._cfg(game)
        source_layer = cfg.get("sourceLayer", "objects")
        source_tags = config_list(cfg, "sourceTags", ["beam_source"])
        facing_param = cfg.get("facingParam", "facing")
        blocking_layers = config_list(cfg, "blockingLayers", ["ground"])
        blocking_tags = config_list(cfg, "blockingTags", ["solid"])
        target_tags = config_list(cfg, "targetTags", ["goal_target"])
        hazard_tags = config_list(cfg, "hazardTags", [])
        reflectors = _reflector_map(cfg.get("reflectors"))
        splitters = _splitter_map(cfg.get("splitters"))
        hit_variable = cfg.get("hitVariable")
        hazard_variable = cfg.get("hazardVariable")
        path_length_variable = cfg.get("pathLengthVariable")
        all_reflectors_used_variable = cfg.get("allReflectorsUsedVariable")
        all_targets_hit_variable = cfg.get("allTargetsHitVariable")
        path_layer = cfg.get("pathLayer", "markers")
        path_kind = cfg.get("pathKind")
        segment_kind_h = cfg.get("segmentKindHorizontal")
        segment_kind_v = cfg.get("segmentKindVertical")
        reflector_glow_kinds = _reflector_map(cfg.get("reflectorGlowKinds"))
        splitter_glow_kinds = _reflector_map(cfg.get("splitterGlowKinds"))
        blocked_kinds = cfg.get("blockedKinds")
        blocked_kinds = {str(k): str(v) for k, v in blocked_kinds.items()} if isinstance(blocked_kinds, dict) else {}
        hit_target_kind = cfg.get("hitTargetKind")
        hazard_kind = cfg.get("hazardKind")
        max_steps = int(cfg.get("maxSteps", 200))

        # Every kind any cell could be marked with this turn — a superset
        # used to clear last turn's trace regardless of which specific kind
        # a cell had.
        all_marker_kinds = {path_kind, segment_kind_h, segment_kind_v, hit_target_kind, hazard_kind, *blocked_kinds.values()}
        for dir_map in reflector_glow_kinds.values():
            all_marker_kinds.update(dir_map.values())
        for dir_map in splitter_glow_kinds.values():
            all_marker_kinds.update(dir_map.values())
        all_marker_kinds.discard(None)
        if all_marker_kinds:
            layer = state.board.layers.get(path_layer)
            if layer is not None:
                for pos, entity in list(layer.entries()):
                    if entity.kind in all_marker_kinds:
                        state.board.set_entity(path_layer, pos, None)

        source_layer_obj = state.board.layers.get(source_layer)
        if source_layer_obj is None:
            return []

        events: list[dict] = []
        any_hit = False
        any_hazard = False
        # Summed rather than "first hit's length" so a future multi-source
        # game reads naturally as "total beam material spent" — a per-source
        # budget reduces to plain path length when there is exactly one
        # source.
        total_hit_length = 0
        visited_cells: set[Pos] = set()
        hit_target_positions: set[Pos] = set()

        for src_pos, entity in list(source_layer_obj.entries()):
            if not any(game.has_tag(entity.kind, t) for t in source_tags):
                continue
            facing = entity.param(facing_param)
            if not isinstance(facing, str) or not is_cardinal(facing):
                continue

            # Almost always one branch; more than one only when the ray
            # passed through a `splitters` cell and forked.
            branches = self._trace(
                src_pos, facing, state, game,
                blocking_layers, blocking_tags, target_tags, hazard_tags,
                reflectors, splitters, max_steps,
            )

            for cells, hit in branches:
                path = [c.position for c in cells]

                for cell in cells:
                    kind = self._marker_kind_for(
                        cell, path_kind, segment_kind_h, segment_kind_v,
                        reflector_glow_kinds, splitter_glow_kinds, blocked_kinds,
                        hit_target_kind, hazard_kind,
                    )
                    if kind is not None:
                        state.board.set_entity(path_layer, cell.position, Entity(kind))
                        # Emitted in trace order (source to endpoint) purely so a
                        # renderer can play the path back cell-by-cell instead of
                        # the board simply appearing fully painted — the state
                        # above is already final.
                        events.append({
                            "type": "beam_cell_revealed",
                            "position": cell.position,
                            "layer": path_layer,
                            "kind": kind,
                        })
                visited_cells.update(path)
                if hit:
                    any_hit = True
                    total_hit_length += len(path)
                    hit_target_positions.add(cells[-1].position)
                if any(c.role == "hazard" for c in cells):
                    any_hazard = True
                events.append({
                    "type": "beam_traced",
                    "position": src_pos,
                    "path": [[p.x, p.y] for p in path],
                    "hit": hit,
                })

        if hit_variable is not None:
            state.variables[hit_variable] = 1 if any_hit else 0
        if hazard_variable is not None:
            state.variables[hazard_variable] = 1 if any_hazard else 0
        if path_length_variable is not None:
            state.variables[path_length_variable] = total_hit_length
        if all_reflectors_used_variable is not None:
            all_used = True
            for layer_id in blocking_layers:
                layer = state.board.layers.get(layer_id)
                if layer is None:
                    continue
                for pos, cell_entity in layer.entries():
                    if cell_entity.kind not in reflectors and cell_entity.kind not in splitters:
                        continue
                    if pos not in visited_cells:
                        all_used = False
                        break
                if not all_used:
                    break
            state.variables[all_reflectors_used_variable] = 1 if all_used else 0
        if all_targets_hit_variable is not None:
            all_targets_hit = True
            for layer_id in blocking_layers:
                layer = state.board.layers.get(layer_id)
                if layer is None:
                    continue
                for pos, cell_entity in layer.entries():
                    if not any(game.has_tag(cell_entity.kind, t) for t in target_tags):
                        continue
                    if pos not in hit_target_positions:
                        all_targets_hit = False
                        break
                if not all_targets_hit:
                    break
            state.variables[all_targets_hit_variable] = 1 if all_targets_hit else 0

        return events

    def _trace(
        self,
        source: Pos,
        direction: str,
        state: GameState,
        game: GameDef,
        blocking_layers: list[str],
        blocking_tags: list[str],
        target_tags: list[str],
        hazard_tags: list[str],
        reflectors: dict[str, dict[str, str]],
        splitters: dict[str, dict[str, list[str]]],
        max_steps: int,
    ) -> list[tuple[list[_PathCell], bool]]:
        """Traces from `source` in `direction`, returning one (cells, hit)
        pair per terminal branch. Almost always a single-element list — it
        only grows past one when the ray passes through a `splitters`
        cell, which forks the single incoming beam into several outgoing
        ones. Each returned branch carries the full path from the source,
        prefix included, so branches replay independently rather than
        sharing a partial list.
        """
        return self._trace_segment(
            source, direction, [], state, game,
            blocking_layers, blocking_tags, target_tags, hazard_tags,
            reflectors, splitters, max_steps,
        )

    def _trace_segment(
        self,
        source: Pos,
        direction: str,
        prefix: list[_PathCell],
        state: GameState,
        game: GameDef,
        blocking_layers: list[str],
        blocking_tags: list[str],
        target_tags: list[str],
        hazard_tags: list[str],
        reflectors: dict[str, dict[str, str]],
        splitters: dict[str, dict[str, list[str]]],
        max_steps: int,
    ) -> list[tuple[list[_PathCell], bool]]:
        pos = source
        cells: list[_PathCell] = list(prefix)

        for _ in range(max_steps):
            incoming = direction
            pos = pos.moved(direction)
            if not state.board.is_in_bounds(pos):
                break

            reflect_to = None
            split_to: Optional[list[str]] = None
            blocked = False
            hit_target = False
            hit_hazard = False
            role = "segment"
            entity_kind: Optional[str] = None
            for layer_id in blocking_layers:
                cell_entity = state.board.get_entity(layer_id, pos)
                if cell_entity is None:
                    continue
                if any(game.has_tag(cell_entity.kind, t) for t in target_tags):
                    hit_target = True
                    role = "target"
                    entity_kind = cell_entity.kind
                    break
                if any(game.has_tag(cell_entity.kind, t) for t in hazard_tags):
                    hit_hazard = True
                    role = "hazard"
                    entity_kind = cell_entity.kind
                    break
                split_map = splitters.get(cell_entity.kind)
                if split_map is not None:
                    split_to = split_map.get(direction)
                    role = "splitter"
                    entity_kind = cell_entity.kind
                    break
                reflect_map = reflectors.get(cell_entity.kind)
                if reflect_map is not None:
                    reflect_to = reflect_map.get(direction)
                    role = "reflector"
                    entity_kind = cell_entity.kind
                    break
                if any(game.has_tag(cell_entity.kind, t) for t in blocking_tags):
                    blocked = True
                    role = "blocked"
                    entity_kind = cell_entity.kind
                    break

            cells.append(_PathCell(pos, incoming, role, entity_kind))
            if hit_target:
                return [(cells, True)]
            if hit_hazard:
                break
            if blocked:
                break
            if split_to:
                branches: list[tuple[list[_PathCell], bool]] = []
                for dir_str in split_to:
                    if not is_cardinal(dir_str):
                        branches.append((cells, False))
                        continue
                    branches.extend(self._trace_segment(
                        pos, dir_str, cells, state, game,
                        blocking_layers, blocking_tags, target_tags, hazard_tags,
                        reflectors, splitters, max_steps,
                    ))
                return branches
            if reflect_to is not None:
                if not is_cardinal(reflect_to):
                    break
                direction = reflect_to
                continue

        return [(cells, False)]

    @staticmethod
    def _marker_kind_for(
        cell: _PathCell,
        path_kind: Optional[str],
        segment_kind_h: Optional[str],
        segment_kind_v: Optional[str],
        reflector_glow_kinds: dict[str, dict[str, str]],
        splitter_glow_kinds: dict[str, dict[str, str]],
        blocked_kinds: dict[str, str],
        hit_target_kind: Optional[str],
        hazard_kind: Optional[str],
    ) -> Optional[str]:
        """Resolves which marker kind (if any) to paint at `cell`. Reflector
        and blocked cells prefer a kind keyed by the direction the beam was
        moving when it entered them; a plain traversed cell prefers
        `segment_kind_h`/`segment_kind_v` based on that same direction's
        axis; the target-hit cell prefers `hit_target_kind`. Anything not
        matched falls back to the uniform `path_kind`, and finally to no
        marker at all.

        A hazard cell is the one exception to that fallback: it resolves to
        `hazard_kind` (often left unset) and never falls back to `path_kind`,
        since the run ends the instant the beam reaches it — the hazard
        entity's own sprite should stay exactly as it looks the rest of the
        time, not get redecorated with a beam-path marker no one has time to
        see before losing.
        """
        d = cell.incoming_direction
        if cell.role == "reflector":
            k = reflector_glow_kinds.get(cell.entity_kind or "", {}).get(d)
            if k is not None:
                return k
        elif cell.role == "splitter":
            k = splitter_glow_kinds.get(cell.entity_kind or "", {}).get(d)
            if k is not None:
                return k
        elif cell.role == "blocked":
            k = blocked_kinds.get(d)
            if k is not None:
                return k
        elif cell.role == "target":
            if hit_target_kind is not None:
                return hit_target_kind
        elif cell.role == "hazard":
            return hazard_kind
        elif cell.role == "segment":
            horizontal = d in ("left", "right")
            k = segment_kind_h if horizontal else segment_kind_v
            if k is not None:
                return k
        return path_kind
