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
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
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
)
from engines.python.goal_renderer import render_goals  # noqa: E402
from engines.python._turn_engine import TurnEngine  # noqa: E402
from tools.benchmark.harness import metrics, protocol  # noqa: E402
from tools.benchmark.harness.rules import build_rules  # noqa: E402

SOCK_NAME = ".play.sock"
_ACCEPT_POLL_SECONDS = 0.2
_USAGE = "usage: ./play state | move '<json>' | history | give_up"


class Session:
    """One level, one agent. Owns the runner subprocess and the run's counters."""

    def __init__(self, pack_dir: Path, level_id: str, *, anon: bool = False):
        self.pack_dir = pack_dir
        self.level_id = level_id
        self.anon = anon

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
        if anon:
            self.anon_shapes, _table = build_anon_action_shapes(self.game_def)

        self.proc: subprocess.Popen | None = None
        self.state: dict[str, Any] = {}
        self.history: list[dict] = []
        # first_divergence compares the agent's *first* attempt against the
        # gold path, so stop recording once the board has been reset.
        self.first_attempt_moves: list[dict] = []
        self.past_first_attempt = False
        self.rejected_schema = 0
        self.rejected_illegal = 0
        self.terminal: dict[str, Any] | None = None

    # ── runner plumbing ──────────────────────────────────────────────────

    def start(self, packs_dir: Path) -> None:
        argv = [
            sys.executable, str(_BENCH_DIR / "runner.py"),
            "--pack", self.pack_dir.name,
            "--level", self.level_id,
            "--packs-dir", str(packs_dir),
            "--observation", "harness",
            "--mode", "single",
        ]
        if self.anon:
            argv.append("--anon")
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
        if self.terminal is not None:
            return self.terminal_text(), True
        if verb == "state":
            return self.render_state(), False
        if verb == "history":
            return self.render_history(), False
        if verb == "give_up":
            return self._submit({"action": "give_up"}, record=False)
        if verb == "move":
            return self._move(args)
        return _USAGE, False

    def _move(self, args: list[str]) -> tuple[str, bool]:
        if len(args) != 1:
            return self._schema_error(
                "move takes exactly one argument: the action as JSON, quoted."
            )
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

    def _submit(self, action: dict, *, record: bool) -> tuple[str, bool]:
        assert self.proc is not None and self.proc.stdin is not None
        was_first_attempt = not self.past_first_attempt
        self.proc.stdin.write(json.dumps(action) + "\n")
        self.proc.stdin.flush()
        events = self._pump()

        rejections = [e for e in events if e.get("event") == "rejected"]
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
            body = ""
            was_reset = any(e.get("event") == "reset" for e in events)
            if record:
                # A move that tripped the per-attempt limit belongs to the
                # attempt that just ended, whose history _pump already cleared.
                if not was_reset:
                    self.history.append(action)
                if was_first_attempt:
                    self.first_attempt_moves.append(action)

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
        ),
        encoding="utf-8",
    )

    play_dst = sandbox / "play"
    shutil.copyfile(_HARNESS_DIR / "play", play_dst)
    play_dst.chmod(0o755)

    sock_path = sandbox / SOCK_NAME
    if sock_path.exists():
        sock_path.unlink()
    return sock_path


def serve(session: Session, sock_path: Path, stop: threading.Event) -> None:
    """Accept ./play connections until `stop` is set."""
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(sock_path))
        server.listen(8)
        server.settimeout(_ACCEPT_POLL_SECONDS)
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


def load_thresholds(config_path: Path) -> dict:
    import yaml

    config = yaml.safe_load(config_path.read_text()) or {}
    return config.get("thresholds", {})


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
        "--agent-cmd", nargs=argparse.REMAINDER, default=None,
        help="Command to run inside the sandbox. Everything after this flag.",
    )
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()

    packs_dir = Path(args.packs_dir).resolve()
    session = Session(packs_dir / args.pack, args.level, anon=args.anon)
    sandbox = Path(args.sandbox).resolve()
    sock_path = build_sandbox(session, sandbox)
    session.start(packs_dir)

    stop = threading.Event()
    server_thread = threading.Thread(
        target=serve, args=(session, sock_path, stop), daemon=True
    )
    server_thread.start()

    agent_rc: int | None = None
    if args.agent_cmd:
        env = dict(os.environ)
        env["PLAY_SANDBOX"] = str(sandbox)
        try:
            agent_rc = subprocess.call(
                args.agent_cmd, cwd=str(sandbox), env=env, timeout=args.timeout
            )
        except subprocess.TimeoutExpired:
            agent_rc = -1
            print("[supervisor] agent timed out", file=sys.stderr)
    else:
        print(f"[supervisor] sandbox ready at {sandbox}; Ctrl-C to finish.")
        try:
            while session.terminal is None:
                server_thread.join(timeout=1.0)
        except KeyboardInterrupt:
            pass

    stop.set()
    server_thread.join(timeout=5)
    session.stop()

    thresholds = load_thresholds(Path(args.config))
    result = session.result(thresholds)
    result["agent_exit_code"] = agent_rc
    text = json.dumps(result, indent=2)
    if args.result:
        Path(args.result).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
