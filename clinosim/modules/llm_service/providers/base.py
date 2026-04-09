"""Base interfaces for LLM providers.

All providers implement `LLMProvider` Protocol so that `LLMService` can
swap backends without code changes (AD-11, AD-24).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class ProviderResponse:
    """Unified response from any LLM provider."""

    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    latency_ms: int = 0
    # Arbitrary provider metadata (stop reason, safety flags, cost estimate, ...)
    metadata: dict[str, Any] | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """Structural interface every provider must satisfy."""

    def complete(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 1000,
        system_prompt: str = "",
        temperature: float = 0.4,
        stop_sequences: list[str] | None = None,
    ) -> ProviderResponse:
        """Synchronous text completion. Raises on error; LLMService handles retry/fallback."""
        ...

    def health_check(self) -> bool:
        """Quick reachability check. Must not raise."""
        ...
