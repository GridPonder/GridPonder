"""Wire format for the sandbox <-> supervisor socket.

Deliberately tiny and closed: the supervisor accepts exactly four verbs and
nothing else. Anything the agent sends that is not one of them is a
ProtocolError, which the supervisor logs and refuses.

Pure functions only — no sockets, no files. Keeps the format unit-testable.
"""
from __future__ import annotations

import json

VERBS = frozenset({"state", "move", "history", "give_up"})


class ProtocolError(Exception):
    """Malformed or disallowed message."""


def encode_request(argv: list[str]) -> bytes:
    return (json.dumps(argv) + "\n").encode("utf-8")


def decode_request(line: bytes) -> tuple[str, list[str]]:
    try:
        argv = json.loads(line.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtocolError(f"malformed request: {exc}") from exc
    if not isinstance(argv, list) or not argv:
        raise ProtocolError("request must be a non-empty JSON array")
    verb = argv[0]
    if verb not in VERBS:
        raise ProtocolError(f"unknown verb: {verb!r}")
    return verb, [str(a) for a in argv[1:]]


def encode_response(text: str, *, terminal: bool = False) -> bytes:
    payload = {"text": text, "terminal": terminal}
    return (json.dumps(payload) + "\n").encode("utf-8")


def decode_response(line: bytes) -> tuple[str, bool]:
    try:
        payload = json.loads(line.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtocolError(f"malformed response: {exc}") from exc
    return str(payload.get("text", "")), bool(payload.get("terminal", False))
