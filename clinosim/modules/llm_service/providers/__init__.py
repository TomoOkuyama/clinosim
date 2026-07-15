"""LLM provider registry. Adds new providers by registering here."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .base import LLMProvider, ProviderResponse
from .bedrock import BedrockProvider
from .mock import MockProvider
from .ollama import OllamaProvider

__all__ = [
    "LLMProvider",
    "ProviderResponse",
    "OllamaProvider",
    "MockProvider",
    "BedrockProvider",
    "build_provider",
    "register_provider",
]


_REGISTRY: dict[str, Callable[[dict[str, Any]], Any]] = {
    "local": lambda cfg: OllamaProvider(cfg),
    "ollama": lambda cfg: OllamaProvider(cfg),
    "bedrock": lambda cfg: BedrockProvider(cfg),
    "mock": lambda cfg: MockProvider(cfg),
    # "anthropic_direct" and "openai_compatible" can be added later
    # by registering builders via register_provider() from user code.
}


def register_provider(name: str, builder: Callable[[dict[str, Any]], Any]) -> None:
    """Register a custom provider builder so third-party code can extend the registry."""
    _REGISTRY[name] = builder


def build_provider(provider_name: str, provider_config: dict[str, Any] | None) -> Any:
    """Instantiate a provider by its config section name.

    Example:
        build_provider("bedrock", {"region": "us-east-1", "model_id": "..."})
    """
    if provider_name not in _REGISTRY:
        raise ValueError(f"Unknown LLM provider: {provider_name!r}. Registered: {sorted(_REGISTRY.keys())}")
    return _REGISTRY[provider_name](provider_config or {})
