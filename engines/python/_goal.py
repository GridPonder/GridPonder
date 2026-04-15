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


# ---------------------------------------------------------------------------
# Lose evaluator
# ---------------------------------------------------------------------------

def evaluate_lose(lose_conditions: list[dict], state: GameState) -> tuple[bool, str | None]:
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
    return False, None
