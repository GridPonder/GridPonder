"""LiteLLM-based agent client.

Handles LLM calls for all providers (Ollama, Anthropic, OpenAI, Gemini, xAI)
through a single interface. Action extraction mirrors llm_agent.dart so both
stay in sync — change the regex here if you change it there.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import litellm

# Silence LiteLLM's verbose logging by default.
litellm.suppress_debug_info = True


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

    params: dict[str, Any] = {
        "model": litellm_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": effective_max_tokens,
    }
    if request_timeout is not None:
        params["timeout"] = request_timeout
    params.update(extra_params)

    t0 = time.monotonic()
    response = litellm.completion(**params)
    latency_ms = (time.monotonic() - t0) * 1000.0

    content: str = response.choices[0].message.content or ""
    usage = response.usage or {}

    # thinking/reasoning tokens — field name varies by provider.
    thinking_tokens: int = (
        getattr(usage, "reasoning_tokens", None)
        or getattr(usage, "thinking_tokens", None)
        or 0
    )
    output_tokens: int = getattr(usage, "completion_tokens", 0) or 0

    return content, latency_ms, thinking_tokens, output_tokens


def extract_action(text: str) -> dict[str, Any] | None:
    """Extract a JSON action object from the LLM response.

    Mirrors the regex in llm_agent.dart: finds the first {...} block.
    Returns None if no valid JSON action could be parsed.

    Strips <think>...</think> blocks first (Ollama thinking models) so
    that JSON inside reasoning text doesn't get matched accidentally.
    """
    # Strip thinking blocks; fall back to full text if stripping leaves nothing.
    stripped = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
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
