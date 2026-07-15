"""
Goal and lose condition evaluation.

Mirrors Dart's goal_evaluator.dart + lose_evaluator.dart.
"""
from __future__ import annotations
from typing import Any
from ._models import Pos, GameState, Entity
from ._game_def import GameDef


# ---------------------------------------------------------------------------
# Goal evaluator
# ---------------------------------------------------------------------------

def evaluate_goals(goals: list[dict], state: GameState, game: GameDef, pending_events: list[dict]) -> tuple[bool, dict[str, float]]:
    """Return (all_done, {goalId: progress})."""
    if not goals:
        return False, {}
    progress: dict[str, float] = {}
    all_done = True
    for goal in goals:
        done, prog = _evaluate_goal(goal, state, game, pending_events)
        progress[goal["id"]] = prog
        if not done:
            all_done = False
    return all_done, progress


def _evaluate_goal(goal: dict, state: GameState, game: GameDef, pending_events: list[dict]) -> tuple[bool, float]:
    gtype = goal["type"]
    cfg = goal.get("config", {})
    match gtype:
        case "reach_target":   return _reach_target(cfg, state, game)
        case "sequence_match": return _sequence_match(goal, cfg, state, game, pending_events)
        case "board_match":    return _board_match(cfg, state, game)
        case "variable_threshold": return _variable_threshold(cfg, state)
        case "all_cleared":    return _all_cleared(cfg, state, game)
        case "sum_constraint": return _sum_constraint(cfg, state)
        case "count_constraint": return _count_constraint(cfg, state)
        case "param_match":    return _param_match(cfg, state)
        case "balance":        return _balance(cfg, state, game)
        case _:                return False, 0.0


def _reach_target(cfg: dict, state: GameState, game: GameDef) -> tuple[bool, float]:
    if not state.avatar.enabled or state.avatar.position is None:
        return False, 0.0
    pos = state.avatar.position
    target_kind = cfg.get("targetKind")
    target_tag = cfg.get("targetTag")
    for layer_id in ["markers", "objects", "ground", "actors"]:
        entity = state.board.get_entity(layer_id, pos)
        if entity is None:
            continue
        if target_kind and entity.kind == target_kind:
            return True, 1.0
        if target_tag and game.has_tag(entity.kind, target_tag):
            return True, 1.0
    return False, 0.0


def _sequence_match(goal: dict, cfg: dict, state: GameState, game: GameDef, pending_events: list[dict]) -> tuple[bool, float]:
    sequence = [int(v) for v in cfg.get("sequence", [])]
    if not sequence:
        return True, 1.0
    current_index = state.sequence_indices.get(goal["id"], 0)
    trigger = cfg.get("scanTrigger", "turn_end")
    index = current_index

    if trigger == "on_merge":
        for event in pending_events:
            if event["type"] == "tiles_merged" and index < len(sequence):
                rv = event.get("resultValue")
                if rv == sequence[index]:
                    index += 1
    else:
        while index < len(sequence):
            target = sequence[index]
            found = _find_number_on_board(state, target)
            if found is None:
                break
            consume = cfg.get("consumeOnMatch", True)
            if consume:
                layer_id, found_pos = found
                state.board.set_entity(layer_id, found_pos, None)
            index += 1

    state.sequence_indices[goal["id"]] = index
    prog = index / len(sequence) if sequence else 1.0
    return index >= len(sequence), prog


def _find_number_on_board(state: GameState, target: int):
    objects_layer = state.board.layers.get("objects")
    if objects_layer is None:
        return None
    for pos, entity in objects_layer.entries():
        if entity.kind == "number":
            v = entity.param("value")
            if v == target or (v is not None and str(v) == str(target)):
                return ("objects", pos)
    return None


def _board_match(cfg: dict, state: GameState, game: GameDef) -> tuple[bool, float]:
    target_layers = cfg.get("targetLayers", {})
    match_mode = cfg.get("matchMode", "exact_non_null")
    total = matched = 0
    for layer_id, target_data in target_layers.items():
        board_layer = state.board.layers.get(layer_id)
        if board_layer is None:
            continue
        for y, row in enumerate(target_data):
            for x, target in enumerate(row):
                if match_mode == "exact_non_null" and target is None:
                    continue
                total += 1
                actual = board_layer.get(Pos(x, y))
                if match_mode == "exact_non_null":
                    te = Entity.from_json(target) if target else None
                    if actual and te and actual.kind == te.kind:
                        matched += 1
                else:
                    if target is None and actual is None:
                        matched += 1
                    elif target is not None and actual is not None:
                        te = Entity.from_json(target)
                        if actual.kind == te.kind:
                            matched += 1
    if total == 0:
        return True, 1.0
    prog = matched / total
    return matched == total, prog


def _variable_threshold(cfg: dict, state: GameState) -> tuple[bool, float]:
    name = cfg.get("variable", "")
    target = cfg.get("target", 0)
    comparison = cfg.get("comparison", "gte")
    current = state.variables.get(name)
    if current is None:
        return False, 0.0
    cur = float(current)
    done = {"eq": cur == target, "gte": cur >= target, "lte": cur <= target}.get(comparison, False)
    prog = min(1.0, cur / target) if target != 0 else 1.0
    return done, prog


def _all_cleared(cfg: dict, state: GameState, game: GameDef) -> tuple[bool, float]:
    kind = cfg.get("kind")
    tag = cfg.get("tag")
    remaining = 0
    for layer in state.board.layers.values():
        for _, entity in layer.entries():
            if kind and entity.kind == kind:
                remaining += 1
            if tag and game.has_tag(entity.kind, tag):
                remaining += 1
    return remaining == 0, 1.0 if remaining == 0 else 0.0


def _cell_value(entity: Any, board: Any) -> int:
    if entity is None:
        return 0
    if entity.kind.startswith("num_"):
        try:
            return int(entity.kind[4:])
        except ValueError:
            return 0
    if entity.kind == "number":
        return entity.param("value") or 0
    return 0


def _sum_constraint(cfg: dict, state: GameState) -> tuple[bool, float]:
    layer_id = cfg.get("layer", "objects")
    scope = cfg.get("scope", "board")
    target = cfg.get("target", 0)
    comparison = cfg.get("comparison", "eq")
    index = cfg.get("index")
    layer = state.board.layers.get(layer_id)
    if layer is None:
        return False, 0.0
    w, h = state.board.width, state.board.height

    def cv(pos):
        return _cell_value(layer.get(pos), None)

    def satisfies(s):
        return {"gte": s >= target, "lte": s <= target}.get(comparison, s == target)

    match scope:
        case "row":
            if index is None: return False, 0.0
            ok = satisfies(sum(cv(Pos(x, index)) for x in range(w)))
            return ok, 1.0 if ok else 0.0
        case "col":
            if index is None: return False, 0.0
            ok = satisfies(sum(cv(Pos(index, y)) for y in range(h)))
            return ok, 1.0 if ok else 0.0
        case "all_rows":
            sums = [sum(cv(Pos(x, y)) for x in range(w)) for y in range(h)]
            sat = sum(1 for s in sums if satisfies(s))
            return sat == h, sat / h if h else 1.0
        case "all_cols":
            sums = [sum(cv(Pos(x, y)) for y in range(h)) for x in range(w)]
            sat = sum(1 for s in sums if satisfies(s))
            return sat == w, sat / w if w else 1.0
        case "board":
            total = sum(cv(Pos(x, y)) for y in range(h) for x in range(w))
            ok = satisfies(total)
            return ok, 1.0 if ok else 0.0
        case _:
            return False, 0.0


def _count_constraint(cfg: dict, state: GameState) -> tuple[bool, float]:
    layer_id = cfg.get("layer", "objects")
    scope = cfg.get("scope", "all_rows")
    predicate = cfg.get("predicate", "even")
    target = cfg.get("target", 0)
    comparison = cfg.get("comparison", "eq")
    index = cfg.get("index")
    layer = state.board.layers.get(layer_id)
    if layer is None:
        return False, 0.0
    w, h = state.board.width, state.board.height

    def cv(pos):
        return _cell_value(layer.get(pos), None)

    def matches_pred(v):
        if predicate == "even": return v % 2 == 0
        if predicate == "odd": return v % 2 != 0
        if predicate.startswith("gte_"): return v >= int(predicate[4:])
        if predicate.startswith("lte_"): return v <= int(predicate[4:])
        if predicate.startswith("eq_"): return v == int(predicate[3:])
        return False

    def has_entity(pos): return layer.get(pos) is not None

    def row_count(y):
        return sum(1 for x in range(w) if has_entity(Pos(x, y)) and matches_pred(cv(Pos(x, y))))

    def col_count(x):
        return sum(1 for y in range(h) if has_entity(Pos(x, y)) and matches_pred(cv(Pos(x, y))))

    def satisfies(c):
        return {"gte": c >= target, "lte": c <= target}.get(comparison, c == target)

    match scope:
        case "row":
            if index is None: return False, 0.0
            ok = satisfies(row_count(index))
            return ok, 1.0 if ok else 0.0
        case "col":
            if index is None: return False, 0.0
            ok = satisfies(col_count(index))
            return ok, 1.0 if ok else 0.0
        case "all_rows":
            sat = sum(1 for y in range(h) if satisfies(row_count(y)))
            return sat == h, sat / h if h else 1.0
        case "all_cols":
            sat = sum(1 for x in range(w) if satisfies(col_count(x)))
            return sat == w, sat / w if w else 1.0
        case _:
            return False, 0.0


def _param_match(cfg: dict, state: GameState) -> tuple[bool, float]:
    marker_layer_id = cfg.get("markerLayer", "markers")
    marker_kind = cfg.get("markerKind")
    check_layer_id = cfg.get("checkLayer", "objects")
    check_kind = cfg.get("checkKind")
    check_param = cfg.get("checkParam")
    check_value = cfg.get("checkValue")
    if check_param is None or check_value is None:
        return False, 0.0
    marker_layer = state.board.layers.get(marker_layer_id)
    check_layer = state.board.layers.get(check_layer_id)
    if marker_layer is None:
        return False, 0.0
    total = matched = 0
    for pos, entity in marker_layer.entries():
        if marker_kind and entity.kind != marker_kind:
            continue
        total += 1
        if check_layer is None:
            continue
        ce = check_layer.get(pos)
        if ce is None:
            continue
        if check_kind and ce.kind != check_kind:
            continue
        if ce.param(check_param) == check_value:
            matched += 1
    if total == 0:
        return False, 0.0
    return matched == total, matched / total


def _count_claimable(board: Any, cfg: dict) -> int:
    """Count cells in `cfg["claimableLayer"]` whose kind matches `cfg["claimableKind"]`
    (default: that layer's default kind) — every non-wall ground cell eligible
    to be owned. `claimableKind` accepts a single kind or a list of kinds, for
    boards where more than one ground kind can be owned.

    NOTE (engine parity, tracked follow-up): this reads the layer's declared
    (un-normalized) `default_kind` as set on `BoardLayer`. Dart's `Board.fromJson`
    normalizes a missing `exactly_one` layer `default` to `'empty'`, while this
    Python model does not perform that normalization. A claimable layer that
    omits `default` entirely, combined with a `balance` goal that also omits
    `claimableKind`, could therefore diverge between engines (Python: `None`
    here vs. Dart: `'empty'`). This is non-divergent for well-formed packs,
    which declare an explicit `default` on `exactly_one` layers. Follow-up:
    normalize the missing `exactly_one` default in `_models.py` to match Dart.
    """
    layer = board.layers.get(cfg.get("claimableLayer"))
    if layer is None:
        return 0
    claimable_kind = cfg.get("claimableKind", layer.default_kind)
    kinds = (set(claimable_kind) if isinstance(claimable_kind, (list, tuple))
             else {claimable_kind})
    return sum(1 for _pos, entity in layer.entries() if entity.kind in kinds)


def _balance(cfg: dict, state: GameState, game: GameDef) -> tuple[bool, float]:
    """Win when a territory layer is divided completely and into exactly-equal
    shares among the configured owners (or per requireComplete/requireEqual)."""
    layer = state.board.layers.get(cfg.get("layer"))
    counts = {o: 0 for o in cfg.get("owners", [])}
    if layer is not None:
        for _pos, entity in layer.entries():
            if entity.kind in counts:
                counts[entity.kind] += 1
    claimable = _count_claimable(state.board, cfg)
    owned = sum(counts.values())
    equal = len(set(counts.values())) == 1
    complete = owned == claimable
    progress = owned / claimable if claimable else 1.0
    done = (equal or not cfg.get("requireEqual", True)) and \
           (complete or not cfg.get("requireComplete", True))
    return done, progress


# ---------------------------------------------------------------------------
# Lose evaluator
# ---------------------------------------------------------------------------

def evaluate_lose(
    lose_conditions: list[dict],
    state: GameState,
    goals: list[dict] | None = None,
    game: GameDef | None = None,
) -> tuple[bool, str | None]:
    """Return (is_lost, reason | None)."""
    for cond in lose_conditions:
        ctype = cond["type"]
        cfg = cond.get("config", {})
        if ctype == "max_actions":
            if state.action_count >= cfg.get("limit", 0):
                return True, "max_actions"
        elif ctype == "variable_threshold":
            name = cfg.get("variable", "")
            target = cfg.get("target", 0)
            comparison = cfg.get("comparison", "gte")
            current = state.variables.get(name)
            if current is not None:
                cur = float(current)
                lost = {"eq": cur == target, "gte": cur >= target, "lte": cur <= target}.get(comparison, False)
                if lost:
                    return True, f"variable_threshold:{name}"
        elif ctype == "balance_budget_exhausted":
            if _balance_budget_exhausted(cfg, state, goals or [], game):
                return True, "balance_budget_exhausted"
        elif ctype == "balance_unreachable":
            if _balance_unreachable(cfg, state, goals or [], game):
                return True, "balance_unreachable"
    return False, None


def _claims_are_overwritable(state: GameState, game: GameDef | None) -> bool:
    """True when an owned cell on THIS board could actually be repainted.

    Both balance lose conditions share an over-claim test that assumes claims
    are permanent: an owner past its equal share can never come back down. That
    breaks when cells can be repainted, so the test must stay quiet rather than
    report a false loss.

    Deliberately a board-level question, not a config-level one. A pack may
    declare a `tagged` policy game-wide while most of its boards carry no tagged
    cells; on those boards claims *are* permanent and the conditions must still
    fire. Asking only "is a policy declared?" would silently disable the fail
    condition for the whole pack, and no gold-path test would catch it — a
    winning path never trips a lose condition.
    """
    if game is None:
        return False
    for system in getattr(game, "systems", []):
        if system.get("type") not in ("coupled_actors", "individual_actors"):
            continue
        config = system.get("config") or {}
        claim = config.get("claim") or {}
        overwrite = claim.get("overwrite") or {}
        mode = overwrite.get("mode", "never")
        if mode == "always":
            return True
        if mode != "tagged":
            continue
        tag = overwrite.get("tag")
        if not tag:
            continue
        layer_id = overwrite.get("layer", config.get("groundLayer", "ground"))
        layer = state.board.layers.get(layer_id)
        if layer is None:
            continue
        for pos, _entity in layer.entries():
            if state.board.has_tag_at(layer_id, pos, tag, game.entity_kinds):
                return True
    return False


def _balance_budget_exhausted(
    cfg: dict,
    state: GameState,
    goals: list[dict],
    game: GameDef | None,
) -> bool:
    goal = _balance_goal_for_condition(cfg, goals)
    if goal is None:
        return False

    goal_cfg = goal.get("config", {})
    owners = goal_cfg.get("owners", [])
    if not owners:
        return False

    claimable = _count_claimable_for_budget_loss(state, goal_cfg, game)
    if claimable % len(owners) != 0:
        return True
    target = claimable // len(owners)

    owned = {owner: 0 for owner in owners}
    layer = state.board.layers.get(goal_cfg.get("layer", "territory"))
    if layer is not None:
        for _pos, entity in layer.entries():
            if entity.kind in owned:
                owned[entity.kind] += 1

    # Over-claim is only terminal while claims are permanent. The deficit check
    # below stays sound under reclaim (a claimer still spends a move per cell).
    if (any(count > target for count in owned.values())
            and not _claims_are_overwritable(state, game)):
        return True

    actor_to_owner = cfg.get("actorToOwner") or _individual_actor_to_owner(game)
    if not actor_to_owner:
        return False

    budget_key = cfg.get("budgetVariable", "actorMovesRemaining")
    remaining = state.variables.get(budget_key)
    if not isinstance(remaining, dict):
        remaining = _individual_budgets(game)
    if not isinstance(remaining, dict):
        return False

    for actor_kind, owner_kind in actor_to_owner.items():
        if owner_kind not in owned:
            continue
        deficit = target - owned[owner_kind]
        if deficit > int(remaining.get(actor_kind, 0)):
            return True
    return False


def _balance_unreachable(
    cfg: dict,
    state: GameState,
    goals: list[dict],
    game: GameDef | None,
) -> bool:
    """Fires when the `balance` goal's equal-share requirement has already
    become impossible: some owner has claimed strictly more than its equal
    share (`claimable / owners`). Because a claimed cell can never change owner,
    an over-target owner can never come back down, so the level is unwinnable
    and is lost immediately rather than only when the action cap is reached.
    Also fires if `claimable` is not divisible by the owner count (equal shares
    are arithmetically impossible). Generic across coupled and individual modes;
    unlike `balance_budget_exhausted` it needs no actor/budget wiring.

    The over-claim half is suppressed when the board carries repaintable cells
    (see `_claims_are_overwritable`) — an over-share owner can then be repainted
    back down, so it is not terminal."""
    goal = _balance_goal_for_condition(cfg, goals)
    if goal is None:
        return False

    goal_cfg = goal.get("config", {})
    owners = goal_cfg.get("owners", [])
    if not owners:
        return False

    claimable = _count_claimable_for_budget_loss(state, goal_cfg, game)
    if claimable % len(owners) != 0:
        return True
    target = claimable // len(owners)

    if _claims_are_overwritable(state, game):
        return False

    owned = {owner: 0 for owner in owners}
    layer = state.board.layers.get(goal_cfg.get("layer", "territory"))
    if layer is not None:
        for _pos, entity in layer.entries():
            if entity.kind in owned:
                owned[entity.kind] += 1

    return any(count > target for count in owned.values())


def _balance_goal_for_condition(cfg: dict, goals: list[dict]) -> dict | None:
    goal_id = cfg.get("goalId")
    for goal in goals:
        if goal.get("type") != "balance":
            continue
        if goal_id is None or goal.get("id") == goal_id:
            return goal
    return None


def _count_claimable_for_budget_loss(
    state: GameState,
    goal_cfg: dict,
    game: GameDef | None,
) -> int:
    layer_id = goal_cfg.get("claimableLayer", "ground")
    claimable_kind = goal_cfg.get("claimableKind")
    if claimable_kind is None and game is not None:
        layer_def = next((layer for layer in game.layers if layer.get("id") == layer_id), None)
        claimable_kind = layer_def.get("defaultKind") if layer_def is not None else None
    if claimable_kind is None:
        claimable_kind = "empty"

    # `claimableKind` accepts a single kind or a list. Must agree with
    # `_count_claimable` above — if the goal and the lose conditions disagree
    # about the claimable count, the level is unwinnable or falsely lost.
    kinds = (set(claimable_kind) if isinstance(claimable_kind, (list, tuple))
             else {claimable_kind})

    layer = state.board.layers.get(layer_id)
    if layer is None:
        return 0
    return sum(1 for _pos, entity in layer.entries() if entity.kind in kinds)


def _individual_actor_to_owner(game: GameDef | None) -> dict[str, str]:
    if game is None:
        return {}
    for system in game.systems:
        if system.get("type") == "individual_actors" and system.get("enabled", True):
            claim = system.get("config", {}).get("claim", {})
            return {str(k): str(v) for k, v in claim.get("map", {}).items()}
    return {}


def _individual_budgets(game: GameDef | None) -> dict[str, int]:
    if game is None:
        return {}
    for system in game.systems:
        if system.get("type") == "individual_actors" and system.get("enabled", True):
            budgets = system.get("config", {}).get("budgets", {})
            return {str(k): int(v) for k, v in budgets.items()}
    return {}
