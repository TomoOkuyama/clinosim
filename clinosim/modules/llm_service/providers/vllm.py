"""vLLM (OpenAI-compatible) LLM provider.

Targets vLLM's ``/v1/chat/completions`` endpoint served by ``vllm serve``.
Same wire contract as the OpenAI Chat Completions API, so this provider
also works with any OpenAI-compatible server (SGLang, TensorRT-LLM
Triton, LiteLLM proxy, etc.).

Config keys:
    endpoint:   str  = "http://localhost:8000"    # vLLM default
    model:      str  = "Qwen/Qwen3.8-27B-FP8"      # HF-style ID served by vLLM
    enable_thinking: bool | None = None            # Qwen thinking mode
                                                    # (None = server default)
    seed:       int | None = None                  # per-request seed
    timeout_seconds: int = 300
"""

from __future__ import annotations

from typing import Any

from .base import ProviderResponse


class VLLMProvider:
    """vLLM (or any OpenAI-compatible) chat-completions provider."""

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self.base_url = config.get("endpoint", "http://localhost:8000").rstrip("/")
        self.default_model = config.get("model", "Qwen/Qwen3.8-27B-FP8")
        # Qwen thinking mode: False disables internal step-by-step reasoning
        # (equivalent to Ollama's `think: false`). None = don't send, use
        # server / chat-template default.
        self.enable_thinking = config.get("enable_thinking", None)
        self.seed = config.get("seed", None)
        self.timeout_seconds = int(config.get("timeout_seconds", 300))

    def complete(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 1000,
        system_prompt: str = "",
        temperature: float = 0.4,
        stop_sequences: list[str] | None = None,
    ) -> ProviderResponse:
        import time

        import httpx

        actual_model = model or self.default_model
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": actual_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if stop_sequences:
            payload["stop"] = stop_sequences
        if self.seed is not None:
            payload["seed"] = self.seed
        if self.enable_thinking is not None:
            # vLLM chat-template kwargs — passed through to the tokenizer's
            # chat template. Qwen thinking models respect enable_thinking.
            payload["chat_template_kwargs"] = {"enable_thinking": self.enable_thinking}

        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.ConnectError as e:
            raise ConnectionError(f"Cannot connect to vLLM at {self.base_url}. Is `vllm serve` running?") from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise RuntimeError(
                    f"Model '{actual_model}' not found on vLLM server. Serve with: vllm serve <model>"
                ) from e
            raise
        latency_ms = int((time.perf_counter() - started) * 1000)

        choices = data.get("choices") or []
        text = choices[0].get("message", {}).get("content", "") if choices else ""
        finish_reason = choices[0].get("finish_reason") if choices else None
        usage = data.get("usage") or {}
        return ProviderResponse(
            text=text,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=actual_model,
            latency_ms=latency_ms,
            metadata={"finish_reason": finish_reason},
        )

    def health_check(self) -> bool:
        import httpx

        try:
            r = httpx.get(f"{self.base_url}/v1/models", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        import httpx

        try:
            r = httpx.get(f"{self.base_url}/v1/models", timeout=5)
            return [m["id"] for m in r.json().get("data", [])]
        except Exception:
            return []
