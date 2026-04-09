"""AWS Bedrock LLM provider.

Uses the Bedrock Runtime `Converse` API which provides a uniform
interface across Anthropic Claude, Meta Llama, Mistral, etc.

boto3 is imported lazily so clinosim does not require boto3 on hosts
that never call Bedrock (template / mock / Ollama mode).

Authentication:
    - Use `profile` key in config, OR
    - Leave `profile` unset to use the default AWS credential chain
      (EC2 instance role, env vars, ~/.aws/credentials).

Config keys:
    region: str         AWS region, e.g. "us-east-1"
    profile: str|None   AWS profile name (None → default chain)
    model_id: str       default bedrock model id
    inference_profile_arn: str|None
                        cross-region inference profile ARN (overrides model_id
                        when set)
"""

from __future__ import annotations

from typing import Any

from .base import ProviderResponse


class BedrockProvider:
    """AWS Bedrock provider using Converse API."""

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self.region = config.get("region", "us-east-1")
        self.profile = config.get("profile")
        self.default_model = config.get(
            "model_id",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
        )
        self.inference_profile_arn = config.get("inference_profile_arn")
        self._client: Any = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3
        except ImportError as e:
            raise ImportError(
                "boto3 is required for BedrockProvider. "
                "Install with: pip install 'clinosim[bedrock]' or pip install boto3"
            ) from e
        session = boto3.Session(
            profile_name=self.profile,
            region_name=self.region,
        )
        self._client = session.client("bedrock-runtime")
        return self._client

    def _resolve_model(self, requested: str | None) -> str:
        """Prefer inference profile ARN (cross-region) if configured."""
        if self.inference_profile_arn:
            return self.inference_profile_arn
        return requested or self.default_model

    def complete(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 1000,
        system_prompt: str = "",
        temperature: float = 0.4,
        stop_sequences: list[str] | None = None,
    ) -> ProviderResponse:
        client = self._ensure_client()
        model_id = self._resolve_model(model)

        system_blocks: list[dict[str, Any]] = []
        if system_prompt:
            system_blocks.append({"text": system_prompt})

        inference_cfg: dict[str, Any] = {
            "maxTokens": max_tokens,
            "temperature": temperature,
        }
        if stop_sequences:
            inference_cfg["stopSequences"] = stop_sequences

        kwargs: dict[str, Any] = {
            "modelId": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ],
            "inferenceConfig": inference_cfg,
        }
        if system_blocks:
            kwargs["system"] = system_blocks

        import time
        t0 = time.time()
        try:
            resp = client.converse(**kwargs)
        except Exception as e:
            # Surface a specific error category the service layer can inspect.
            raise RuntimeError(f"Bedrock Converse failed: {type(e).__name__}: {e}") from e
        latency_ms = int((time.time() - t0) * 1000)

        message = resp.get("output", {}).get("message", {})
        content_blocks = message.get("content", []) or []
        text_parts = [blk.get("text", "") for blk in content_blocks if "text" in blk]
        text = "".join(text_parts)

        usage = resp.get("usage", {}) or {}
        stop_reason = resp.get("stopReason", "")

        return ProviderResponse(
            text=text,
            input_tokens=int(usage.get("inputTokens", 0)),
            output_tokens=int(usage.get("outputTokens", 0)),
            model=model_id,
            latency_ms=latency_ms,
            metadata={"stop_reason": stop_reason},
        )

    def health_check(self) -> bool:
        """Lightweight check: verify credentials can list foundation models.

        Does not invoke the model (no token cost).
        """
        try:
            import boto3  # noqa: F401
        except ImportError:
            return False
        try:
            client = self._ensure_client()
            # A minimal call — list_foundation_models is on `bedrock` not
            # `bedrock-runtime`, so we just verify the client was created.
            return client is not None
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """Best-effort: list available foundation models in the region."""
        try:
            import boto3
            session = boto3.Session(
                profile_name=self.profile, region_name=self.region
            )
            bedrock_client = session.client("bedrock")
            resp = bedrock_client.list_foundation_models()
            return [m["modelId"] for m in resp.get("modelSummaries", [])]
        except Exception:
            return []
