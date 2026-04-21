"""LiteLLM-based agent client.

Handles LLM calls for all providers (Ollama, Anthropic, OpenAI, Gemini, xAI)
through a single interface. Action extraction mirrors llm_agent.dart so both
stay in sync — change the regex here if you change it there.
"""

from __future__ import annotations

import json
import multiprocessing
import re
import time
from typing import Any

import litellm

# Silence LiteLLM's verbose logging by default.
litellm.suppress_debug_info = True


def _llm_worker(queue: Any, params: dict) -> None:
    """Subprocess worker: makes the LiteLLM call and puts result on queue.

    Runs in a separate process so the caller can hard-kill it (and close the
    underlying TCP connection) when the wall-clock timeout fires.
    """
    try:
        import litellm as _litellm  # re-import in spawned process
        _litellm.suppress_debug_info = True
        response = _litellm.completion(**params)
        content: str = response.choices[0].message.content or ""
        usage = response.usage or {}
        thinking_tokens: int = (
            getattr(usage, "reasoning_tokens", None)
            or getattr(usage, "thinking_tokens", None)
            or 0
        )
        output_tokens: int = getattr(usage, "completion_tokens", 0) or 0
        queue.put(("ok", (content, thinking_tokens, output_tokens)))
    except BaseException as e:  # noqa: BLE001
        queue.put(("err", e))


def call_llm(
    prompt: str,
    litellm_model: str,
    extra_params: dict[str, Any] | None = None,
    max_tokens: int = 1024,
    request_timeout: float | None = None,
) -> tuple[str, float, int, int]:
    """Call an LLM and return (response_text, latency_ms, thinking_tokens, output_tokens).

    Args:
        prompt: The full prompt string built by the Dart runner.
        litellm_model: LiteLLM model string, e.g. "ollama_chat/qwen3:4b".
        extra_params: Provider-specific params merged into the completion call
                      (e.g. {"think": True} for Ollama, {"thinking": {...}} for Anthropic).
        max_tokens: Max output tokens (thinking budget added on top for API models).
        request_timeout: Hard wall-clock timeout in seconds. When set, the LLM
                         call runs in a subprocess; exceeding the limit terminates
                         the process (closing the TCP connection so Ollama stops
                         generating) and raises TimeoutError.
    """
    extra_params = dict(extra_params or {})

    # Ollama-specific params ("think", "reasoning_effort") must be sent as
    # top-level fields in the Ollama API request body via LiteLLM's extra_body.
    # When thinking is on, raise max_tokens so the model can finish reasoning
    # before producing the action JSON.
    effective_max_tokens = max_tokens
    if litellm_model.startswith("ollama"):
        ollama_body: dict[str, Any] = {}
        for key in ("think", "reasoning_effort"):
            if key in extra_params:
                ollama_body[key] = extra_params.pop(key)
        if ollama_body:
            extra_params["extra_body"] = ollama_body
        if ollama_body.get("think") is True or "reasoning_effort" in ollama_body:
            effective_max_tokens = max(max_tokens, 32768)

    # Anthropic/Bedrock extended thinking: max_tokens must exceed budget_tokens.
    thinking_cfg = extra_params.get("thinking")
    if isinstance(thinking_cfg, dict) and thinking_cfg.get("type") == "enabled":
        budget = thinking_cfg.get("budget_tokens", 0)
        effective_max_tokens = max(effective_max_tokens, budget + max_tokens)

    params: dict[str, Any] = {
        "model": litellm_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": effective_max_tokens,
    }
    if request_timeout is not None:
        params["timeout"] = request_timeout
    params.update(extra_params)

    t0 = time.monotonic()

    if request_timeout is not None:
        # Run in a subprocess so we can hard-kill it on timeout.  A daemon
        # thread would abandon the HTTP connection but leave Ollama generating;
        # terminating the process closes the socket and stops generation.
        ctx = multiprocessing.get_context("spawn")
        queue: multiprocessing.Queue = ctx.Queue()
        p = ctx.Process(target=_llm_worker, args=(queue, params), daemon=True)
        p.start()
        p.join(timeout=request_timeout)

        if p.is_alive():
            p.terminate()
            p.join(timeout=5)
            if p.is_alive():
                p.kill()  # SIGKILL if SIGTERM was ignored (e.g. blocked in C HTTP call)
                p.join()
            raise TimeoutError(
                f"LLM call exceeded {request_timeout}s wall-clock limit"
            )

        try:
            status, value = queue.get_nowait()
        except Exception as exc:
            raise RuntimeError("LLM worker exited without result") from exc

        if status == "err":
            raise value  # re-raise original exception from worker
        content, thinking_tokens, output_tokens = value
    else:
        # No timeout — call directly in-process (no subprocess overhead).
        try:
            response = litellm.completion(**params)
        except BaseException as e:
            raise e
        content = response.choices[0].message.content or ""
        usage = response.usage or {}
        thinking_tokens = (
            getattr(usage, "reasoning_tokens", None)
            or getattr(usage, "thinking_tokens", None)
            or 0
        )
        output_tokens = getattr(usage, "completion_tokens", 0) or 0

    latency_ms = (time.monotonic() - t0) * 1000.0
    return content, latency_ms, thinking_tokens, output_tokens


def _strip_noise(text: str) -> str:
    """Remove <think> blocks and markdown code fences, then strip whitespace."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"```[a-z]*\n?", "", text, flags=re.IGNORECASE)
    return text.strip()


def extract_action(text: str) -> dict[str, Any] | None:
    """Extract a single JSON action object from the LLM response.

    Mirrors the regex in llm_agent.dart: finds the first {...} block.
    Returns None if no valid JSON action could be parsed.

    Strips <think>...</think> blocks and markdown code fences first.
    """
    stripped = _strip_noise(text)
    for candidate in [stripped or text, text]:
        match = re.search(r"\{[^}]+\}", candidate)
        if match:
            try:
                obj = json.loads(match.group(0))
                if isinstance(obj, dict) and "action" in obj:
                    return obj
            except json.JSONDecodeError:
                pass
    return None


def extract_actions_list(
    text: str, max_n: int | None = None
) -> tuple[list[dict[str, Any]], str | None]:
    """Extract a list of actions and optional memory from a multi-action response.

    Handles three formats the model may produce:
      1. Outer object:  {"actions": [{"action": "..."}, ...], "memory": "..."}
      2. Bare array:    [{"action": "..."}, ...]  (memory in last item if present)
      3. Single action: {"action": "..."}          (wrapped into a one-element list)

    Returns (actions, memory) where:
      - actions is a (possibly empty) list of action dicts without memory fields
      - memory is the extracted memory string or None

    Strips <think>...</think> blocks and markdown code fences before parsing.
    Caps list length at max_n if provided.
    """
    source = _strip_noise(text) or text

    def _cap(lst: list) -> list:
        return lst[:max_n] if max_n is not None else lst

    # Try to parse any JSON value starting at the first '{' or '['.
    for start_char in ('{', '['):
        pos = source.find(start_char)
        if pos == -1:
            continue
        try:
            parsed, _ = json.JSONDecoder().raw_decode(source, pos)
        except json.JSONDecodeError:
            continue

        # Format 1: {"actions": [...], "memory": "..."}
        if isinstance(parsed, dict) and "actions" in parsed:
            raw_actions = parsed.get("actions", [])
            memory = parsed.get("memory")
            actions = [
                {k: v for k, v in a.items() if k != "memory"}
                for a in raw_actions
                if isinstance(a, dict) and "action" in a
            ]
            if actions:
                return _cap(actions), memory

        # Format 2: bare array [{"action": ...}, ...]
        if isinstance(parsed, list):
            actions = [a for a in parsed if isinstance(a, dict) and "action" in a]
            if actions:
                # Memory may be on the last item.
                memory = actions[-1].pop("memory", None) if actions else None
                actions = [{k: v for k, v in a.items() if k != "memory"} for a in actions]
                return _cap(actions), memory

    # Format 3: single action fallback.
    single = extract_action(source)
    if single:
        memory = single.pop("memory", None)
        return [single], memory

    return [], None
