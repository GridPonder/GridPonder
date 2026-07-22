"""The play client is what the agent runs. Test it against a fake server."""
import json
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
    assert result.returncode != 0
    assert "not running" in (result.stdout + result.stderr).lower()
