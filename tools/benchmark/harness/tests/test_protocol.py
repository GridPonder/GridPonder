import pytest
from tools.benchmark.harness import protocol


def test_roundtrip_request():
    line = protocol.encode_request(["move", '{"action": "step"}'])
    verb, args = protocol.decode_request(line)
    assert verb == "move"
    assert args == ['{"action": "step"}']


def test_bare_verb_has_no_args():
    verb, args = protocol.decode_request(protocol.encode_request(["state"]))
    assert verb == "state"
    assert args == []


def test_unknown_verb_rejected():
    line = protocol.encode_request(["state"]).replace(b"state", b"cheat")
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_request(line)


def test_empty_request_rejected():
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_request(b"[]\n")


def test_malformed_json_rejected():
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_request(b"not json\n")


def test_roundtrip_response():
    text, terminal = protocol.decode_response(
        protocol.encode_response("board here", terminal=True)
    )
    assert text == "board here"
    assert terminal is True


def test_response_defaults_to_non_terminal():
    _text, terminal = protocol.decode_response(protocol.encode_response("x"))
    assert terminal is False


def test_requests_are_newline_terminated():
    assert protocol.encode_request(["state"]).endswith(b"\n")
    assert protocol.encode_response("x").endswith(b"\n")


def test_verbs_are_exactly_the_four():
    assert protocol.VERBS == frozenset({"state", "move", "history", "give_up"})


def test_non_object_response_rejected():
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_response(b"[1,2]\n")


# ── malformed input must surface as ProtocolError, never as a raw exception ──

@pytest.mark.parametrize("line", [b"[[]]\n", b"[{}]\n", b"[1]\n", b"[null]\n",
                                  b"[true]\n"])
def test_non_string_verb_rejected(line):
    """`verb in VERBS` raises TypeError on unhashable JSON; check the type first."""
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_request(line)


@pytest.mark.parametrize("line", [b'["move", {"action": "step"}]\n',
                                  b'["move", 3]\n', b'["move", null]\n'])
def test_non_string_argument_rejected(line):
    """argv is strings. Coercing with str() would emit a Python repr, not JSON."""
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_request(line)


def test_string_terminal_is_not_truthy_coerced():
    """bool("false") is True — the wrong answer, and it ends the run."""
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_response(b'{"text": "x", "terminal": "false"}\n')


@pytest.mark.parametrize("line", [b'{"text": "x", "terminal": 0}\n',
                                  b'{"text": "x", "terminal": 1}\n'])
def test_non_boolean_terminal_rejected(line):
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_response(line)


@pytest.mark.parametrize("line", [b'{"text": 123}\n', b'{"text": {"a": 1}}\n',
                                  b'{"text": null}\n'])
def test_non_string_text_rejected(line):
    with pytest.raises(protocol.ProtocolError):
        protocol.decode_response(line)
