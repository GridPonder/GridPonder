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
