"""
Generic engine adapter for the GridPonder puzzle solver.

Wraps the Python TurnEngine (engines/python/) to provide the standard solver
interface (load / apply / ACTIONS / can_prune) for any game pack.  Any game
with a game.json + level JSON can be solved without a hand-written simulator.

State representation
--------------------
BFS/DFS/A* need hashable states.  ``EngineState`` wraps a ``GameState`` and
delegates ``__hash__`` / ``__eq__`` to ``GameState.to_key()``.  The underlying
``GameState`` is never mutated after construction; a fresh copy is made for
every ``apply`` call.

Action strings
--------------
Actions are flattened to strings:

  * Actions with a ``direction`` param → ``"{action_id}_{direction}"``
    (e.g. ``"move_up"``, ``"diagonal_swap_up_right"``)
  * Actions with ``position`` and ``direction`` params →
    ``"{action_id}_{x}_{y}_{direction}"`` (e.g. ``"move_2_3_left"``)
  * Actions with no params → ``"{action_id}"``
    (e.g. ``"flood_red"``, ``"rotate"``)

Usage
-----
::

    from engine_adapter import load, apply, can_prune, gold_path_actions

    pack_dir = Path("../../packs/diagonal_swipes")
    level_json = json.loads((pack_dir / "levels/ds_001.json").read_text())
    initial, info = load(level_json, pack_dir)

    for action in info.ACTIONS:
        new_state, won, events = apply(initial, action, info)
"""

from __future__ import annotations

from collections import deque
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# Make engines/ importable when running from tools/solver/
_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engines.python._game_def import GameDef
from engines.python._models import GameState, Pos
from engines.python._turn_engine import TurnEngine
from engines.python.loader import load_pack

# ---------------------------------------------------------------------------
# EngineState — hashable wrapper around GameState
# ---------------------------------------------------------------------------

class EngineState:
    """
    Hashable snapshot of a ``GameState``.

    Immutable from the caller's perspective: ``apply`` always returns a fresh
    ``EngineState`` and never mutates an existing one.
    """

    __slots__ = ("_state", "_key", "_hash")

    def __init__(self, state: GameState) -> None:
        self._state = state
        self._key: Optional[tuple] = None
        self._hash: Optional[int] = None

    def _get_key(self) -> tuple:
        if self._key is None:
            self._key = self._state.to_key()
        return self._key

    def __hash__(self) -> int:
        if self._hash is None:
            self._hash = hash(self._get_key())
        return self._hash

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EngineState):
            return NotImplemented
        return self._get_key() == other._get_key()

    @property
    def game_state(self) -> GameState:
        return self._state


# ---------------------------------------------------------------------------
# EngineInfo — static level data (does not change during search)
# ---------------------------------------------------------------------------

@dataclass
class EngineInfo:
    """Static context passed to every ``apply`` call."""
    game: GameDef
    level_def: dict
    pack_dir: Path
    ACTIONS: list[str]        # flat action strings valid for this game
    level_id: Optional[str] = None
    width: int = 0
    height: int = 0


# ---------------------------------------------------------------------------
# Action helpers
# ---------------------------------------------------------------------------

def _build_actions(game: GameDef, width: int = 0, height: int = 0) -> list[str]:
    """Build the flat ACTIONS list from the game definition."""
    result: list[str] = []
    for action_def in game.actions:
        aid = action_def["id"]
        params = action_def.get("params", {})
        if "position" in params and "direction" in params:
            dirs = params["direction"].get(
                "values", ["up", "down", "left", "right"])
            for y in range(height):
                for x in range(width):
                    for direction in dirs:
                        result.append(f"{aid}_{x}_{y}_{direction}")
        elif "direction" in params:
            dirs = params["direction"].get("values", ["up", "down", "left", "right"])
            for d in dirs:
                result.append(f"{aid}_{d}")
        elif "position" in params:
            for y in range(height):
                for x in range(width):
                    result.append(f"{aid}_{x}_{y}")
        else:
            result.append(aid)
    return result


def _parse_action(action_str: str, game: GameDef) -> tuple[str, dict]:
    """Convert a flat action string back to ``(action_id, params)``."""
    for action_def in game.actions:
        aid = action_def["id"]
        params = action_def.get("params", {})
        if "position" in params and "direction" in params:
            prefix = f"{aid}_"
            if not action_str.startswith(prefix):
                continue
            rest = action_str[len(prefix):]
            dirs = params["direction"].get(
                "values", ["up", "down", "left", "right"])
            for direction in dirs:
                suffix = f"_{direction}"
                if not rest.endswith(suffix):
                    continue
                position = rest[:-len(suffix)].split("_")
                if len(position) == 2:
                    return aid, {
                        "position": [int(position[0]), int(position[1])],
                        "direction": direction,
                    }
        elif "direction" in params:
            dirs = params["direction"].get("values", ["up", "down", "left", "right"])
            for d in dirs:
                if action_str == f"{aid}_{d}":
                    return aid, {"direction": d}
        elif "position" in params and action_str.startswith(f"{aid}_"):
            rest = action_str[len(aid) + 1:].split("_")
            if len(rest) == 2:
                return aid, {"position": [int(rest[0]), int(rest[1])]}
        elif action_str == aid:
            return aid, {}
    raise ValueError(f"Unknown action string: {action_str!r}")


# ---------------------------------------------------------------------------
# Solver interface
# ---------------------------------------------------------------------------

def load(level_json: dict, pack_dir: str | Path) -> tuple[EngineState, EngineInfo]:
    """
    Load a level for generic engine-backed solving.

    Returns
    -------
    initial : EngineState
        The starting state.
    info : EngineInfo
        Static context (game def, level def, ACTIONS list, …).
    """
    pack_dir = Path(pack_dir)
    game, levels = load_pack(pack_dir)

    level_id = level_json.get("id")
    board = level_json.get("board", {})
    cols, rows = board.get("size", [0, 0])

    actions = _build_actions(game, cols, rows)

    info = EngineInfo(
        game=game,
        level_def=level_json,
        pack_dir=pack_dir,
        ACTIONS=actions,
        level_id=level_id,
        width=cols,
        height=rows,
    )

    # Build the initial GameState via TurnEngine's board parser
    engine = TurnEngine(game, level_json)
    initial = EngineState(engine.state.copy())
    return initial, info


def apply(
    state: EngineState,
    action_str: str,
    info: EngineInfo,
) -> tuple[EngineState, bool, list[dict]]:
    """
    Apply one action to *state*.

    Returns ``(new_state, won, events)``.  If the action is vetoed (move
    blocked, etc.) the state is unchanged and ``won`` is False.
    """
    action_id, params = _parse_action(action_str, info.game)

    # Winning and losing states are terminal. The runtime UI stops dispatching
    # actions at that point; the generic solver must enforce the same boundary
    # when it replays states directly through the engine adapter.
    if state.game_state.is_won or state.game_state.is_lost:
        return state, state.game_state.is_won, []

    # Fast-path: bypass TurnEngine.__init__ (no board re-parsing)
    engine = object.__new__(TurnEngine)
    engine._game = info.game
    engine._level = info.level_def
    engine._initial_state = state._state   # for reset() — unused in apply
    engine._state = state._state.copy()
    engine._history = []

    result = engine.execute_turn(action_id, params, save_history=False)
    new_state = EngineState(engine._state)
    return new_state, result.is_won, result.events


def can_prune(
    state: EngineState,
    info: EngineInfo,
    depth: int,
    max_depth: int,
) -> bool:
    """Generic pruning — over-claim dead end for the ``balance`` goal.

    Any kingdom owning more than ``target`` can never rebalance (claims are
    irreversible), so the branch is dead.  Lets BFS/DFS (which don't consult
    the heuristic) prune these too.  Returns False for non-balance games.
    """
    cfg = _balance_goal(info)
    if cfg is None or not _balance_optimizations_supported(state, info, cfg):
        return False
    owners = cfg.get("owners", [])
    k = len(owners)
    if k == 0:
        return False
    claimable = _claimable_count(
        state, info, cfg.get("claimableLayer", "ground"), cfg.get("claimableKind", "empty")
    )
    if claimable % k != 0:
        return False
    target = claimable // k
    owned = _owned_counts(state, cfg.get("layer", "territory"), owners)
    if any(owned[o] > target for o in owners):
        return True

    indiv = _individual_system(info)
    if indiv is None:
        return False

    sys_cfg = indiv.get("config", {})
    claim = sys_cfg.get("claim", {})
    actor_to_owner = claim.get("map", {})
    if not actor_to_owner:
        return False

    remaining = _actor_budgets_remaining(state, sys_cfg)
    for actor_kind, owner_kind in actor_to_owner.items():
        if owner_kind not in owned:
            continue
        deficit = target - owned[owner_kind]
        if deficit > int(remaining.get(actor_kind, 0)):
            return True
        if deficit > 0 and not _actor_can_reach_enough_claims(
            state,
            info,
            actor_kind,
            int(remaining.get(actor_kind, 0)),
            deficit,
            actor_layer_id=sys_cfg.get("actorLayer", "actors"),
            ground_layer=cfg.get("claimableLayer", "ground"),
            claim_kind=cfg.get("claimableKind", "empty"),
            territory_layer=cfg.get("layer", "territory"),
        ):
            return True
    h = heuristic(state, info)
    if h == float("inf"):
        return True
    if depth + h > max_depth:
        return True
    return False


def _actor_can_reach_enough_claims(
    state: EngineState,
    info: EngineInfo,
    actor_kind: str,
    budget: int,
    deficit: int,
    actor_layer_id: str,
    ground_layer: str,
    claim_kind: str,
    territory_layer: str,
) -> bool:
    if budget < deficit:
        return False

    board = state._state.board
    actor_layer = board.layers.get(actor_layer_id)
    start = None
    if actor_layer is not None:
        for pos, entity in actor_layer.entries():
            if entity.kind == actor_kind:
                start = pos
                break
    if start is None:
        return False

    seen = {start}
    q = deque([(start, 0)])
    reachable_unclaimed = 0
    while q:
        pos, dist = q.popleft()
        if dist >= budget:
            continue
        for direction in ("up", "down", "left", "right"):
            target = pos.moved(direction)
            if target in seen:
                continue
            if not board.is_in_bounds(target):
                continue
            ground = board.get_entity(ground_layer, target)
            if ground is None or ground.kind != claim_kind:
                continue
            seen.add(target)
            if board.get_entity(territory_layer, target) is None:
                reachable_unclaimed += 1
                if reachable_unclaimed >= deficit:
                    return True
            q.append((target, dist + 1))
    return reachable_unclaimed >= deficit


def _balance_goal(info: EngineInfo) -> Optional[dict]:
    for g in info.level_def.get("goals", []):
        if g.get("type") == "balance":
            return g.get("config", {})
    return None


def _claimable_count(state: EngineState, info: EngineInfo, ground_layer: str, claim_kind: str) -> int:
    board = state._state.board
    count = 0
    for y in range(info.height):
        for x in range(info.width):
            entity = board.get_entity(ground_layer, Pos(x, y))
            if entity is not None and entity.kind == claim_kind:
                count += 1
    return count


def _owned_counts(state: EngineState, terr_layer: str, owners: list[str]) -> dict[str, int]:
    owned = {o: 0 for o in owners}
    layer = state._state.board.layers.get(terr_layer)
    if layer is not None:
        for _pos, entity in layer.entries():
            if entity.kind in owned:
                owned[entity.kind] += 1
    return owned


def _effective_game(info: EngineInfo) -> GameDef:
    overrides = info.level_def.get("systemOverrides")
    return info.game.with_system_overrides(overrides) if overrides else info.game


def _has_reactive_rules(info: EngineInfo) -> bool:
    """Whether actions can have effects beyond the configured systems."""
    return bool(info.game.rules or info.level_def.get("rules"))


def _individual_system(info: EngineInfo) -> Optional[dict]:
    """Return the enabled ``individual_actors`` system, if this level uses one."""
    for s in _effective_game(info).systems:
        if s["type"] == "individual_actors" and s.get("enabled", True):
            return s
    return None


def _coupled_system(info: EngineInfo) -> Optional[dict]:
    """Return the enabled ``coupled_actors`` system, if this level uses one."""
    for system in _effective_game(info).systems:
        if system["type"] == "coupled_actors" and system.get("enabled", True):
            return system
    return None


def _sliding_system(info: EngineInfo) -> Optional[dict]:
    """Return the enabled ``sliding_blocks`` system, if this level uses one."""
    for system in _effective_game(info).systems:
        if system["type"] == "sliding_blocks" and system.get("enabled", True):
            return system
    return None


def _balance_optimizations_supported(
    state: EngineState,
    info: EngineInfo,
    cfg: dict,
) -> bool:
    """Whether the balance pruning assumptions are all explicitly satisfied."""
    # Rules may alter territory, budgets, or actor positions after an event.
    # In that case the static reachability assumptions below are not sound.
    if _has_reactive_rules(info):
        return False

    owners = cfg.get("owners", [])
    if not owners or len(set(owners)) != len(owners):
        return False
    if not cfg.get("requireComplete", True) or not cfg.get("requireEqual", True):
        return False

    claimable_layer = cfg.get("claimableLayer")
    claimable_kind = cfg.get("claimableKind")
    if not isinstance(claimable_layer, str) or not isinstance(claimable_kind, str):
        return False

    individual = _individual_system(info)
    coupled = _coupled_system(info)
    if (individual is None) == (coupled is None):
        return False
    movement = individual or coupled
    sys_cfg = movement.get("config", {})
    if sys_cfg.get("groundLayer", "ground") != claimable_layer:
        return False
    claim = sys_cfg.get("claim", {})
    actor_to_owner = claim.get("map", {})
    if (
        not isinstance(actor_to_owner, dict)
        or set(actor_to_owner.values()) != set(owners)
        or len(set(actor_to_owner.values())) != len(actor_to_owner)
    ):
        return False
    if (claim.get("overwrite") or {}).get("mode", "never") != "never":
        return False

    actor_layer_id = sys_cfg.get("actorLayer", "actors")
    actor_layer = state._state.board.layers.get(actor_layer_id)
    if actor_layer is None:
        return False
    actor_counts = {kind: 0 for kind in actor_to_owner}
    for _pos, entity in actor_layer.entries():
        if entity.kind in actor_counts:
            actor_counts[entity.kind] += 1
    if any(count != 1 for count in actor_counts.values()):
        return False

    if individual is not None:
        budgets = sys_cfg.get("budgets")
        if not isinstance(budgets, dict) or not budgets:
            return False
        if any(kind not in budgets for kind in actor_to_owner):
            return False

    ground_layer = state._state.board.layers.get(claimable_layer)
    wall_tag = sys_cfg.get("wallTag", "solid")
    if ground_layer is None:
        return False
    for _pos, entity in ground_layer.entries():
        if entity.kind != claimable_kind and not info.game.has_tag(entity.kind, wall_tag):
            return False
    return True


def _actor_budgets_remaining(state: EngineState, sys_cfg: dict) -> dict[str, int]:
    budgets = sys_cfg.get("budgets", {})
    key = sys_cfg.get("budgetVariable", "actorMovesRemaining")
    current = state._state.variables.get(key)
    if isinstance(current, dict):
        return {kind: int(value) for kind, value in current.items()}
    return {kind: int(value) for kind, value in budgets.items()}


def _balance_target_and_owned(
    state: EngineState,
    info: EngineInfo,
    cfg: dict,
    owners: list[str],
) -> tuple[Optional[int], dict[str, int]]:
    claimable = _claimable_count(
        state,
        info,
        cfg.get("claimableLayer", "ground"),
        cfg.get("claimableKind", "empty"),
    )
    if claimable % len(owners) != 0:
        return None, {o: 0 for o in owners}
    target = claimable // len(owners)
    owned = _owned_counts(state, cfg.get("layer", "territory"), owners)
    return target, owned


def _coupled_balance_heuristic(
    owners: list[str],
    target: int,
    owned: dict[str, int],
) -> float:
    deficits = [target - owned[o] for o in owners]
    return float(max(deficits))


def _individual_balance_heuristic(
    state: EngineState,
    info: EngineInfo,
    cfg: dict,
    owners: list[str],
    target: int,
    owned: dict[str, int],
) -> float:
    deficits = [target - owned[o] for o in owners]
    lower = sum(deficits)
    indiv = _individual_system(info)
    if indiv is None:
        return float(lower)

    sys_cfg = indiv.get("config", {})
    claim = sys_cfg.get("claim", {})
    owner_to_actor = {owner: actor for actor, owner in claim.get("map", {}).items()}
    selected_key = sys_cfg.get("selectedVariable", "selectedActorKind")
    selected = state._state.variables.get(selected_key)

    actors_needing_work = 0
    first_claim_extra = 0
    for owner_kind in owners:
        deficit = target - owned[owner_kind]
        if deficit <= 0:
            continue
        actor_kind = owner_to_actor.get(owner_kind)
        if actor_kind is None:
            continue
        if actor_kind != selected:
            actors_needing_work += 1
        distance = _distance_to_nearest_unclaimed_claim(
            state,
            info,
            sys_cfg,
            actor_kind,
            territory_layer_id=cfg.get("layer", "territory"),
            claimable_kind=cfg.get("claimableKind", "empty"),
        )
        if distance is None:
            return float("inf")
        first_claim_extra += max(0, distance - 1)
    return float(lower + actors_needing_work + first_claim_extra)


def _distance_to_nearest_unclaimed_claim(
    state: EngineState,
    info: EngineInfo,
    sys_cfg: dict,
    actor_kind: str,
    territory_layer_id: str,
    claimable_kind: str,
) -> Optional[int]:
    board = state._state.board
    actor_layer_id = sys_cfg.get("actorLayer", "actors")
    ground_layer_id = sys_cfg.get("groundLayer", "ground")
    wall_tag = sys_cfg.get("wallTag", "solid")

    actor_layer = board.layers.get(actor_layer_id)
    start = None
    if actor_layer is not None:
        for pos, entity in actor_layer.entries():
            if entity.kind == actor_kind:
                start = pos
                break
    if start is None:
        return None

    seen = {start}
    q = deque([(start, 0)])
    while q:
        pos, dist = q.popleft()
        if dist > 0 and board.get_entity(territory_layer_id, pos) is None:
            return dist
        for direction in ("up", "down", "left", "right"):
            target = pos.moved(direction)
            if target in seen:
                continue
            if not board.is_in_bounds(target):
                continue
            ground = board.get_entity(ground_layer_id, target)
            if ground is None or ground.kind != claimable_kind:
                continue
            if board.has_tag_at(ground_layer_id, target, wall_tag, info.game.entity_kinds):
                continue
            seen.add(target)
            q.append((target, dist + 1))
    return None


def heuristic(state: EngineState, info: EngineInfo) -> float:
    """Admissible heuristic for the ``balance`` goal (0 for other goals).

    Per-kingdom deficit is ``target − owned_k``.  A single claim-move adds at
    most one owned cell for one kingdom; taps and moves onto already-owned or
    foreign cells claim nothing.

    * Individual mode: each action advances at most one kingdom, so remaining
      actions ≥ **sum** of deficits — an admissible, much tighter bound.
    * Coupled mode: one action can claim for several kingdoms at once, so only
      the **max** deficit is a safe (admissible) lower bound.

    Returns ``inf`` (a dead end the search prunes) when any kingdom already owns
    more than ``target``: claims are irreversible, so balance can never recover.
    """
    cfg = _balance_goal(info)
    if cfg is None or not _balance_optimizations_supported(state, info, cfg):
        return 0.0
    owners = cfg.get("owners", [])
    if not owners:
        return 0.0
    target, owned = _balance_target_and_owned(state, info, cfg, owners)
    if target is None:
        return 0.0  # malformed target; don't guide
    if any(owned[o] > target for o in owners):
        return float("inf")
    if _individual_system(info) is not None:
        return _individual_balance_heuristic(state, info, cfg, owners, target, owned)
    return _coupled_balance_heuristic(owners, target, owned)


def legal_actions(state: EngineState, info: EngineInfo) -> list[str]:
    """Per-state legal action list — a generic pruning of the static ACTIONS.

    For games with an enabled ``individual_actors`` system the select action
    (``tap_cell``) is only valid on cells that currently hold an actor; tapping
    any other cell is always vetoed and produces an identical (deduped) state,
    so enumerating all width×height tap targets is pure wasted work.  Here we
    restrict the select action to actor-occupied cells, collapsing branching
    from ~width×height taps to one-per-actor.  Games without an individual
    system are unaffected (the full ACTIONS list is returned).
    """
    if state.game_state.is_won or state.game_state.is_lost:
        return []

    indiv = _individual_system(info)
    sliding = _sliding_system(info)
    # Combining two selection models needs game-specific arbitration. Falling
    # back to the complete static action set is slower but remains sound.
    if indiv is not None and sliding is not None:
        return info.ACTIONS
    if sliding is not None:
        return _sliding_legal_actions(state, info, sliding)
    if indiv is None:
        return info.ACTIONS
    # Re-selecting an actor and attempting a blocked move both emit events.
    # Rules may intentionally react to those events, so only prune them when
    # the game has no reactive rules.
    if _has_reactive_rules(info):
        return info.ACTIONS

    cfg = indiv.get("config", {})
    select_action = cfg.get("selectAction", "tap_cell")
    move_action = cfg.get("moveAction", "move")
    actor_layer_id = cfg.get("actorLayer", "actors")
    ground_layer_id = cfg.get("groundLayer", "ground")
    wall_tag = cfg.get("wallTag", "solid")
    selected_key = cfg.get("selectedVariable", "selectedActorKind")
    selected_position_key = cfg.get(
        "selectedPositionVariable", "selectedActorPosition")
    selected_kind = state._state.variables.get(selected_key)
    selected_position_raw = state._state.variables.get(selected_position_key)
    selected_position = (
        tuple(selected_position_raw[:2])
        if isinstance(selected_position_raw, (list, tuple))
        and len(selected_position_raw) >= 2
        else None
    )
    remaining = _actor_budgets_remaining(state, cfg)
    has_budgets = bool(cfg.get("budgets"))

    layer = state._state.board.layers.get(actor_layer_id)
    occupied: set[tuple[int, int]] = set()
    selected_actor_position: Optional[Pos] = None
    if layer is not None:
        selected_kind_positions: list[Pos] = []
        for pos, entity in layer.entries():
            occupied.add((pos.x, pos.y))
            if entity.kind == selected_kind:
                selected_kind_positions.append(pos)
            if (
                entity.kind == selected_kind
                and selected_position == (pos.x, pos.y)
            ):
                selected_actor_position = pos
        if selected_position is None and len(selected_kind_positions) == 1:
            selected_actor_position = selected_kind_positions[0]

    board = state._state.board
    select_prefix = f"{select_action}_"
    move_prefix = f"{move_action}_"
    result: list[str] = []
    for action in info.ACTIONS:
        if action.startswith(select_prefix):
            rest = action[len(select_prefix):].split("_")
            if len(rest) != 2:
                continue
            pos_key = (int(rest[0]), int(rest[1]))
            actor_kind = None
            if layer is not None:
                entity = layer.get(Pos(pos_key[0], pos_key[1]))
                actor_kind = entity.kind if entity is not None else None
            if (
                pos_key in occupied
                and actor_kind is not None
                and pos_key != selected_position
                and (not has_budgets or int(remaining.get(actor_kind, 0)) > 0)
            ):
                result.append(action)
        elif action.startswith(move_prefix):
            if not selected_kind:
                continue
            if has_budgets and int(remaining.get(selected_kind, 0)) <= 0:
                continue
            pos = selected_actor_position
            if pos is None:
                continue
            action_id, params = _parse_action(action, info.game)
            direction = params.get("direction")
            target = pos.moved(direction)
            if (
                not board.is_in_bounds(target)
                or board.has_tag_at(ground_layer_id, target, wall_tag, info.game.entity_kinds)
                or (target.x, target.y) in occupied
            ):
                continue
            result.append(action)
        else:
            result.append(action)
    return result


def _sliding_legal_actions(
    state: EngineState,
    info: EngineInfo,
    system: dict,
) -> list[str]:
    """Use one canonical position per block instead of every board cell."""
    config = system.get("config", {})
    move_action = config.get("moveAction", "move")
    action_def = next(
        (action for action in info.game.actions if action["id"] == move_action),
        None,
    )
    if action_def is None:
        return info.ACTIONS
    params = action_def.get("params", {})
    if "position" not in params or "direction" not in params:
        return info.ACTIONS

    declared_directions = params["direction"].get(
        "values", ["up", "down", "left", "right"]
    )
    allowed_by_axis = {
        "horizontal": {"left", "right"},
        "vertical": {"up", "down"},
        "both": {"up", "down", "left", "right"},
    }
    result: list[str] = []
    for block in state.game_state.board.multi_cell_objects:
        if not block.cells:
            continue
        position = min(block.cells, key=lambda pos: (pos.y, pos.x))
        allowed = allowed_by_axis.get(str(block.params.get("axis", "both")), set())
        for direction in declared_directions:
            if direction in allowed:
                result.append(
                    f"{move_action}_{position.x}_{position.y}_{direction}"
                )

    for action in info.ACTIONS:
        try:
            action_id, _params = _parse_action(action, info.game)
        except (TypeError, ValueError):
            continue
        if action_id != move_action:
            result.append(action)
    return result


def canonicalize_path(
    actions: list[str],
    initial: EngineState,
    info: EngineInfo,
) -> list[str]:
    """Normalize equivalent sliding-block cell selections along a path."""
    sliding = _sliding_system(info)
    if sliding is None:
        return actions
    move_action = sliding.get("config", {}).get("moveAction", "move")

    state = initial
    result: list[str] = []
    for action in actions:
        canonical = action
        action_id, params = _parse_action(action, info.game)
        position_raw = params.get("position")
        direction = params.get("direction")
        if action_id == move_action and position_raw is not None and direction:
            position = Pos.from_json(position_raw)
            block = next(
                (
                    item
                    for item in state.game_state.board.multi_cell_objects
                    if position in item.cells
                ),
                None,
            )
            if block is not None and block.cells:
                first = min(block.cells, key=lambda pos: (pos.y, pos.x))
                canonical = f"{move_action}_{first.x}_{first.y}_{direction}"
        result.append(canonical)
        state, _won, _events = apply(state, canonical, info)
    return result


# ---------------------------------------------------------------------------
# Gold path helpers
# ---------------------------------------------------------------------------

def gold_path_actions(level_json: dict) -> list[str]:
    """
    Extract the gold path from a level JSON as flat action strings.

    Works for any game: position-and-direction entries become
    ``"{action}_{x}_{y}_{dir}"``, direction-only entries become
    ``"{action}_{dir}"``, and param-less entries remain ``"{action}"``.
    """
    gold_raw = level_json.get("solution", {}).get("goldPath", [])
    actions: list[str] = []
    _cardinals = {"up", "down", "left", "right"}
    for entry in gold_raw:
        if isinstance(entry, str):
            actions.append(f"move_{entry}" if entry in _cardinals else entry)
        elif isinstance(entry, dict):
            action_id = entry.get("action", "move")
            direction = entry.get("direction")
            position = entry.get("position")
            if direction and position:
                actions.append(
                    f"{action_id}_{position[0]}_{position[1]}_{direction}")
            elif direction:
                actions.append(f"{action_id}_{direction}")
            elif position:
                actions.append(f"{action_id}_{position[0]}_{position[1]}")
            else:
                actions.append(action_id)
    return actions
