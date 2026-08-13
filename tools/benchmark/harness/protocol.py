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
    # Type-check before the membership test: `verb in VERBS` raises TypeError
    # for unhashable JSON values (a nested array or object), which would
    # escape decode_request as something other than a ProtocolError.
    if not isinstance(verb, str):
        raise ProtocolError(f"verb must be a string, got {type(verb).__name__}")
    if verb not in VERBS:
        raise ProtocolError(f"unknown verb: {verb!r}")
    # argv comes from a shell argv, so every argument is already a string.
    # Coercing with str() instead would silently turn a JSON object into its
    # Python repr ("{'action': 'step'}"), which no longer parses as JSON.
    args = argv[1:]
    for i, arg in enumerate(args):
        if not isinstance(arg, str):
            raise ProtocolError(
                f"argument {i} must be a string, got {type(arg).__name__}"
            )
    return verb, args


def encode_response(text: str, *, terminal: bool = False) -> bytes:
    payload = {"text": text, "terminal": terminal}
    return (json.dumps(payload) + "\n").encode("utf-8")


def decode_response(line: bytes) -> tuple[str, bool]:
    try:
        payload = json.loads(line.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtocolError(f"malformed response: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProtocolError("response must be a JSON object")
    # Check the types rather than coercing them. bool("false") is True, so a
    # supervisor that stringified `terminal` would end every run on its first
    # reply; str() on a non-string `text` yields a Python repr, not the text.
    text = payload.get("text", "")
    if not isinstance(text, str):
        raise ProtocolError(f"text must be a string, got {type(text).__name__}")
    terminal = payload.get("terminal", False)
    if not isinstance(terminal, bool):
        raise ProtocolError(
            f"terminal must be a boolean, got {type(terminal).__name__}"
        )
    return text, terminal
