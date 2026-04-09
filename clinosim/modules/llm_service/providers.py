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


class BedrockProvider:
    """Amazon Bedrock provider for Claude models."""

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self.region = config.get("region", "us-east-1")
        self.default_model = config.get("model", "anthropic.claude-3-5-sonnet-20241022-v2:0")
        self.profile_name = config.get("profile_name")  # Optional AWS profile
        self._client = None

    def _get_client(self):
        """Lazy initialization of boto3 client."""
        if self._client is None:
            try:
                import boto3
                session_kwargs = {"region_name": self.region}
                if self.profile_name:
                    session_kwargs["profile_name"] = self.profile_name
                session = boto3.Session(**session_kwargs)
                self._client = session.client("bedrock-runtime")
            except ImportError:
                raise RuntimeError(
                    "boto3 is required for BedrockProvider. "
                    "Install with: pip install boto3"
                )
            except Exception as e:
                raise RuntimeError(
                    f"Failed to create Bedrock client: {e}. "
                    "Ensure AWS credentials are configured."
                )
        return self._client

    def complete(self, prompt: str, model: str | None = None,
                 max_tokens: int = 1000, system_prompt: str = "") -> ProviderResponse:
        import json
        import time

        client = self._get_client()
        actual_model = model or self.default_model

        # Build messages for Claude 3 API
        messages = [{"role": "user", "content": prompt}]

        # Build request body
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": messages,
            "temperature": 0.7,
        }

        if system_prompt:
            body["system"] = system_prompt

        start_time = time.time()

        try:
            response = client.invoke_model(
                modelId=actual_model,
                body=json.dumps(body),
            )

            response_body = json.loads(response["body"].read())
            latency_ms = int((time.time() - start_time) * 1000)

            # Extract text from Claude 3 response format
            content = response_body.get("content", [])
            text = ""
            for block in content:
                if block.get("type") == "text":
                    text += block.get("text", "")

            # Extract token usage
            usage = response_body.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)

            return ProviderResponse(
                text=text,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=actual_model,
                latency_ms=latency_ms,
            )

        except client.exceptions.ValidationException as e:
            raise ValueError(f"Invalid request to Bedrock: {e}")
        except client.exceptions.ModelNotReadyException:
            raise RuntimeError(
                f"Model '{actual_model}' is not ready. "
                "Check model availability in your region."
            )
        except client.exceptions.ThrottlingException:
            raise RuntimeError("Bedrock API throttling. Retry with backoff.")
        except Exception as e:
            raise RuntimeError(f"Bedrock API error: {e}")

    def health_check(self) -> bool:
        """Check if Bedrock client can be initialized."""
        try:
            self._get_client()
            return True
        except Exception:
            return False


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
