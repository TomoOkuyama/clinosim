"""LLM Provider implementations.

Each provider implements the same interface. The service routes to the
appropriate provider based on configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ProviderResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    latency_ms: int = 0


class OllamaProvider:
    """Local Llama via Ollama. Default provider for v0.1."""

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self.base_url = config.get("endpoint", "http://localhost:11434")
        self.default_model = config.get("model", "llama3.1:8b")

    def complete(self, prompt: str, model: str | None = None,
                 max_tokens: int = 1000, system_prompt: str = "") -> ProviderResponse:
        import httpx

        actual_model = model or self.default_model
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt

        try:
            response = httpx.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": actual_model,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": 0.4,
                    },
                },
                timeout=180,
            )
            response.raise_for_status()
            data = response.json()

            return ProviderResponse(
                text=data.get("response", ""),
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
                model=actual_model,
                latency_ms=int(data.get("total_duration", 0) / 1_000_000),
            )
        except httpx.ConnectError:
            raise ConnectionError(
                f"Cannot connect to Ollama at {self.base_url}. "
                "Is Ollama running? Start with: ollama serve"
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise RuntimeError(
                    f"Model '{actual_model}' not found in Ollama. "
                    f"Pull it with: ollama pull {actual_model}"
                )
            raise

    def health_check(self) -> bool:
        import httpx
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        import httpx
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return []


class MockProvider:
    """Mock provider for testing. Returns predictable text without any LLM call."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.call_count = 0
        self.last_prompt = ""

    def complete(self, prompt: str, model: str | None = None,
                 max_tokens: int = 1000, system_prompt: str = "") -> ProviderResponse:
        self.call_count += 1
        self.last_prompt = prompt
        return ProviderResponse(
            text=f"[Mock LLM response #{self.call_count}]",
            input_tokens=len(prompt.split()),
            output_tokens=10,
            model=model or "mock",
        )

    def health_check(self) -> bool:
        return True
