"""Durable curriculum notebook checkpoints and reflection calls."""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent_client import call_llm, extract_action, extract_actions_list
from connector_api import estimate_cost
from instructions import InstructionPayload, sha256_json, sha256_text


NOTEBOOK_MAX_CHARS = 2_000
REFLECTION_MAX_TOKENS = 512


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def notebook_digest(notebook: str) -> str:
    return sha256_text(notebook.strip())


def session_file_name(session_key: str) -> str:
    return session_key.removeprefix("sha256:") + ".json"


@dataclass(frozen=True)
class ReflectionResult:
    notebook: str
    latency_ms: float
    input_tokens: int
    reasoning_tokens: int
    output_tokens: int
    cost_usd: float | None
    cost_source: str
    response_digest: str

    def public_metadata(self) -> dict[str, Any]:
        return {
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "cost_source": self.cost_source,
            "response_digest": self.response_digest,
        }


def empty_session_state(
    *,
    session_key: str,
    study_id: str,
    model_id: str,
    model_role: str,
    pack_id: str,
    configuration_id: str,
    instruction_policy: str,
    expected_episode_ids: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "session_key": session_key,
        "study_id": study_id,
        "model_id": model_id,
        "model_role": model_role,
        "pack_id": pack_id,
        "configuration_id": configuration_id,
        "instruction_policy": instruction_policy,
        "expected_episode_ids": expected_episode_ids,
        "cursor": 0,
        "completed_episode_ids": [],
        "notebook": "",
        "notebook_digest": notebook_digest(""),
        "notebook_history": [],
    }


def load_session_state(
    path: Path,
    expected: dict[str, Any],
) -> dict[str, Any]:
    if not path.is_file():
        return expected
    state = json.loads(path.read_text())
    immutable_fields = [
        "schema_version",
        "session_key",
        "study_id",
        "model_id",
        "model_role",
        "pack_id",
        "configuration_id",
        "instruction_policy",
        "expected_episode_ids",
    ]
    mismatches = [
        field for field in immutable_fields
        if state.get(field) != expected.get(field)
    ]
    if mismatches:
        raise ValueError(
            f"Incompatible curriculum session checkpoint {path}: "
            + ", ".join(mismatches)
        )
    completed = list(state.get("completed_episode_ids") or [])
    expected_ids = list(expected["expected_episode_ids"])
    if completed != expected_ids[: len(completed)]:
        raise ValueError(
            f"Non-contiguous curriculum checkpoint in {path}"
        )
    if int(state.get("cursor", -1)) != len(completed):
        raise ValueError(f"Curriculum cursor mismatch in {path}")
    notebook = str(state.get("notebook") or "")
    if state.get("notebook_digest") != notebook_digest(notebook):
        raise ValueError(f"Curriculum notebook digest mismatch in {path}")
    return state


def advance_session_state(
    state: dict[str, Any],
    *,
    episode_id: str,
    notebook: str,
    reflection: ReflectionResult,
    outcome: dict[str, Any],
) -> dict[str, Any]:
    expected_ids = list(state["expected_episode_ids"])
    cursor = int(state["cursor"])
    if cursor >= len(expected_ids) or expected_ids[cursor] != episode_id:
        raise ValueError(
            f"Cannot advance session at cursor {cursor} with {episode_id}"
        )
    before = str(state.get("notebook") or "")
    updated = dict(state)
    updated["cursor"] = cursor + 1
    updated["completed_episode_ids"] = [
        *list(state.get("completed_episode_ids") or []),
        episode_id,
    ]
    updated["notebook"] = notebook
    updated["notebook_digest"] = notebook_digest(notebook)
    updated["notebook_history"] = [
        *list(state.get("notebook_history") or []),
        {
            "episode_id": episode_id,
            "notebook_before_digest": notebook_digest(before),
            "notebook_before_chars": len(before),
            "notebook_after_digest": notebook_digest(notebook),
            "notebook_after_chars": len(notebook),
            "reflection": reflection.public_metadata(),
            "success": bool(outcome.get("success")),
            "actions_total": outcome.get("actions_total"),
            "llm_calls": outcome.get("llm_calls"),
        },
    ]
    return updated


def tactical_memory_updates(result: dict[str, Any]) -> list[str]:
    updates: list[str] = []
    mode = str(result.get("inference_mode") or "single")
    max_n = result.get("max_n")
    for entry in result.get("llm_log") or []:
        response = str(entry.get("response") or "")
        memory: str | None = None
        if mode == "single":
            action = extract_action(response)
            if action and isinstance(action.get("memory"), str):
                memory = action["memory"]
        else:
            _, memory = extract_actions_list(response, max_n=max_n)
        if memory:
            normalized = " ".join(memory.split())
            if normalized and (not updates or updates[-1] != normalized):
                updates.append(normalized)
    return updates[-8:]


def build_reflection_prompt(
    *,
    instruction: InstructionPayload,
    notebook_before: str,
    gameplay_result: dict[str, Any],
) -> str:
    memories = tactical_memory_updates(gameplay_result)
    memory_text = "\n".join(f"- {item}" for item in memories) or "- none"
    outcome = "solved" if gameplay_result.get("success") else "not solved"
    return f"""You maintain a compact notebook of reusable rules for one grid game.

Update the notebook using only evidence from the completed level. Keep mechanics,
invariants, reusable strategies, and explicitly uncertain hypotheses. Remove exact
coordinates, completed layouts, level-specific move sequences, and stale claims.
Do not claim an uncertain rule as fact. Return JSON only:
{{"notebook": "..."}}

GAME: {instruction.game_title}
GAME DESCRIPTION: {instruction.game_description}
LEVEL: {instruction.level_title}
VISIBLE GUIDE: {instruction.guide or "(none)"}
GOAL: {instruction.rendered_goal}
OUTCOME: {outcome}
ACTIONS: {gameplay_result.get("actions_total")}
CALLS: {gameplay_result.get("llm_calls")}
REJECTIONS: {gameplay_result.get("rejections")}
RESETS: {gameplay_result.get("resets")}

PREVIOUS NOTEBOOK:
{notebook_before or "(empty)"}

TACTICAL MEMORY WRITTEN DURING PLAY:
{memory_text}
"""


def _first_json_object(text: str) -> dict[str, Any] | None:
    start_positions = [match.start() for match in re.finditer(r"\{", text)]
    for start in start_positions:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start : index + 1])
                    except json.JSONDecodeError:
                        break
                    return value if isinstance(value, dict) else None
    return None


def normalize_notebook(response_text: str) -> str:
    parsed = _first_json_object(response_text)
    if parsed is None or not isinstance(parsed.get("notebook"), str):
        raise ValueError("Reflection response did not contain a notebook string")
    notebook = parsed["notebook"].strip()
    if len(notebook) > NOTEBOOK_MAX_CHARS:
        notebook = notebook[:NOTEBOOK_MAX_CHARS].rstrip()
    return notebook


def reflect_notebook(
    *,
    instruction: InstructionPayload,
    notebook_before: str,
    gameplay_result: dict[str, Any],
    model: dict[str, Any],
    variant: dict[str, Any],
    timeout_s: float | None,
) -> ReflectionResult:
    connector_model = model.get("model") or model.get("litellm_model")
    if not connector_model:
        raise ValueError("Reflection model has no connector identifier")
    prompt = build_reflection_prompt(
        instruction=instruction,
        notebook_before=notebook_before,
        gameplay_result=gameplay_result,
    )
    started = time.monotonic()
    (
        response_text,
        latency_ms,
        input_tokens,
        reasoning_tokens,
        output_tokens,
        cost_usd,
        _reasoning,
    ) = call_llm(
        prompt,
        str(connector_model),
        dict(variant.get("params") or {}),
        max_tokens=REFLECTION_MAX_TOKENS,
        request_timeout=timeout_s,
        connector=str(model.get("connector", "litellm")),
    )
    measured_ms = (time.monotonic() - started) * 1000
    latency_ms = latency_ms or measured_ms
    cost_source = "connector"
    if cost_usd is None:
        cost_usd = estimate_cost(
            input_tokens,
            output_tokens,
            model.get("pricing"),
        )
        cost_source = (
            "configured_estimate" if cost_usd is not None else "unavailable"
        )
    notebook = normalize_notebook(response_text)
    return ReflectionResult(
        notebook=notebook,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        reasoning_tokens=reasoning_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        cost_source=cost_source,
        response_digest=sha256_text(response_text),
    )


def pending_checkpoint(
    *,
    episode: dict[str, Any],
    instruction: InstructionPayload,
    notebook_before: str,
    gameplay_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "episode": episode,
        "instruction_digest": instruction.digest,
        "notebook_before": notebook_before,
        "notebook_before_digest": notebook_digest(notebook_before),
        "gameplay_result": gameplay_result,
        "gameplay_result_digest": sha256_json(gameplay_result),
    }


def load_pending_checkpoint(
    path: Path,
    *,
    episode_id: str,
    instruction_digest: str,
    notebook_before: str,
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    pending = json.loads(path.read_text())
    if pending.get("episode", {}).get("episode_id") != episode_id:
        raise ValueError(f"Pending checkpoint episode mismatch in {path}")
    if pending.get("instruction_digest") != instruction_digest:
        raise ValueError(f"Pending checkpoint instruction mismatch in {path}")
    if pending.get("notebook_before_digest") != notebook_digest(notebook_before):
        raise ValueError(f"Pending checkpoint notebook mismatch in {path}")
    gameplay_result = pending.get("gameplay_result")
    if pending.get("gameplay_result_digest") != sha256_json(gameplay_result):
        raise ValueError(f"Pending gameplay digest mismatch in {path}")
    return pending
