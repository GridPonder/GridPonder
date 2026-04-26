"""
TurnEngine — orchestrates the 7-phase turn pipeline.

Mirrors Dart's TurnEngine + PhaseRunner.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Any

from ._models import GameState
from ._game_def import GameDef
from ._rules_engine import RulesEngine
from ._goal import evaluate_goals, evaluate_lose
from ._systems import instantiate_systems
from . import _events as ev


@dataclass
class TurnResult:
    accepted: bool
    events: list[dict]
    is_won: bool
    is_lost: bool
    lose_reason: Optional[str] = None
    goal_progress: Optional[dict[str, float]] = None


class TurnEngine:
    """
    Stateful turn engine for one level.

    Usage::

        engine = TurnEngine(game_def, level_def)
        result = engine.execute_turn('move', {'direction': 'right'})
        if engine.is_won:
            ...
        engine.undo()
        engine.reset()
    """

    def __init__(self, game_def: GameDef, level_def: dict):
        """
        Parameters
        ----------
        game_def : GameDef
            Parsed game.json.
        level_def : dict
            Parsed level JSON (as returned by LevelDef or a raw dict).
        """
        self._game = game_def
        self._level = level_def  # raw dict with goals, rules, systemOverrides, solution, etc.
        self._initial_state = self._make_initial_state()
        self._apply_load_cascade(self._initial_state)
        self._state = self._initial_state.copy()
        self._history: list[GameState] = []  # undo stack

    def _make_initial_state(self) -> GameState:
        from ._models import Board, GameState
        layer_defs = self._game.layers
        board_json = self._level.get("board", {})
        board = Board.from_json(board_json, layer_defs)
        state_json = self._level.get("state", {})
        return GameState.from_json(state_json, board, self._game.defaults)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def state(self) -> GameState:
        return self._state

    @property
    def is_won(self) -> bool:
        return self._state.is_won

    @property
    def is_lost(self) -> bool:
        return self._state.is_lost

    @property
    def undo_depth(self) -> int:
        return len(self._history)

    def execute_turn(
        self,
        action_id: str,
        params: Optional[dict] = None,
        save_history: bool = True,
    ) -> TurnResult:
        """Execute one turn. Returns TurnResult. State is mutated in place.

        Parameters
        ----------
        save_history : bool
            If False, skip the undo snapshot (useful for solvers that never
            call undo()).  Default True preserves normal behaviour.
        """
        params = params or {}
        action = {"actionId": action_id, "params": params}

        # Phase 1: input validation
        if not self._game.is_valid_action(action_id):
            return TurnResult(accepted=False, events=[], is_won=False, is_lost=False)

        # Save undo snapshot (skip for performance-critical callers like the solver)
        if save_history:
            self._history.append(self._state.copy())

        state = self._state
        systems = instantiate_systems(self._game)
        all_events: list[dict] = []

        # Phase 2: Action resolution
        for sys in systems:
            events = sys.execute_action_resolution(action, state, self._game)
            all_events.extend(events)

        # If vetoed → reject (don't count the move)
        if any(e["type"] == "action_vetoed" for e in all_events):
            if save_history:
                self._history.pop()
            return TurnResult(accepted=False, events=all_events, is_won=False, is_lost=False)

        # Phase 3: Movement resolution
        for sys in systems:
            events = sys.execute_movement_resolution(state, self._game)
            all_events.extend(events)

        # Phase 4: Interaction resolution (no-op in v0)

        # Phase 5: Cascade resolution
        level_rules = self._level.get("rules", []) or []
        # Normalise level rules to same format as game rules
        norm_level_rules = [
            {
                "id": r.get("id", ""),
                "on": r["on"],
                "where": r.get("where"),
                "if": r.get("if"),
                "then": r.get("then", []),
                "priority": r.get("priority", 0),
                "once": r.get("once", False),
            }
            for r in level_rules
        ]
        rules_engine = RulesEngine(self._game.rules, norm_level_rules)
        max_depth = self._game.defaults.get("maxCascadeDepth", 3)
        cascade_events = rules_engine.evaluate(all_events, state, self._game, max_depth, systems)
        all_events.extend(cascade_events)

        # Phase 6: NPC resolution
        for sys in systems:
            events = sys.execute_npc_resolution(state, self._game)
            all_events.extend(events)

        # Phase 7: Goal evaluation
        state.action_count += 1
        state.turn_count += 1

        goals = self._level.get("goals", []) or []
        lose_conditions = self._level.get("loseConditions", []) or []

        is_won, goal_progress = evaluate_goals(goals, state, self._game, all_events)
        if is_won:
            state.is_won = True

        is_lost = False
        lose_reason = None
        if not state.is_won:
            is_lost, lose_reason = evaluate_lose(lose_conditions, state)
            if is_lost:
                state.is_lost = True

        all_events.append(ev.turn_ended(state.turn_count))

        return TurnResult(
            accepted=True,
            events=all_events,
            is_won=state.is_won,
            is_lost=is_lost,
            lose_reason=lose_reason,
            goal_progress=goal_progress,
        )

    def undo(self) -> bool:
        """Restore previous state. Returns False if nothing to undo."""
        if not self._history:
            return False
        self._state = self._history.pop()
        return True

    def reset(self) -> None:
        """Restore to initial state, clear undo stack."""
        self._state = self._initial_state.copy()
        self._history.clear()

    def _apply_load_cascade(self, state: GameState) -> None:
        """Fire ``object_placed`` events for every object on a non-ground layer
        at level load, then run the rules engine cascade. Mirrors the Dart
        engine so always-on rules like ``crate_floats_on_water`` apply
        uniformly to objects placed during play and to objects already on the
        board at start.
        """
        initial_events: list[dict] = []
        for layer_def in self._game.layers:
            if layer_def.get("occupancy") != "zero_or_one":
                continue
            layer = state.board.layers.get(layer_def["id"])
            if layer is None:
                continue
            for pos, entity in layer.entries():
                initial_events.append(
                    ev.object_placed(pos, entity.kind, dict(entity.params))
                )
        if not initial_events:
            return
        systems = instantiate_systems(self._game)
        level_rules = self._level.get("rules", []) or []
        norm_level_rules = [
            {
                "id": r.get("id", ""),
                "on": r["on"],
                "where": r.get("where"),
                "if": r.get("if"),
                "then": r.get("then", []),
                "priority": r.get("priority", 0),
                "once": r.get("once", False),
            }
            for r in level_rules
        ]
        rules_engine = RulesEngine(self._game.rules, norm_level_rules)
        max_depth = self._game.defaults.get("maxCascadeDepth", 3)
        rules_engine.evaluate(initial_events, state, self._game, max_depth, systems)

    def state_key(self) -> tuple:
        """Hashable state snapshot for BFS/A* deduplication."""
        return self._state.to_key()
