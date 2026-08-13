"""The play client is what the agent runs. Test it against a fake server."""
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parents[1]
PLAY_SRC = HARNESS_DIR / "play"


def _serve_once(sock_path: Path, reply: bytes, received: list[bytes]) -> threading.Thread:
    """Accept one connection, record the request, send `reply`."""
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)

    def run() -> None:
        conn, _ = server.accept()
        with conn:
            received.append(conn.recv(65536))
            conn.sendall(reply)
        server.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _run_play(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(tmp_path / "play"), *args],
        cwd=tmp_path, capture_output=True, text=True, timeout=10,
    )


def test_play_sends_argv_and_prints_reply(tmp_path):
    shutil.copy(PLAY_SRC, tmp_path / "play")
    received: list[bytes] = []
    reply = json.dumps({"text": "BOARD", "terminal": False}).encode() + b"\n"
    thread = _serve_once(tmp_path / ".play.sock", reply, received)

    result = _run_play(tmp_path, "move", '{"action": "step"}')
    thread.join(timeout=5)

    assert json.loads(received[0]) == ["move", '{"action": "step"}']
    assert "BOARD" in result.stdout
    assert result.returncode == 0


def test_play_exits_nonzero_on_terminal_response(tmp_path):
    shutil.copy(PLAY_SRC, tmp_path / "play")
    received: list[bytes] = []
    reply = json.dumps({"text": "SOLVED", "terminal": True}).encode() + b"\n"
    thread = _serve_once(tmp_path / ".play.sock", reply, received)

    result = _run_play(tmp_path, "state")
    thread.join(timeout=5)

    assert "SOLVED" in result.stdout
    assert result.returncode == 3


def test_play_reports_missing_socket_clearly(tmp_path):
    shutil.copy(PLAY_SRC, tmp_path / "play")
    result = _run_play(tmp_path, "state")
    assert result.returncode == 2
    assert "not running" in (result.stdout + result.stderr).lower()


def test_play_reports_malformed_response_without_traceback(tmp_path):
    shutil.copy(PLAY_SRC, tmp_path / "play")
    received: list[bytes] = []
    reply = b"not json at all\n"
    thread = _serve_once(tmp_path / ".play.sock", reply, received)

    result = _run_play(tmp_path, "state")
    thread.join(timeout=5)

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.stdout


def test_play_reports_non_dict_response(tmp_path):
    shutil.copy(PLAY_SRC, tmp_path / "play")
    received: list[bytes] = []
    reply = json.dumps([1, 2, 3]).encode() + b"\n"
    thread = _serve_once(tmp_path / ".play.sock", reply, received)

    result = _run_play(tmp_path, "state")
    thread.join(timeout=5)

    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_play_with_no_arguments_exits_usage_error(tmp_path):
    shutil.copy(PLAY_SRC, tmp_path / "play")
    result = _run_play(tmp_path)
    assert result.returncode == 2


def test_play_times_out_instead_of_hanging(tmp_path):
    shutil.copy(PLAY_SRC, tmp_path / "play")

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(tmp_path / ".play.sock"))
    server.listen(1)

    def run() -> None:
        conn, _ = server.accept()
        # Accept the connection and the request, then never reply and never
        # close — this is exactly the hang scenario Fix 2 guards against.
        conn.recv(65536)
        threading.Event().wait(15)
        conn.close()
        server.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    result = subprocess.run(
        [sys.executable, str(tmp_path / "play"), "state"],
        cwd=tmp_path, capture_output=True, text=True, timeout=10,
        env={**os.environ, "PLAY_SOCKET_TIMEOUT": "1"},
    )

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
