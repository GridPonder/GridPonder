"""Turn an agent name from harness.yaml into a command to run in the sandbox.

`--agent-cmd` takes a literal command, which is right for one-off debugging and
useless for a sweep: harness.yaml says `harness: claude`, and something has to
know what that means. That mapping lives here, along with the parsing of
whatever the agent prints about its own token use.

Adapters are deliberately thin. An adapter decides how to *invoke* a model, not
how to play — the rules reach the agent through RULES.md and the socket, the
same way for every adapter, so two harnesses stay comparable.
"""
from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path

_HARNESS_DIR = Path(__file__).resolve().parent

# The whole briefing. Deliberately says nothing about the puzzle: naming the
# mechanics here would leak through every adapter at once and be invisible in
# the results, since RULES.md is what gets archived with a run.
PROMPT = """\
You are playing a puzzle game in this directory.

Read RULES.md first. It tells you the goal, the commands, and the exact JSON
shape of every action. Then play, using only the ./play command:

    ./play state          show the board
    ./play move '<json>'  make one move
    ./play history        list your moves this attempt
    ./play give_up        restart from the beginning

Nothing else in this directory will help you and there is no other source of
information. Work out the rules by looking at the board and trying moves.

Keep playing until ./play tells you the run is over. Do not stop early, do not
ask for confirmation, and do not write any files.\
"""

# Narration is deliberately *not* here. Asking in the launch prompt was tried
# and does not work: Claude Code routes the answer into thinking blocks, whose
# contents the stream strips, so the request produces nothing readable. It also
# would only ever reach this one adapter. The reason now travels as an optional
# second argument to `./play move`, documented in RULES.md — which every
# adapter reads, and which no CLI can redact. See rules._NARRATION.


@dataclass
class AgentSpec:
    """How to launch one agent, and how to read what it reports back."""

    name: str
    argv: list[str]
    # Host paths to expose read-write inside the sandbox (API keys, session
    # state). Anything listed is fully visible to the agent, so it must never
    # include the pack tree.
    credentials: list[Path] = field(default_factory=list)
    # Host paths bound read-only, for an agent whose own program lives in this
    # repo: under confinement the repo is as invisible as the pack, so the
    # script has to be handed in explicitly. Same rule as credentials — never
    # anything under the pack tree.
    tools: list[Path] = field(default_factory=list)
    # Environment the agent needs that the sandbox would otherwise strip.
    env: dict[str, str] = field(default_factory=dict)
    # Set when the adapter prints a machine-readable trailer we can mine for
    # token counts and cost.
    parses_usage: bool = False
    # Whether the model name means anything to this agent. Recorded on the
    # run so a report never labels a local script with whatever model the
    # config happened to name.
    uses_model: bool = False


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def claude_agent(*, model: str | None = None, prompt: str = PROMPT,
                 seed: int = 0, thinking_tokens: int = 0,
                 narrate: bool = False) -> AgentSpec:
    """Claude Code in headless mode.

    Permission prompts are bypassed because there is no one to answer them, and
    the tool list is narrowed to what playing actually needs. The confinement
    that matters is the sandbox, not the tool allowlist: an agent with Bash can
    read any file it can reach, which is the point of isolation.py.
    """
    # `seed` is accepted and ignored: a hosted model has no seed to set, and
    # every adapter takes the same arguments so the sweep does not have to know
    # which knobs a given agent happens to support.
    #
    # stream-json rather than json: the single-object form reports only the
    # final tally, which cannot say *where* a run went wrong. The stream keeps
    # every assistant message, so a rejection or a lost attempt can be lined up
    # against what the agent was reasoning about immediately before it.
    argv = [
        "claude", "-p", prompt,
        "--output-format", "stream-json", "--verbose",
        "--permission-mode", "bypassPermissions",
        "--allowed-tools", "Bash", "Read",
    ]
    if model:
        argv += ["--model", model]

    env = {}
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        if os.environ.get(key):
            env[key] = os.environ[key]

    # Available, but it makes the transcript *worse*, so it defaults off.
    # Forcing a thinking budget moves the model's reasoning into thinking
    # blocks, and the CLI strips those to an empty string plus a signature
    # before we ever see them. Measured on tk_008: without a budget, 28 text
    # blocks totalling 2,349 characters of narration; with MAX_THINKING_TOKENS
    # set, 0 text blocks and 0 characters. The knob is kept because it is a
    # real property of the run — an agent that thinks more may play better —
    # but reach for `narrate` if the goal is a readable transcript.
    if thinking_tokens > 0:
        env["MAX_THINKING_TOKENS"] = str(thinking_tokens)

    # The credential file and the settings file, never the whole ~/.claude
    # directory. That directory carries every past session's transcript, and on
    # a repo whose sessions discuss gold paths those transcripts *are* the
    # answers — an agent with Bash could grep them out of its own tool's
    # history and "solve" a level it never played. isolation.wrap tmpfs's any
    # directory listed here for the same reason, but the narrower list is what
    # makes that a backstop instead of the only defence.
    home = _home()
    credentials = [p for p in (home / ".claude" / ".credentials.json",
                               home / ".claude.json") if p.exists()]
    # The CLI still needs somewhere to write session state.
    if (home / ".claude").is_dir():
        credentials.insert(0, home / ".claude")

    return AgentSpec(
        name="claude",
        argv=argv,
        credentials=credentials,
        env=env,
        parses_usage=True,
        uses_model=True,
    )


def baseline_agent(*, seed: int = 0, model: str | None = None,
                   prompt: str = PROMPT, thinking_tokens: int = 0,
                   narrate: bool = False) -> AgentSpec:
    """A free, deterministic explorer used to exercise the pipeline.

    It reads RULES.md, extracts the action shapes, and plays semi-random legal
    JSON until the run ends. It solves almost nothing, which is the point: it
    produces losses, retries and rejections on demand, so the sweep and the
    report can be validated without spending tokens or waiting on a model.
    """
    script = _HARNESS_DIR / "baseline_agent.py"
    return AgentSpec(
        name="baseline",
        argv=["/usr/bin/python3", str(script), "--seed", str(seed)],
        # Bound in rather than copied into the sandbox: the sandbox directory
        # is part of what the agent is measured on, and an extra file there
        # would be one more thing a real agent could find.
        tools=[script],
        parses_usage=False,
    )


_REGISTRY = {
    "claude": claude_agent,
    "baseline": baseline_agent,
}


def build(name: str, **kwargs) -> AgentSpec:
    if name not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"unknown agent {name!r}; known agents: {known}")
    return _REGISTRY[name](**kwargs)


def known_agents() -> list[str]:
    return sorted(_REGISTRY)


def iter_events(stdout: str):
    """Yield the JSON objects an agent streamed, skipping anything else.

    `--output-format stream-json` emits one object per line. Non-JSON lines are
    dropped rather than raising: a CLI banner or a warning is not a reason to
    lose a run's whole transcript.
    """
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def reasoning_timeline(stdout: str) -> list[dict]:
    """The agent's own narration, in order, paired with the moves it made.

    Each entry is one assistant message: its text, and any ./play commands it
    ran. That is what lets a rejection or a lost attempt be attributed to a
    line of reasoning rather than just reported as a counter.
    """
    timeline = []
    for event in iter_events(stdout):
        if event.get("type") != "assistant":
            continue
        message = event.get("message") or {}
        text_parts, commands = [], []
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text", "").strip():
                text_parts.append(block["text"].strip())
            elif block.get("type") == "thinking" and block.get("thinking"):
                text_parts.append(block["thinking"].strip())
            elif block.get("type") == "tool_use":
                command = (block.get("input") or {}).get("command")
                if isinstance(command, str):
                    commands.append(command)
        if text_parts or commands:
            timeline.append({
                "text": "\n\n".join(text_parts),
                "commands": commands,
            })
    return timeline


def parse_usage(stdout: str) -> dict:
    """Pull token counts and cost out of an agent's own report.

    Best-effort by design: an adapter that reports nothing usable yields an
    empty dict, and the report shows the run without cost rather than refusing
    to show it. Never inferred or estimated — a made-up cost is worse than a
    blank column.

    Handles both output shapes: one JSON object, or a stream whose final
    `result` event carries the tally.
    """
    text = stdout.strip()
    if not text:
        return {}
    payload = None
    for event in iter_events(text):
        if event.get("type") == "result":
            payload = event
    if payload is None:
        # Single-object form: tolerate anything the CLI printed around it.
        start = text.find("{")
        if start < 0:
            return {}
        try:
            candidate = json.loads(text[start:])
        except ValueError:
            return {}
        if not isinstance(candidate, dict):
            return {}
        payload = candidate

    usage = payload.get("usage") or {}
    out = {}
    if isinstance(usage, dict):
        for key in ("input_tokens", "output_tokens",
                    "cache_read_input_tokens", "cache_creation_input_tokens"):
            if isinstance(usage.get(key), int):
                out[key] = usage[key]
    for src, dst in (("total_cost_usd", "cost_usd"),
                     ("num_turns", "turns"),
                     ("duration_ms", "agent_duration_ms")):
        if isinstance(payload.get(src), (int, float)):
            out[dst] = payload[src]
    if isinstance(payload.get("is_error"), bool):
        out["agent_reported_error"] = payload["is_error"]
    return out


def describe(spec: AgentSpec) -> str:
    return " ".join(shlex.quote(a) for a in spec.argv)
