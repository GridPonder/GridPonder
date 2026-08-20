from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

import run_study
from curriculum import (
    ReflectionResult,
    atomic_write_json,
    pending_checkpoint,
)
from instructions import InstructionPayload
from study_manifest import ModelRole, StudyEpisode


def _episode() -> StudyEpisode:
    model = {
        "id": "fake",
        "display_name": "Fake",
        "model": "fake/model",
        "connector": "fake",
        "local": True,
        "pricing": {
            "input_per_million": 1,
            "output_per_million": 1,
        },
    }
    variant = {"suffix": "", "reasoning": False, "params": {}}
    role = ModelRole(
        role="reference",
        variant_id="fake",
        family="fake",
        tier="frontier",
        reference=True,
        model=model,
        variant=variant,
    )
    return StudyEpisode(
        episode_id="sha256:episode",
        study_id="study",
        panels=("curriculum",),
        cells=("learn",),
        priority=1,
        model_role=role,
        condition="curriculum",
        pack_id="game",
        level_id="level-1",
        level_index=0,
        scope="headline",
        mode="single",
        input_mode="text",
        anon=False,
        max_n=None,
        repeat_index=0,
        instruction_policy="authored-v1",
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


def test_reflection_resume_does_not_repeat_gameplay() -> None:
    episode = _episode()
    task = run_study.StudyTask(
        full_variant_id=episode.model_id,
        task_id=str(episode.session_key),
        priority=1,
        episodes=(episode,),
        curriculum=True,
    )
    args = argparse.Namespace(
        attempt_multiplier=2,
        total_multiplier=3,
        action_timeout=30,
        flex_penalty=0.5,
        runner="python",
        packs_dir=Path("/unused"),
    )
    gameplay_calls = 0
    reflection_calls = 0
    original_gameplay = run_study._run_episode_gameplay
    original_reflect = run_study.reflect_notebook

    def fake_gameplay(**_kwargs):
        nonlocal gameplay_calls
        gameplay_calls += 1
        return {
            "type": "level",
            **run_study._episode_context(episode),
            "model_id": episode.model_id,
            "pack_id": episode.pack_id,
            "level_id": episode.level_id,
            "inference_mode": episode.mode,
            "input_mode": episode.input_mode,
            "success": True,
            "actions_total": 1,
            "llm_calls": 1,
            "input_tokens_total": 10,
            "thinking_tokens_total": 0,
            "output_tokens_total": 5,
            "cost_usd": 0.1,
            "llm_log": [],
        }

    def fake_reflect(**_kwargs):
        nonlocal reflection_calls
        reflection_calls += 1
        if reflection_calls == 1:
            raise TimeoutError("deliberate reflection failure")
        return ReflectionResult(
            notebook="Reusable rule.",
            latency_ms=5,
            input_tokens=2,
            reasoning_tokens=0,
            output_tokens=3,
            cost_usd=0.01,
            cost_source="test",
            response_digest="sha256:reflection",
        )

    with TemporaryDirectory() as temp:
        results_dir = Path(temp)
        meta = {
            episode.output_key: {
                "type": "run_meta",
                "model_id": episode.model_id,
            }
        }
        writer = run_study.ResultWriter(results_dir, meta)
        valid: set[str] = set()
        try:
            run_study._run_episode_gameplay = fake_gameplay
            run_study.reflect_notebook = fake_reflect
            first = run_study._execute_curriculum(
                task,
                instructions={(episode.pack_id, episode.level_id): _instruction()},
                args=args,
                results_dir=results_dir,
                launch_session_id="launch-one",
                writer=writer,
                valid_episode_ids=valid,
            )
            assert first[0]["error_phase"] == "reflection"
            assert gameplay_calls == 1
            assert episode.episode_id not in valid

            second = run_study._execute_curriculum(
                task,
                instructions={(episode.pack_id, episode.level_id): _instruction()},
                args=args,
                results_dir=results_dir,
                launch_session_id="launch-two",
                writer=writer,
                valid_episode_ids=valid,
            )
            assert second[0]["success"]
            assert gameplay_calls == 1
            assert reflection_calls == 2
            assert episode.episode_id in valid
        finally:
            run_study._run_episode_gameplay = original_gameplay
            run_study.reflect_notebook = original_reflect

        records = [
            json.loads(line)
            for line in (results_dir / f"{episode.output_key}.jsonl")
            .read_text()
            .splitlines()
        ]
        assert records[0]["type"] == "run_meta"
        assert records[1]["error_phase"] == "reflection"
        assert records[2]["success"]
        session_files = list((results_dir / "sessions").glob("*.json"))
        assert len(session_files) == 1
        assert json.loads(session_files[0].read_text())["cursor"] == 1
        assert not list((results_dir / "sessions" / "pending").glob("*.json"))


def test_result_before_session_advance_recovers_from_reflected_pending() -> None:
    episode = _episode()
    instruction = _instruction()
    task = run_study.StudyTask(
        full_variant_id=episode.model_id,
        task_id=str(episode.session_key),
        priority=1,
        episodes=(episode,),
        curriculum=True,
    )
    args = argparse.Namespace(
        attempt_multiplier=2,
        total_multiplier=3,
        action_timeout=30,
        flex_penalty=0.5,
        runner="python",
        packs_dir=Path("/unused"),
    )
    gameplay = {
        "type": "level",
        **run_study._episode_context(episode),
        "success": True,
        "actions_total": 1,
        "llm_calls": 1,
        "input_tokens_total": 1,
        "thinking_tokens_total": 0,
        "output_tokens_total": 1,
        "cost_usd": 0.1,
        "llm_log": [],
    }
    reflection = ReflectionResult(
        notebook="Recovered rule.",
        latency_ms=5,
        input_tokens=1,
        reasoning_tokens=0,
        output_tokens=1,
        cost_usd=0.01,
        cost_source="test",
        response_digest="sha256:reflection",
    )
    final_result = run_study._merge_reflection_cost(gameplay, reflection)
    final_result["notebook_after_digest"] = "sha256:notebook"
    final_result["notebook_after_chars"] = len(reflection.notebook)

    with TemporaryDirectory() as temp:
        results_dir = Path(temp)
        writer = run_study.ResultWriter(
            results_dir,
            {
                episode.output_key: {
                    "type": "run_meta",
                    "model_id": episode.model_id,
                }
            },
        )
        writer.append(episode.output_key, final_result)
        pending = pending_checkpoint(
            episode=run_study._episode_context(episode),
            instruction=instruction,
            notebook_before="",
            gameplay_result=gameplay,
        )
        pending.update(
            {
                "status": "reflected",
                "reflection": asdict(reflection),
                "notebook_after": reflection.notebook,
                "final_result": final_result,
            }
        )
        pending_path = (
            results_dir
            / "sessions"
            / "pending"
            / "episode.json"
        )
        atomic_write_json(pending_path, pending)
        valid = {episode.episode_id}

        original_gameplay = run_study._run_episode_gameplay
        original_reflect = run_study.reflect_notebook
        try:
            run_study._run_episode_gameplay = lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("gameplay must not repeat")
            )
            run_study.reflect_notebook = lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("reflection must not repeat")
            )
            emitted = run_study._execute_curriculum(
                task,
                instructions={(episode.pack_id, episode.level_id): instruction},
                args=args,
                results_dir=results_dir,
                launch_session_id="resume",
                writer=writer,
                valid_episode_ids=valid,
            )
        finally:
            run_study._run_episode_gameplay = original_gameplay
            run_study.reflect_notebook = original_reflect

        assert emitted == []
        session_files = list((results_dir / "sessions").glob("*.json"))
        assert json.loads(session_files[0].read_text())["cursor"] == 1
        records = (
            results_dir / f"{episode.output_key}.jsonl"
        ).read_text().splitlines()
        assert len(records) == 2
        assert not pending_path.exists()


if __name__ == "__main__":
    test_reflection_resume_does_not_repeat_gameplay()
    test_result_before_session_advance_recovers_from_reflected_pending()
    print("2 passed")
