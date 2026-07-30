#!/usr/bin/env python3
"""Run one level as a sandboxed agent session.

This is the piece that closes the loop. It owns the game and the sandbox; the
agent owns nothing but a directory containing RULES.md and ./play.

    supervisor                          sandbox/
    ├── loads the pack                  ├── RULES.md   (generated, per level)
    ├── spawns runner.py --observation  ├── play       (copied, stdlib only)
    │   harness                         └── .play.sock (bound by the supervisor)
    ├── binds .play.sock
    ├── writes RULES.md + play
    └── launches the agent with cwd=sandbox

Every ./play invocation is one connect → one request → one response → close.
The agent never sees the pack, the gold path, the action limit, or the list of
currently legal moves; it sees the board, the goal, and the action shapes.

Scope: one level, one agent, one process. Sweeping levels across harnesses and
models — harness.yaml's `tier1`/`tier2`/`concurrency` blocks — is a separate
orchestrator that calls this one; only `thresholds` is read here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

_HARNESS_DIR = Path(__file__).resolve().parent
_BENCH_DIR = _HARNESS_DIR.parent
_REPO_ROOT = _BENCH_DIR.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from engines.python.loader import load_pack  # noqa: E402
from engines.python.anon import (  # noqa: E402
    build_anon_action_shapes,
    build_anon_kind_to_label,
    resolve_anon_action,
)
from engines.python.goal_renderer import render_goals  # noqa: E402
from engines.python._turn_engine import TurnEngine  # noqa: E402
from tools.benchmark.harness import agents, isolation, metrics, protocol  # noqa: E402
from tools.benchmark.harness.rules import build_rules  # noqa: E402

SOCK_NAME = ".play.sock"
_ACCEPT_POLL_SECONDS = 0.2
# Linux caps sun_path at 108 bytes including the terminator. Leave room rather
# than sitting on the edge.
_SOCK_PATH_MAX = 100
_USAGE = "usage: ./play state | move '<json>' | history | give_up"
# Printed immediately before the run summary, so a caller reading stdout can
# tell the agent's transcript from the supervisor's own report.
RESULT_MARKER = "=== run result ==="

# Why the board just went back to the start. The agent is told this much and
# no more: that an attempt ended, not which rule ended it.
_RESET_TEXT = {
    "lost": "You lost that attempt. The board is back to its starting position.",
    "limit": "That attempt ran out of actions. The board is back to its "
             "starting position.",
    "voluntary": "Attempt abandoned. The board is back to its starting position.",
}


class Session:
    """One level, one agent. Owns the runner subprocess and the run's counters."""

    def __init__(self, pack_dir: Path, level_id: str, *, anon: bool = False,
                 max_attempts: int = 1, trace: bool = False,
                 full_attempts: bool = False, narrate: bool = False):
        self.pack_dir = pack_dir
        self.level_id = level_id
        self.anon = anon
        self.max_attempts = max(1, max_attempts)
        self.trace = trace
        # Every attempt gets the level's own budget instead of sharing one
        # gold-path multiple between them. See runner.py --full-attempts.
        self.full_attempts = full_attempts
        # Document the optional reason argument on `move` in RULES.md.
        self.narrate = narrate

        self.game_def, levels = load_pack(str(pack_dir))
        if level_id not in levels:
            raise SystemExit(f'level "{level_id}" not found in {pack_dir}')
        self.level_def = levels[level_id]

        # Supervisor-side only. The gold path scores the run; it is never
        # rendered into the sandbox, and RULES.md is built without it.
        self.gold_path: list[dict] = list(
            self.level_def.get("solution", {}).get("goldPath", [])
        )

        self.anon_shapes: list[dict] | None = None
        self.anon_table: dict[str, dict] = {}
        if anon:
            self.anon_shapes, self.anon_table = build_anon_action_shapes(
                self.game_def
            )

        self.proc: subprocess.Popen | None = None
        self.state: dict[str, Any] = {}
        # What the agent typed, echoed back by ./play history. Stays aliased on
        # an anonymous run: de-aliasing it here would hand back the mapping the
        # run exists to withhold.
        self.history: list[dict] = []
        # first_divergence compares the agent's *first* attempt against the
        # gold path, so stop recording once the board has been reset. Scored
        # supervisor-side, so these are stored in real ids — see _scoring_form.
        self.first_attempt_moves: list[dict] = []
        self.past_first_attempt = False
        self.rejected_schema = 0
        self.rejected_illegal = 0
        # Attempts the agent lost outright. Counted from reset events so that a
        # loss the agent recovered from still shows up, not just the last one.
        self.losses = 0
        self.terminal: dict[str, Any] | None = None

        # Transcript. Written from the serve thread, so it needs a lock even
        # though only one ./play call is served at a time — nothing guarantees
        # that stays true.
        self.transcript = None
        self._transcript_lock = threading.Lock()
        self.turn_seq = 0
        self.opened_at = time.monotonic()
        # Set by _submit when the turn just served reset the board, so the
        # transcript can file it under the attempt it actually ran in.
        self._turn_reset = False
        # The reason the agent gave for the move being served, if it gave one.
        self._turn_why = ""

    def open_transcript(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.transcript = path.open("w", encoding="utf-8")
        self.opened_at = time.monotonic()

    def close_transcript(self) -> None:
        if self.transcript is not None:
            self.transcript.close()
            self.transcript = None

    # ── runner plumbing ──────────────────────────────────────────────────

    def start(self, packs_dir: Path) -> None:
        argv = [
            sys.executable, str(_BENCH_DIR / "runner.py"),
            "--pack", self.pack_dir.name,
            "--level", self.level_id,
            "--packs-dir", str(packs_dir),
            "--observation", "harness",
            "--mode", "single",
            "--max-attempts", str(self.max_attempts),
        ]
        if self.anon:
            argv.append("--anon")
        if self.full_attempts:
            argv.append("--full-attempts")
        self.proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
        )
        self._pump()  # initial state event

    def _read_event(self) -> dict | None:
        assert self.proc is not None and self.proc.stdout is not None
        line = self.proc.stdout.readline()
        if not line:
            return None
        return json.loads(line)

    def _pump(self) -> list[dict]:
        """Read runner events up to the next state or terminal event."""
        seen: list[dict] = []
        while True:
            event = self._read_event()
            if event is None:
                # The runner died. Treat it as a lost run rather than hanging
                # the agent on a socket that will never answer.
                self.terminal = {"event": "lost", "reason": "runner exited"}
                return seen
            seen.append(event)
            kind = event.get("event")
            if kind == "rejected":
                if event.get("reason") == "schema":
                    self.rejected_schema += 1
                else:
                    self.rejected_illegal += 1
            elif kind == "reset":
                self.history.clear()
                self.past_first_attempt = True
                if event.get("reason") == "lost":
                    self.losses += 1
            elif kind == "state":
                self.state = event
                return seen
            elif kind in ("won", "lost"):
                self.terminal = event
                return seen

    def stop(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            try:
                assert self.proc.stdin is not None
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)

    # ── rendering ────────────────────────────────────────────────────────

    def render_state(self) -> str:
        if not self.state:
            return "No board yet."
        s = self.state
        lines = [
            f"Attempt {s['attempt']} — {s['moves_this_attempt']} action(s) this attempt, "
            f"{s['actions_total']} total.",
            "",
            f"Goal: {s['goals']}",
            "",
            s["board_text"],
        ]
        if s.get("inventory"):
            lines += ["", f"Carrying: {s['inventory']}"]
        return "\n".join(lines)

    def render_history(self) -> str:
        if not self.history:
            return "No actions this attempt yet."
        return "\n".join(
            f"{i + 1}. {json.dumps(a)}" for i, a in enumerate(self.history)
        )

    def terminal_text(self) -> str:
        assert self.terminal is not None
        if self.terminal.get("event") == "won":
            return (
                f"Solved in {self.terminal['actions_total']} action(s) across "
                f"{self.terminal['attempts']} attempt(s). The run is over."
            )
        return "The run is over. No further moves are possible."

    # ── verbs ────────────────────────────────────────────────────────────

    def handle(self, verb: str, args: list[str]) -> tuple[str, bool]:
        """One ./play call, start to finish, with the transcript entry for it.

        Logged here rather than deeper down so every path is covered: a verb
        the agent got wrong, a move rejected before the runner saw it, and a
        move that played all produce a record. Reading a run afterwards is the
        whole point — "it scored 38 actions" says nothing about where it went
        wrong, and that is the question the transcript exists to answer.
        """
        started = time.monotonic()
        before = (self.rejected_schema, self.rejected_illegal, self.losses)
        # Snapshot the position this command was issued *from*. A move that
        # loses the attempt triggers a reset, and by the time we log it
        # self.state already describes the fresh board — which would file the
        # losing move under the attempt that came after it.
        was = (self.state.get("attempt"), self.state.get("actions_total"),
               self.state.get("moves_this_attempt"))

        if self.terminal is not None:
            text, terminal = self.terminal_text(), True
        elif verb == "state":
            text, terminal = self.render_state(), False
        elif verb == "history":
            text, terminal = self.render_history(), False
        elif verb == "give_up":
            text, terminal = self._submit({"action": "give_up"}, record=False)
        elif verb == "move":
            text, terminal = self._move(args)
        else:
            text, terminal = _USAGE, False

        self._log_turn(verb, args, text, terminal, started, before, was)
        self._turn_reset = False
        self._turn_why = ""
        return text, terminal

    def _log_turn(self, verb: str, args: list[str], text: str, terminal: bool,
                  started: float, before: tuple[int, int, int],
                  was: tuple) -> None:
        if self.transcript is None:
            return
        schema, illegal, losses = before
        was_attempt, was_total, was_in_attempt = was
        lost = self.losses > losses
        # A give_up ends an attempt without losing it, and resets the board
        # just the same, so it needs the same re-attribution.
        reset = self._turn_reset
        played = verb in ("move", "give_up") and not (
            self.rejected_schema > schema or self.rejected_illegal > illegal)
        entry = {
            "seq": self.turn_seq,
            "elapsed": round(time.monotonic() - self.opened_at, 2),
            "took": round(time.monotonic() - started, 2),
            "verb": verb,
            "args": args,
            # What the agent said it was doing, in its own words, recorded
            # against the move it applies to rather than inferred afterwards.
            "why": self._turn_why,
            # The attempt this command ran in, and the action count after
            # it. On a losing move the board has already reset, so these
            # come from the snapshot plus the action just spent.
            "attempt": (was_attempt if reset else self.state.get("attempt")),
            "actions_total": (
                (was_total or 0) + 1 if reset
                else (self.terminal or self.state).get("actions_total")),
            "actions_this_attempt": (
                (was_in_attempt or 0) + 1 if reset
                else (self.terminal.get("actions_this_attempt")
                      if self.terminal
                      else self.state.get("moves_this_attempt"))),
            "played_action": played,
            # What this particular call cost the agent, so a reader does not
            # have to diff running totals to find where things went wrong.
            "rejected_schema": self.rejected_schema - schema,
            "rejected_illegal": self.rejected_illegal - illegal,
            "lost_attempt": lost,
            "terminal": terminal,
            "response": text,
        }
        self.turn_seq += 1
        with self._transcript_lock:
            self.transcript.write(json.dumps(entry) + "\n")
            self.transcript.flush()

    def _move(self, args: list[str]) -> tuple[str, bool]:
        if not 1 <= len(args) <= 2:
            return self._schema_error(
                "move takes the action as quoted JSON, and optionally one "
                "short line saying why you are making it."
            )
        # The reason travels with the move rather than being scraped out of the
        # agent's own output stream. Claude Code strips the contents of its
        # thinking blocks, so a model that reasons silently leaves a transcript
        # of moves with no reasons attached to any of them; a protocol field
        # cannot be redacted, arrives at exactly the moment it applies, and
        # works the same way for every harness. Never required — making it
        # required would turn a missing rationale into a schema rejection and
        # corrupt the one counter that is supposed to mean "the agent could not
        # express itself".
        self._turn_why = args[1].strip() if len(args) == 2 else ""
        try:
            action = json.loads(args[0])
        except ValueError as exc:
            return self._schema_error(f"That is not valid JSON ({exc}).")
        if not isinstance(action, dict):
            return self._schema_error("An action must be a JSON object.")
        if action.get("action") == "give_up":
            # Routing this to the runner would silently restart the attempt.
            # give_up is a ./play verb, not an action; say so.
            return self._schema_error("To restart the attempt, run ./play give_up.")
        return self._submit(action, record=True)

    def _schema_error(self, message: str) -> tuple[str, bool]:
        """A rejection the supervisor can see without asking the runner.

        Counted with the runner's schema rejections: from the agent's side
        "my JSON was wrong" is one failure mode, wherever it was caught.
        """
        self.rejected_schema += 1
        return f"Rejected: {message}\n\n{self.render_state()}", False

    def _scoring_form(self, action: dict) -> dict:
        """The action as the gold path spells it.

        The gold path is written in real ids, so an anonymous run has to be
        translated back before it can be compared: otherwise a flawless anon
        run diverges at move 0 purely because it said `a1` where the gold path
        says `move`. The runner accepted this action, so the alias resolves;
        the fallback only guards against the two drifting apart.
        """
        if not self.anon_table:
            return action
        return resolve_anon_action(self.anon_table, action) or action

    def _trace(self, action: dict, outcome: str) -> None:
        """One line per move, on stderr, as it happens.

        A hosted agent can think for many minutes between moves, and with the
        summary only printed at the end a live run is indistinguishable from a
        hung one. stderr keeps it out of the transcript the anonymity checks
        read.
        """
        if not self.trace:
            return
        print(
            f"[{self.pack_dir.name}/{self.level_id}] "
            f"attempt {self.state.get('attempt', '?')} "
            f"action {self.state.get('actions_total', '?')}: "
            f"{json.dumps(action)} -> {outcome}",
            file=sys.stderr, flush=True,
        )

    def _submit(self, action: dict, *, record: bool) -> tuple[str, bool]:
        assert self.proc is not None and self.proc.stdin is not None
        was_first_attempt = not self.past_first_attempt
        self.proc.stdin.write(json.dumps(action) + "\n")
        self.proc.stdin.flush()
        events = self._pump()
        self._turn_reset = any(e.get("event") == "reset" for e in events)

        rejections = [e for e in events if e.get("event") == "rejected"]
        self._trace(action, rejections[0].get("reason", "illegal") if rejections
                    else (self.terminal or {}).get("event", "ok"))
        if rejections:
            reason = rejections[0].get("reason", "illegal")
            detail = rejections[0].get("detail", "")
            lead = (
                "Rejected — that JSON does not match any action shape"
                if reason == "schema"
                else "Rejected — not a legal move in this position"
            )
            body = f"{lead}: {detail}"
        else:
            resets = [e for e in events if e.get("event") == "reset"]
            was_reset = bool(resets)
            # Say why the board changed under them. An attempt that silently
            # reverts looks like the move did something strange, and the agent
            # spends the next turns re-deriving a position it never left.
            body = _RESET_TEXT.get(resets[-1].get("reason"), "") if resets else ""
            if record:
                # A move that tripped the per-attempt limit belongs to the
                # attempt that just ended, whose history _pump already cleared.
                if not was_reset:
                    self.history.append(action)
                if was_first_attempt:
                    self.first_attempt_moves.append(self._scoring_form(action))

        if self.terminal is not None:
            text = self.terminal_text()
            return (f"{body}\n\n{text}" if body else text), True
        return (f"{body}\n\n{self.render_state()}" if body else self.render_state()), False

    # ── results ──────────────────────────────────────────────────────────

    def result(self, thresholds: dict) -> dict:
        term = self.terminal or {}
        solved = term.get("event") == "won"
        # An agent that times out, crashes, or simply stops leaves no terminal
        # event. Fall back to the last state rather than defaulting to zero:
        # reporting actions_total 0 for a run that made moves would read as a
        # perfectly efficient failure and skew whatever consumes these numbers.
        run = {
            "pack_id": self.pack_dir.name,
            "level_id": self.level_id,
            "anon": self.anon,
            "solved": solved,
            "actions_total": term.get(
                "actions_total", self.state.get("actions_total", 0)
            ),
            "attempts": term.get("attempts", self.state.get("attempt", 1)),
            "max_attempts": self.max_attempts,
            "full_attempts": self.full_attempts,
            # The runner counts a loss only for a real lose condition, so this
            # excludes the terminal `lost` it also emits for five bad payloads
            # in a row or an exhausted action budget. The supervisor's own
            # reset-derived tally is the fallback for a run with no terminal
            # event at all, where the runner never got to report.
            "losses": term.get("losses", self.losses),
            "gold_path_length": term.get("gold_path_length", len(self.gold_path)),
            "repeated_states": term.get("repeated_states", 0),
            "rejected_schema": self.rejected_schema,
            "rejected_illegal": self.rejected_illegal,
            "reached_terminal": self.terminal is not None,
        }
        run["efficiency"] = metrics.efficiency(
            run["actions_total"], run["gold_path_length"]
        )
        run["first_divergence"] = metrics.first_divergence(
            self.first_attempt_moves, self.gold_path
        )
        run["tier"] = metrics.classify(run, thresholds)
        return run


def build_sandbox(session: Session, sandbox: Path) -> Path:
    """Write RULES.md and ./play into a fresh sandbox. Returns the socket path."""
    sandbox.mkdir(parents=True, exist_ok=True)

    kind_to_label = (
        build_anon_kind_to_label(session.game_def) if session.anon else None
    )
    # A throwaway engine purely to render the opening goal text; goals can read
    # state (sequence progress), and the session's own runner owns the live one.
    goals_text = render_goals(
        session.level_def,
        TurnEngine(session.game_def, session.level_def).state,
        session.game_def,
        anonymize=session.anon,
        kind_to_label=kind_to_label,
    )
    (sandbox / "RULES.md").write_text(
        build_rules(
            session.game_def,
            session.level_def,
            goals_text=goals_text,
            actions=session.anon_shapes,
            anonymized=session.anon,
            narrate=session.narrate,
        ),
        encoding="utf-8",
    )

    sock_path = _socket_path(sandbox)
    play_src = (_HARNESS_DIR / "play").read_text(encoding="utf-8")
    play_dst = sandbox / "play"
    play_dst.write_text(
        play_src.replace('SOCK_PATH = ""', f"SOCK_PATH = {str(sock_path)!r}", 1),
        encoding="utf-8",
    )
    play_dst.chmod(0o755)

    if sock_path.exists():
        sock_path.unlink()
    return sock_path


def _socket_path(sandbox: Path) -> Path:
    """Where to bind this session's socket.

    Normally beside `play`, which keeps a hand-built sandbox self-contained.
    AF_UNIX paths are capped near 108 bytes, though, and a sweep nests one
    sandbox per level under an output directory, which overruns it easily. Past
    the limit the socket moves to a short path derived from the sandbox, so the
    name still says which session owns it and two sweeps cannot collide.
    """
    default = sandbox / SOCK_NAME
    if len(str(default).encode()) < _SOCK_PATH_MAX:
        return default
    digest = hashlib.sha256(str(sandbox).encode()).hexdigest()[:12]
    # XDG_RUNTIME_DIR ahead of /tmp: it is per-user, just as short, and unlike
    # /tmp it is still the host's own directory when the docker daemon runs
    # with a private /tmp — where binding /tmp/... silently mounts an empty one
    # and the agent finds no socket at all.
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    root = (Path(runtime) if runtime and Path(runtime).is_dir()
            else Path(tempfile.gettempdir()))
    short_dir = root / f"gp-{digest}"
    short_dir.mkdir(parents=True, exist_ok=True)
    return short_dir / "p.sock"


def bind_socket(sock_path: Path) -> socket.socket:
    """Bind and listen, in the caller's thread.

    Deliberately not left to the serve thread. A bind that failed there raised
    into a thread nobody was watching, the agent found no socket, and the run
    was still scored — as a legitimate zero, indistinguishable from an agent
    that played and got nowhere. A transport that never came up has to be an
    error, so it is raised where it can stop the run.
    """
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(sock_path))
    except OSError as exc:
        server.close()
        raise SystemExit(f"cannot bind {sock_path}: {exc}") from exc
    server.listen(8)
    server.settimeout(_ACCEPT_POLL_SECONDS)
    return server


def serve(session: Session, server: socket.socket, sock_path: Path,
          stop: threading.Event) -> None:
    """Accept ./play connections until `stop` is set."""
    try:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            with conn:
                _serve_one(session, conn)
    finally:
        server.close()
        if sock_path.exists():
            sock_path.unlink()


def _serve_one(session: Session, conn: socket.socket) -> None:
    conn.settimeout(30.0)
    chunks: list[bytes] = []
    try:
        while not chunks or not chunks[-1].endswith(b"\n"):
            chunk = conn.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    except socket.timeout:
        return
    raw = b"".join(chunks).strip()
    if not raw:
        return

    try:
        verb, args = protocol.decode_request(raw)
    except protocol.ProtocolError as exc:
        # A closed protocol: anything that is not one of the four verbs gets
        # the usage line, never a stack trace and never a partial game action.
        print(f"[supervisor] refused request: {exc}", file=sys.stderr)
        conn.sendall(protocol.encode_response(_USAGE))
        return

    text, terminal = session.handle(verb, args)
    conn.sendall(protocol.encode_response(text, terminal=terminal))


def load_config(config_path: Path) -> dict:
    import yaml

    return yaml.safe_load(config_path.read_text()) or {}


def load_thresholds(config_path: Path) -> dict:
    return load_config(config_path).get("thresholds", {})


def main() -> int:
    parser = argparse.ArgumentParser(description="Sandboxed agent session for one level")
    parser.add_argument("--pack", required=True)
    parser.add_argument("--level", required=True)
    parser.add_argument("--packs-dir", required=True)
    parser.add_argument("--sandbox", required=True, help="Directory handed to the agent")
    parser.add_argument("--anon", action="store_true", default=False)
    parser.add_argument("--config", default=str(_HARNESS_DIR / "harness.yaml"))
    parser.add_argument("--result", default=None, help="Where to write result JSON")
    parser.add_argument(
        "--transcript", default=None,
        help="Write a JSONL record of every ./play call, and alongside it "
             "<name>.agent.jsonl with the agent's own reasoning stream. "
             "This is what makes a run diagnosable after the fact.",
    )
    parser.add_argument(
        "--max-attempts", type=int, default=None,
        help="Attempts before the run ends. Defaults to run.max_attempts in "
             "the config, or 1 (a loss ends the run).",
    )
    parser.add_argument(
        "--full-attempts", dest="full_attempts", action="store_true",
        default=None,
        help="Give every attempt the level's own action budget rather than "
             "sharing one gold-path multiple across all of them. Defaults to "
             "run.full_attempts in the config.",
    )
    parser.add_argument(
        "--shared-budget", dest="full_attempts", action="store_false",
        help="Opposite of --full-attempts: one action budget spanning every "
             "attempt.",
    )
    parser.add_argument(
        "--agent", default=None,
        help=f"Named agent to launch: {', '.join(agents.known_agents())}. "
             "Mutually exclusive with --agent-cmd.",
    )
    parser.add_argument("--model", default=None, help="Model for --agent, if it takes one")
    parser.add_argument(
        "--narrate", dest="narrate", action="store_true", default=None,
        help="Ask the agent to write one line of reasoning before each "
             "command. Claude Code's stream strips thinking blocks, so this is "
             "the only way to record why a move was made. It nudges the agent, "
             "so it is recorded on the run. Defaults to run.narrate.",
    )
    parser.add_argument(
        "--no-narrate", dest="narrate", action="store_false",
        help="Let the agent narrate only when it chooses to.",
    )
    parser.add_argument(
        "--thinking-tokens", type=int, default=None,
        help="Force a per-turn thinking budget on agents that support one, so "
             "the transcript records why each move was made rather than only "
             "which moves were made. Defaults to run.thinking_tokens; 0 takes "
             "whatever the model volunteers.",
    )
    parser.add_argument(
        "--seed", type=int, default=0,
        help="Seed for agents that have one. Ignored by hosted models, "
             "which is why repeats of those still differ.",
    )
    parser.add_argument(
        "--isolation", choices=list(isolation.MODES), default="bwrap",
        help="How the agent is confined. 'bwrap' hides everything but the "
             "sandbox, so the pack and gold path are unreachable. 'docker' "
             "starts from an image instead, so the host filesystem is absent "
             "by construction and memory/CPU/network can be capped. 'none' "
             "runs the agent with your own filesystem view, which makes any "
             "score unverifiable — debugging only.",
    )
    parser.add_argument("--docker-image", default=None,
                        help=f"Image for --isolation docker (default "
                             f"{isolation.DEFAULT_IMAGE}).")
    parser.add_argument("--docker-network", default=None,
                        help="Container network: 'bridge' (default) or 'none' "
                             "to cut egress entirely, which only works for an "
                             "agent that does not call a hosted model.")
    parser.add_argument("--docker-memory", default=None, help="e.g. 2g")
    parser.add_argument("--docker-cpus", default=None, help="e.g. 2")
    parser.add_argument(
        "--agent-cmd", nargs=argparse.REMAINDER, default=None,
        help="Command to run inside the sandbox. Everything after this flag.",
    )
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument(
        "--trace", action="store_true", default=False,
        help="Print each move to stderr as it happens. A hosted model can think for minutes between moves, and without this a live run looks identical to a hung one.",
    )
    args = parser.parse_args()

    if args.agent and args.agent_cmd:
        parser.error("--agent and --agent-cmd are mutually exclusive")

    config = load_config(Path(args.config))
    thresholds = config.get("thresholds", {})
    run_config = config.get("run", {})
    max_attempts = (
        args.max_attempts if args.max_attempts is not None
        else int(run_config.get("max_attempts", 1))
    )
    full_attempts = (
        args.full_attempts if args.full_attempts is not None
        else bool(run_config.get("full_attempts", False))
    )
    thinking_tokens = (
        args.thinking_tokens if args.thinking_tokens is not None
        else int(run_config.get("thinking_tokens", 0))
    )
    narrate = (
        args.narrate if args.narrate is not None
        else bool(run_config.get("narrate", False))
    )

    docker_cfg = config.get("docker", {})
    iso_kwargs = {}
    if args.isolation == "docker":
        iso_kwargs = {
            "image": args.docker_image or docker_cfg.get(
                "image", isolation.DEFAULT_IMAGE),
            "network": args.docker_network or docker_cfg.get("network", "bridge"),
            "memory": args.docker_memory or docker_cfg.get("memory"),
            "cpus": args.docker_cpus or docker_cfg.get("cpus"),
        }

    packs_dir = Path(args.packs_dir).resolve()
    session = Session(packs_dir / args.pack, args.level, anon=args.anon,
                      max_attempts=max_attempts, trace=args.trace,
                      full_attempts=full_attempts, narrate=narrate)
    sandbox = Path(args.sandbox).resolve()
    sock_path = build_sandbox(session, sandbox)
    transcript_path = Path(args.transcript) if args.transcript else None
    if transcript_path:
        session.open_transcript(transcript_path)
    # Bind before anything else can consume time or tokens: if the transport
    # is broken there is no run to have, and finding that out after launching a
    # model is finding out too late.
    server = bind_socket(sock_path)

    spec: agents.AgentSpec | None = None
    if args.agent:
        spec = agents.build(args.agent, model=args.model, seed=args.seed,
                            thinking_tokens=thinking_tokens, narrate=narrate)
        agent_argv = spec.argv
    else:
        agent_argv = args.agent_cmd

    # One mount configuration, used for both the check and the launch. Checking
    # a different one than the agent gets is how a confinement passes its own
    # audit and still leaks — or, as happened here, fails an audit it would
    # have passed.
    mounts = dict(
        credentials=(spec.credentials if spec else None),
        tools=(spec.tools if spec else None),
        # Only when the socket had to move out of the sandbox; otherwise the
        # sandbox mount already carries it.
        writable=([sock_path.parent] if sock_path.parent != sandbox else None),
        **iso_kwargs,
    )

    if agent_argv and args.isolation != "none":
        # Check the confinement against the pack we are about to score, not in
        # the abstract. A widened mount list would otherwise fail silently and
        # every number below it would be worthless.
        isolation.verify(sandbox, packs_dir / args.pack,
                         mode=args.isolation,
                         # The socket can sit outside the sandbox when the path
                         # is too long for AF_UNIX; an agent that cannot reach
                         # it scores zero without anything failing.
                         must_be_visible=[sock_path],
                         **mounts)

    session.start(packs_dir)

    stop = threading.Event()
    server_thread = threading.Thread(
        target=serve, args=(session, server, sock_path, stop), daemon=True
    )
    server_thread.start()

    agent_rc: int | None = None
    usage: dict = {}
    started = time.monotonic()
    if agent_argv:
        env = dict(os.environ)
        env["PLAY_SANDBOX"] = str(sandbox)
        env.update(spec.env if spec else {})
        # env is passed to the launch but not to verify(): it is not a mount, so
        # it cannot widen what the agent can read, and docker would otherwise
        # start the agent with no credentials at all.
        argv = isolation.wrap(
            agent_argv, sandbox=sandbox, mode=args.isolation,
            env=(spec.env if spec else None), **mounts)
        # Streamed straight to disk rather than buffered in memory. On a
        # timeout subprocess.run throws away everything it captured, and the
        # reasoning behind a run that had to be killed is precisely the
        # reasoning worth reading — a long run would lose its whole transcript
        # at the one moment it most needed one. Raw, not parsed: the shape of
        # these events belongs to the CLI, and a run already paid for should
        # not become unreadable because our parser aged out.
        stream_path = (transcript_path.with_suffix(".agent.jsonl")
                       if transcript_path else None)
        stream_file = stream_path.open("w", encoding="utf-8") if stream_path else None
        stdout_text = ""
        try:
            proc = subprocess.run(
                argv, cwd=str(sandbox), env=env, timeout=args.timeout,
                stdout=(stream_file or subprocess.PIPE),
                stderr=subprocess.PIPE, text=True,
            )
            agent_rc = proc.returncode
            stdout_text = proc.stdout or ""
            if proc.stderr:
                print(proc.stderr, file=sys.stderr)
        except subprocess.TimeoutExpired as exc:
            agent_rc = -1
            print("[supervisor] agent timed out", file=sys.stderr)
            if exc.stdout:
                stdout_text = (exc.stdout if isinstance(exc.stdout, str)
                               else exc.stdout.decode("utf-8", "replace"))
        finally:
            if stream_file is not None:
                stream_file.close()
        if stream_path is not None and stream_path.is_file():
            stdout_text = stream_path.read_text(encoding="utf-8")
        if stdout_text:
            print(stdout_text)
            if spec and spec.parses_usage:
                usage = agents.parse_usage(stdout_text)
    else:
        print(f"[supervisor] sandbox ready at {sandbox}; Ctrl-C to finish.")
        try:
            while session.terminal is None:
                server_thread.join(timeout=1.0)
        except KeyboardInterrupt:
            pass
    wall_seconds = time.monotonic() - started

    stop.set()
    server_thread.join(timeout=5)
    session.stop()
    session.close_transcript()

    result = session.result(thresholds)
    result["agent"] = args.agent or ("custom" if args.agent_cmd else None)
    result["model"] = args.model if (spec is None or spec.uses_model) else None
    result["isolation"] = args.isolation
    # Both of these change how the agent plays, not just what we record of it,
    # so they belong on the run rather than in the config alone. A narrated run
    # and a silent one are not directly comparable.
    result["thinking_tokens"] = thinking_tokens if (spec and spec.uses_model) else 0
    result["narrate"] = bool(narrate)
    result["agent_exit_code"] = agent_rc
    result["wall_seconds"] = round(wall_seconds, 2)
    result.update(usage)
    text = json.dumps(result, indent=2)
    if args.result:
        Path(args.result).write_text(text + "\n", encoding="utf-8")
    # Marked so the agent's transcript above can be separated from the
    # supervisor's own summary below. The summary names the pack, the level and
    # the tier in plain text, none of which an anonymous run should be judged
    # on having "leaked".
    print(RESULT_MARKER)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
