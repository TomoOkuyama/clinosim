"""Ollama (local) LLM provider. Default for development."""

from __future__ import annotations

from typing import Any

from .base import ProviderResponse


class OllamaProvider:
    """Local Llama/Qwen/etc. via Ollama HTTP API.

    Config keys:
        endpoint: str = "http://localhost:11434"
        model:    str = "llama3.1:8b"
    """

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self.base_url = config.get("endpoint", "http://localhost:11434")
        self.default_model = config.get("model", "llama3.1:8b")

    def complete(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 1000,
        system_prompt: str = "",
        temperature: float = 0.4,
        stop_sequences: list[str] | None = None,
    ) -> ProviderResponse:
        import httpx

        actual_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": actual_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt
        if stop_sequences:
            payload["options"]["stop"] = stop_sequences

        try:
            response = httpx.post(
                f"{self.base_url}/api/generate",
                json=payload,
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
                metadata={"done_reason": data.get("done_reason")},
            )
        except httpx.ConnectError as e:
            raise ConnectionError(
                f"Cannot connect to Ollama at {self.base_url}. "
                f"Is Ollama running? Start with: ollama serve"
            ) from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise RuntimeError(
                    f"Model '{actual_model}' not found in Ollama. "
                    f"Pull it with: ollama pull {actual_model}"
                ) from e
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
