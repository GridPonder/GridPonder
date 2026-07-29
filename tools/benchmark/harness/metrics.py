"""Per-run metrics and tier classification.

The important distinction is friction vs search. Both look like "the agent
lost", but they mean opposite things:

  friction — the agent could not express legal moves. That is a level or docs
             defect (TENETS.md: "difficulty should come from reasoning, not
             friction"), so it is routed to a bug queue and excluded from the
             difficulty ranking.
  search   — every move legal, but the agent still could not find the door.
             That is genuine insight-gating, i.e. real difficulty.

Only *schema* rejections separate those two. The runner reports rejections
under two counters and they mean opposite things:

  rejected_schema  — the JSON did not name a real action or did not match that
                     action's declared parameters. The agent could not say what
                     it meant. That is friction.
  rejected_illegal — a well-formed action the engine refused in this state
                     (walking into a wall, tapping an unreachable cell). That is
                     ordinary probing, and a puzzle that invites it is doing its
                     job. It is reported but never classifies a run.

Collapsing the two would misread both directions at once: a pincer agent
probing walls would look like a docs defect, and a three_kingdoms agent whose
malformed JSON is silently swallowed would look clean.

Pure functions. No I/O.
"""
from __future__ import annotations

from typing import Any


def first_divergence(
    agent_moves: list[dict[str, Any]],
    gold_path: list[dict[str, Any]],
) -> int | None:
    """Index where the agent's first attempt leaves the gold-path prefix.

    Returns None when the agent's moves are a prefix of the gold path (i.e. it
    never diverged), including when it made no moves at all.
    """
    for i, move in enumerate(agent_moves):
        if i >= len(gold_path) or move != gold_path[i]:
            return i
    return None


def efficiency(actions_total: int, gold_path_length: int) -> float | None:
    """Actions taken per gold-path action. None when gold length is unknown."""
    if not gold_path_length:
        return None
    return actions_total / gold_path_length


def classify(run: dict[str, Any], thresholds: dict[str, Any]) -> str:
    """Sort one tier-1 run into trivial | borderline | hard | friction.

    Reads `rejected_schema` only. `rejected_illegal` is carried on the run for
    reporting but deliberately does not feed the friction test — a solved run
    is never friction just because the agent probed the geometry on its way.
    """
    if run["rejected_schema"] >= thresholds["rejected_friction_min"]:
        return "friction"
    if not run["solved"]:
        return "hard"
    eff = efficiency(run["actions_total"], run["gold_path_length"])
    wandered = eff is not None and eff > thresholds["efficiency_trivial_max"]
    if run["attempts"] > 1 or wandered:
        return "borderline"
    return "trivial"
