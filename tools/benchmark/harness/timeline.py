"""Read a session transcript and say where the agent got into trouble.

A result row says an agent took 38 actions and lost once. It cannot say which
move lost the attempt, how long the agent stared at the board first, or what it
believed at the time. That is the question worth answering when a level is
behaving oddly, and it needs the turn-by-turn record.

An "obstacle" here is a turn that cost the agent something: a rejection of
either kind, or a lost attempt. Each is paired with the agent's own reasoning
from just before it, so the entry says what it was trying to do — not merely
that something failed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# ./play invocations inside a shell command the agent ran. Deliberately loose:
# an agent writes `./play move '{...}'`, sometimes wrapped in a loop or joined
# with &&, and a missed match costs an annotation rather than correctness.
_PLAY_RE = re.compile(r"\./play\s+(state|move|history|give_up)([^\n;&|]*)")


def load_turns(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    turns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                turns.append(json.loads(line))
            except ValueError:
                continue
    return turns


def load_reasoning(path: Path) -> list[dict]:
    """The agent's narration, if its stream was captured next to the transcript."""
    from tools.benchmark.harness import agents

    stream = path.with_suffix(".agent.jsonl")
    if not stream.is_file():
        return []
    return agents.reasoning_timeline(stream.read_text(encoding="utf-8"))


def pair_reasoning(turns: list[dict], reasoning: list[dict]) -> None:
    """Attach each ./play call to the reasoning that led to it, in place.

    Matched by walking both sequences in order rather than by timestamp: the
    agent's stream and the game's transcript are written by different
    processes, and their clocks agree only loosely. Order is exact — the agent
    cannot make a call before deciding to.

    The text and the tool call usually arrive as *separate* messages, so the
    message that issued a command is very often textless. Taking its text
    verbatim yields a blank quote on nearly every obstacle, which is the
    difference between an appendix worth reading and one worth deleting; the
    last non-empty text before the call is what actually explains it.

    Carrying text forward has its own failure mode, though: a move the agent
    made in silence inherits the previous move's reasoning and reads as
    explained when it is not. `reasoning_fresh` says which it was, so a report
    can quote the first and admit the second instead of putting words in the
    agent's mouth.
    """
    owners: list[tuple[str, bool]] = []
    last_text = ""
    fresh = False
    for message in reasoning:
        if message["text"]:
            last_text = message["text"]
            fresh = True
        for command in message["commands"]:
            for _verb, _rest in _PLAY_RE.findall(command):
                owners.append((last_text, fresh))
                # Only the first call after a block of reasoning can claim it.
                # A message that fires three commands explains the first; the
                # other two are the agent acting on a plan already made.
                fresh = False

    for index, turn in enumerate(turns):
        # A reason the agent handed to `./play move` beats anything scraped out
        # of its output stream: it was stated at the moment it applied, it is
        # attached to that move rather than aligned with it, and no CLI can
        # strip it on the way through.
        stated = (turn.get("why") or "").strip()
        if stated:
            turn["reasoning"], turn["reasoning_fresh"] = stated, True
            continue
        reason, was_fresh = owners[index] if index < len(owners) else ("", False)
        turn["reasoning"], turn["reasoning_fresh"] = reason, was_fresh


def obstacles(turns: list[dict]) -> list[dict]:
    """Turns that cost the agent something, in order."""
    found = []
    for turn in turns:
        kinds = []
        if turn.get("rejected_schema"):
            kinds.append("schema rejection")
        if turn.get("rejected_illegal"):
            kinds.append("illegal move")
        if turn.get("lost_attempt"):
            kinds.append("lost the attempt")
        if kinds:
            found.append({**turn, "kinds": kinds})
    return found


def attempts(turns: list[dict]) -> list[dict]:
    """Per-attempt totals, so a multi-attempt run can be read attempt by attempt.

    This is what separates "38 actions" from "20 then 18": the per-attempt
    action cap is a lose condition, so a run's total says nothing about whether
    any single attempt came close to it.
    """
    by_attempt: dict[int, dict] = {}
    for turn in turns:
        number = turn.get("attempt")
        if number is None:
            continue
        row = by_attempt.setdefault(number, {
            "attempt": number, "calls": 0, "actions": 0,
            "rejected_schema": 0, "rejected_illegal": 0,
            "lost": False, "seconds": 0.0,
        })
        row["calls"] += 1
        row["rejected_schema"] += turn.get("rejected_schema", 0)
        row["rejected_illegal"] += turn.get("rejected_illegal", 0)
        row["seconds"] += turn.get("took", 0.0)
        if turn.get("actions_this_attempt") is not None:
            row["actions"] = max(row["actions"], turn["actions_this_attempt"])
        if turn.get("lost_attempt"):
            row["lost"] = True
    return [by_attempt[k] for k in sorted(by_attempt)]


def thinking_gaps(turns: list[dict], top: int = 5) -> list[dict]:
    """The moves the agent spent longest deciding on.

    Not `took`, which is only how long the supervisor needed to answer — a few
    milliseconds, since it is reading a pipe. A hosted model does its thinking
    *between* calls, so the interesting number is the gap from one reply going
    out to the next request arriving. Long gaps mark the decisions it found
    hard, which is usually where a level's real difficulty lives.
    """
    ranked = []
    for previous, turn in zip(turns, turns[1:]):
        gap = turn.get("elapsed", 0.0) - (
            previous.get("elapsed", 0.0) + previous.get("took", 0.0))
        if gap > 0:
            ranked.append({**turn, "thought_for": round(gap, 1)})
    ranked.sort(key=lambda t: t["thought_for"], reverse=True)
    return ranked[:top]


def narrative(reasoning: list[dict]) -> list[dict]:
    """The agent's reasoning in order, each block with the calls it led to.

    This is the appendix: the run as the agent narrated it, rather than the
    subset that happened to go wrong. Messages with neither text nor a ./play
    call are dropped — they are the agent reading its own notes, and they pad
    the appendix without adding to it.
    """
    out = []
    for message in reasoning:
        calls = [f"{verb}{rest}".strip()
                 for command in message["commands"]
                 for verb, rest in _PLAY_RE.findall(command)]
        if message["text"] or calls:
            out.append({"text": message["text"], "calls": calls})
    return out


def dialogue(turns: list[dict], reasoning: list[dict]) -> list[dict]:
    """The run as a conversation: what the agent thought, did, and was told.

    narrative() shows the agent's half only, and that is the wrong half for the
    question this module exists to answer. An agent trips when what it expected
    and what the board did come apart, so the diagnosis needs both sides
    adjacent — reasoning, the command it produced, and the reply that either
    confirmed it or did not.

    Everything is carried through; what to show is the report's decision. A
    board printed 76 times is noise in a PDF and evidence in a diff.
    """
    def call_entry(turn: dict, verb: str, text: str) -> list[dict]:
        out = []
        stated = (turn.get("why") or "").strip()
        if stated:
            out.append({"kind": "thought", "text": stated, "stated": True})
        out.append({"kind": "call", "verb": verb, "call": text, "turn": turn})
        return out

    merged: list[dict] = []
    index = 0
    for message in reasoning:
        if message["text"]:
            merged.append({"kind": "thought", "text": message["text"],
                           "stated": False})
        for command in message["commands"]:
            for verb, rest in _PLAY_RE.findall(command):
                turn = turns[index] if index < len(turns) else {}
                index += 1
                merged += call_entry(turn, verb, f"{verb}{rest}".strip())

    # An agent whose stream we could not read at all — a harness that prints
    # nothing, or a CLI that changed its output shape — still has a game-side
    # transcript, and if it stated its reasons through the protocol that
    # transcript is complete on its own. Falling back to it keeps the appendix
    # from disappearing exactly when the other channel failed.
    if not merged:
        for turn in turns:
            merged += call_entry(
                turn, turn.get("verb", ""),
                " ".join([turn.get("verb", ""), *(turn.get("args") or [])]).strip())
    return merged


def coverage(turns: list[dict]) -> dict:
    """How much of the run we actually captured a reason for.

    A diagnostic report is only as good as this number. Reading "the agent
    stalled at move 12" off a transcript where two thirds of the moves arrived
    unnarrated is reading tea leaves, so the ratio is reported next to the
    findings rather than left for someone to infer.
    """
    calls = len(turns)
    explained = sum(1 for t in turns if t.get("reasoning_fresh"))
    return {
        "calls": calls,
        "explained": explained,
        "ratio": round(explained / calls, 3) if calls else 0.0,
    }


def summarize(path: Path) -> dict:
    """Everything the report needs from one session's transcript."""
    turns = load_turns(path)
    if not turns:
        return {}
    reasoning = load_reasoning(path)
    pair_reasoning(turns, reasoning)
    moves = [t for t in turns if t["verb"] == "move"]
    return {
        "turns": len(turns),
        "moves": len(moves),
        "looks": sum(1 for t in turns if t["verb"] in ("state", "history")),
        "attempts": attempts(turns),
        "obstacles": obstacles(turns),
        "slowest": thinking_gaps(turns),
        "narrative": narrative(reasoning),
        "dialogue": dialogue(turns, reasoning),
        "coverage": coverage(turns),
        "seconds": round(sum(t.get("took", 0.0) for t in turns), 1),
    }
