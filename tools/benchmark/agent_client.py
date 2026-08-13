"""Provider-neutral agent client.

LiteLLM remains the default connector. Additional connectors are loaded from
an ignored local directory and implement the contract in ``connector_api``.
Action extraction mirrors llm_agent.dart so both stay in sync.
"""

from __future__ import annotations

import importlib.util
import json
import multiprocessing
import os
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from connector_api import CompletionRequest, CompletionResult


def _llm_worker(queue: Any, params: dict) -> None:
    """Subprocess worker: makes the LiteLLM call and puts result on queue.

    Runs in a separate process so the caller can hard-kill it (and close the
    underlying TCP connection) when the wall-clock timeout fires.
    """
    try:
        import litellm as _litellm  # re-import in spawned process
        _litellm.suppress_debug_info = True
        response = _litellm.completion(**params)
        msg = response.choices[0].message
        content: str = msg.content or ""
        reasoning: str = _extract_reasoning(msg)
        usage = response.usage or {}
        input_tokens: int = getattr(usage, "prompt_tokens", 0) or 0
        thinking_tokens: int = (
            getattr(usage, "reasoning_tokens", None)
            or getattr(usage, "thinking_tokens", None)
            or 0
        )
        output_tokens: int = getattr(usage, "completion_tokens", 0) or 0
        raw_cost = response._hidden_params.get("response_cost")
        cost = float(raw_cost) if raw_cost is not None else None
        queue.put(
            (
                "ok",
                (
                    content,
                    input_tokens,
                    thinking_tokens,
                    output_tokens,
                    cost,
                    reasoning,
                ),
            )
        )
    except BaseException as e:  # noqa: BLE001
        queue.put(("err", e))


def _extract_reasoning(msg: Any) -> str:
    """Best-effort extraction of summarised reasoning content from a LiteLLM
    response message. Anthropic / OpenAI-o1 / Gemini all expose this slightly
    differently; LiteLLM normalises most of them onto `reasoning_content`."""
    rc = getattr(msg, "reasoning_content", None)
    if isinstance(rc, str) and rc:
        return rc
    blocks = getattr(msg, "thinking_blocks", None) or getattr(msg, "reasoning", None)
    if isinstance(blocks, list):
        parts: list[str] = []
        for b in blocks:
            if isinstance(b, dict):
                t = b.get("thinking") or b.get("text") or b.get("content")
                if isinstance(t, str) and t:
                    parts.append(t)
            elif isinstance(b, str) and b:
                parts.append(b)
        return "\n".join(parts)
    return ""


def call_llm(
    prompt: str,
    model: str,
    extra_params: dict[str, Any] | None = None,
    max_tokens: int = 1024,
    request_timeout: float | None = None,
    image_b64: str | None = None,
    connector: str = "litellm",
) -> tuple[str, float, int, int, int, float | None, str]:
    """Call a model through a normalized connector.

    Returns ``(text, latency_ms, input_tokens, reasoning_tokens,
    output_tokens, cost_usd_or_none, reasoning)``.

    If `image_b64` is provided, the prompt is sent as a multimodal message
    (text + image).

    `reasoning` is the model's summarised thinking content when the provider
    exposes it (Anthropic extended-thinking summary, OpenAI o-series, Gemini).
    Empty string when not available.

    Args:
        prompt: The full prompt string built by the Dart runner.
        model: Connector-specific model identifier.
        extra_params: Provider-specific params merged into the completion call
                      (e.g. {"think": True} for Ollama, {"thinking": {...}} for Anthropic).
        max_tokens: Max output tokens (thinking budget added on top for API models).
        request_timeout: Hard wall-clock timeout in seconds. When set, the LLM
                         call runs in a subprocess; exceeding the limit terminates
                         the process (closing the TCP connection so Ollama stops
                         generating) and raises TimeoutError.
    """
    extra_params = dict(extra_params or {})

    if connector != "litellm":
        request = CompletionRequest(
            model=model,
            prompt=prompt,
            max_output_tokens=max_tokens,
            timeout_s=request_timeout,
            image_b64=image_b64,
            options=extra_params,
        )
        t0 = time.monotonic()
        result = _load_connector(connector).complete(request)
        if not isinstance(result, CompletionResult):
            if not isinstance(result, dict):
                raise TypeError(
                    f"Connector {connector!r} returned {type(result).__name__}; "
                    "expected CompletionResult or dict"
                )
            result = CompletionResult(**result)
        latency_ms = (time.monotonic() - t0) * 1000.0
        return (
            result.text,
            latency_ms,
            result.input_tokens,
            result.reasoning_tokens,
            result.output_tokens,
            result.cost_usd,
            result.reasoning,
        )

    litellm = _import_litellm()

    # Ollama-specific params ("think", "reasoning_effort") must be sent as
    # top-level fields in the Ollama API request body via LiteLLM's extra_body.
    # When thinking is on, raise max_tokens so the model can finish reasoning
    # before producing the action JSON.
    effective_max_tokens = max_tokens
    if model.startswith("ollama"):
        ollama_body: dict[str, Any] = {}
        for key in ("think", "reasoning_effort"):
            if key in extra_params:
                ollama_body[key] = extra_params.pop(key)
        if ollama_body:
            extra_params["extra_body"] = ollama_body
        if ollama_body.get("think") is True or "reasoning_effort" in ollama_body:
            effective_max_tokens = max(max_tokens, 32768)

    # Extended-thinking transports need enough output budget for both hidden
    # reasoning and the visible response.
    thinking_cfg = extra_params.get("thinking")
    if isinstance(thinking_cfg, dict):
        if thinking_cfg.get("type") == "enabled":
            budget = thinking_cfg.get("budget_tokens", 0)
            effective_max_tokens = max(effective_max_tokens, budget + max_tokens)
        elif thinking_cfg.get("type") == "adaptive":
            effective_max_tokens = max(effective_max_tokens, 16384)

    # MiniMax reasons by default (hidden chain-of-thought consumes output tokens
    # even without an explicit thinking param), so always give it headroom.
    if "minimax" in model:
        effective_max_tokens = max(effective_max_tokens, 32768)

    if image_b64:
        # Multimodal: OpenAI-style content list, normalised across providers
        # by LiteLLM. Sent as data URL so we don't need to host the image.
        user_content: Any = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ]
    else:
        user_content = prompt

    params: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": user_content}],
        "max_tokens": effective_max_tokens,
    }
    if request_timeout is not None:
        params["timeout"] = request_timeout
    params.update(extra_params)

    t0 = time.monotonic()

    # Only use subprocess isolation for Ollama (to hard-kill local inference).
    # API models use LiteLLM's native timeout via the `timeout` param above.
    use_subprocess = request_timeout is not None and model.startswith("ollama")

    if use_subprocess:
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
        content, input_tokens, thinking_tokens, output_tokens, cost, reasoning = value
    else:
        # No timeout — call directly in-process (no subprocess overhead).
        response = litellm.completion(**params)
        msg = response.choices[0].message
        content = msg.content or ""
        reasoning = _extract_reasoning(msg)
        usage = response.usage or {}
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        thinking_tokens = (
            getattr(usage, "reasoning_tokens", None)
            or getattr(usage, "thinking_tokens", None)
            or 0
        )
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        raw_cost = response._hidden_params.get("response_cost")
        cost = float(raw_cost) if raw_cost is not None else None

    latency_ms = (time.monotonic() - t0) * 1000.0
    return (
        content,
        latency_ms,
        input_tokens,
        thinking_tokens,
        output_tokens,
        cost,
        reasoning,
    )


@lru_cache(maxsize=1)
def _import_litellm():
    try:
        import litellm
    except ImportError as exc:
        raise RuntimeError(
            "LiteLLM connector selected but litellm is not installed. "
            "Install tools/benchmark/requirements.txt."
        ) from exc
    litellm.suppress_debug_info = True
    return litellm


@lru_cache(maxsize=None)
def _load_connector(name: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError(f"Invalid connector name: {name!r}")
    configured = os.environ.get("GRIDPONDER_CONNECTOR_DIR")
    connector_dir = (
        Path(configured).expanduser()
        if configured
        else Path(__file__).parent / "connectors.local"
    )
    path = connector_dir / f"{name}.py"
    if not path.is_file():
        raise FileNotFoundError(
            f"Connector {name!r} not found at {path}. "
            "Set GRIDPONDER_CONNECTOR_DIR or install the local connector."
        )
    spec = importlib.util.spec_from_file_location(
        f"gridponder_connector_{name}", path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load connector {name!r} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    connector = getattr(module, "connector", module)
    if not callable(getattr(connector, "complete", None)):
        raise TypeError(f"Connector {name!r} must expose complete(request)")
    return connector


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
