"""
Rules engine (cascade resolution, phase 5).

Mirrors Dart's rules_engine.dart:
  - Evaluates all rules against pending events
  - Cascade systems run after each pass
  - Repeats up to maxCascadeDepth times
"""
from __future__ import annotations
from ._models import GameState
from ._game_def import GameDef
from . import _conditions as cond
from . import _effects as eff


class RulesEngine:
    def __init__(self, game_rules: list[dict], level_rules: list[dict]):
        self._all_rules = sorted(
            game_rules + level_rules,
            key=lambda r: r.get("priority", 0),
            reverse=True,  # higher priority first
        )

    def evaluate(
        self,
        initial_events: list[dict],
        state: GameState,
        game: GameDef,
        max_depth: int,
        cascade_systems: list,
    ) -> list[dict]:
        """
        Run cascade loop: for each pass, fire matching rules then cascade systems.
        Returns all newly emitted events (not including initial_events).
        """
        all_new_events: list[dict] = []
        pending = list(initial_events)

        for _ in range(max_depth):
            if not pending:
                break

            new_events: list[dict] = []

            for event in pending:
                for rule in self._all_rules:
                    if rule["on"] != event["type"]:
                        continue
                    # once-fired guard
                    if rule.get("once") and rule["id"] in state.once_fired_rules:
                        continue
                    # where condition
                    if not cond.evaluate(rule.get("where"), event, state, game):
                        continue
                    # if condition
                    if not cond.evaluate(rule.get("if"), event, state, game):
                        continue
                    # fire
                    if rule.get("once"):
                        state.once_fired_rules.add(rule["id"])
                    for effect in rule.get("then", []):
                        new_events.extend(eff.execute(effect, event, state, game))

            # cascade systems
            for sys in cascade_systems:
                new_events.extend(sys.execute_cascade_resolution(pending, state, game))

            all_new_events.extend(new_events)
            pending = new_events

        return all_new_events
