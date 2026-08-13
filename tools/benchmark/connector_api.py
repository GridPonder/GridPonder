"""Provider-neutral completion connector contract for benchmark models."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class CompletionRequest:
    model: str
    prompt: str
    max_output_tokens: int
    timeout_s: float | None = None
    image_b64: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompletionResult:
    text: str
    input_tokens: int = 0
    reasoning_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    reasoning: str = ""
    provider_metadata: dict[str, Any] = field(default_factory=dict)


class CompletionConnector(Protocol):
    def complete(self, request: CompletionRequest) -> CompletionResult:
        """Return one normalized completion."""


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    pricing: dict[str, Any] | None,
) -> float | None:
    """Estimate cost from provider-neutral per-million-token rates."""
    if not pricing:
        return None
    input_rate = pricing.get("input_per_million")
    output_rate = pricing.get("output_per_million")
    if input_rate is None or output_rate is None:
        return None
    input_rate = float(input_rate)
    output_rate = float(output_rate)
    if input_rate < 0 or output_rate < 0:
        raise ValueError("Token prices must not be negative")
    return (
        input_tokens * input_rate + output_tokens * output_rate
    ) / 1_000_000
