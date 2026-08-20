from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from curriculum import (
    NOTEBOOK_MAX_CHARS,
    ReflectionResult,
    advance_session_state,
    atomic_write_json,
    empty_session_state,
    load_pending_checkpoint,
    load_session_state,
    normalize_notebook,
    pending_checkpoint,
)
from instructions import InstructionPayload


def _reflection(notebook: str) -> ReflectionResult:
    return ReflectionResult(
        notebook=notebook,
        latency_ms=10,
        input_tokens=2,
        reasoning_tokens=0,
        output_tokens=3,
        cost_usd=0.01,
        cost_source="test",
        response_digest="sha256:test",
    )


def _instruction() -> InstructionPayload:
    return InstructionPayload(
        policy="authored-v1",
        pack_id="game",
        level_id="level-1",
        level_index=0,
        sequence_index=1,
        stage_index=0,
        game_title="Game",
        game_description="Rules",
        stories=(),
        level_title="Level",
        guide="Guide",
        rendered_goal="Goal",
        omitted_media=(),
        source_files=("game/game.json",),
        digest="sha256:instruction",
    )


def test_session_state_requires_contiguous_prefix() -> None:
    expected = empty_session_state(
        session_key="sha256:session",
        study_id="study",
        model_id="model",
        model_role="frontier",
        pack_id="game",
        configuration_id="curriculum-single-text",
        instruction_policy="authored-v1",
        expected_episode_ids=["one", "two"],
    )
    advanced = advance_session_state(
        expected,
        episode_id="one",
        notebook="rule",
        reflection=_reflection("rule"),
        outcome={"success": True, "actions_total": 2, "llm_calls": 2},
    )
    with TemporaryDirectory() as temp:
        path = Path(temp) / "session.json"
        atomic_write_json(path, advanced)
        assert load_session_state(path, expected)["cursor"] == 1
        broken = dict(advanced)
        broken["completed_episode_ids"] = ["two"]
        atomic_write_json(path, broken)
        try:
            load_session_state(path, expected)
        except ValueError as exc:
            assert "Non-contiguous" in str(exc)
        else:
            raise AssertionError("non-contiguous session should fail")


def test_pending_gameplay_checkpoint_detects_changes() -> None:
    instruction = _instruction()
    pending = pending_checkpoint(
        episode={"episode_id": "episode"},
        instruction=instruction,
        notebook_before="before",
        gameplay_result={"success": False, "actions_total": 3},
    )
    with TemporaryDirectory() as temp:
        path = Path(temp) / "pending.json"
        atomic_write_json(path, pending)
        loaded = load_pending_checkpoint(
            path,
            episode_id="episode",
            instruction_digest=instruction.digest,
            notebook_before="before",
        )
        assert loaded is not None
        pending["gameplay_result"]["actions_total"] = 4
        atomic_write_json(path, pending)
        try:
            load_pending_checkpoint(
                path,
                episode_id="episode",
                instruction_digest=instruction.digest,
                notebook_before="before",
            )
        except ValueError as exc:
            assert "gameplay digest" in str(exc)
        else:
            raise AssertionError("modified pending gameplay should fail")


def test_notebook_is_bounded() -> None:
    notebook = normalize_notebook(
        '{"notebook":"' + ("x" * (NOTEBOOK_MAX_CHARS + 100)) + '"}'
    )
    assert len(notebook) == NOTEBOOK_MAX_CHARS


if __name__ == "__main__":
    test_session_state_requires_contiguous_prefix()
    test_pending_gameplay_checkpoint_detects_changes()
    test_notebook_is_bounded()
    print("3 passed")
