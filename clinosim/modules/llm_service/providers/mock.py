"""Mock LLM provider. Deterministic text output without any network call."""

from __future__ import annotations

from typing import Any

from .base import ProviderResponse


class MockProvider:
    """Deterministic provider for tests and template-free dry runs.

    Returns a predictable stub that embeds a snippet of the user prompt so
    integration tests can assert the prompt was correctly built.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.call_count = 0
        self.last_prompt = ""
        self.last_system_prompt = ""
        self.last_model = ""

    def complete(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 1000,
        system_prompt: str = "",
        temperature: float = 0.4,
        stop_sequences: list[str] | None = None,
    ) -> ProviderResponse:
        self.call_count += 1
        self.last_prompt = prompt
        self.last_system_prompt = system_prompt
        self.last_model = model or "mock"

        # Produce a stable, prompt-aware stub so tests can assert routing worked.
        snippet = prompt.strip().splitlines()[0] if prompt.strip() else ""
        # Session-88j bundle strategy: when the prompt asks for a JSON
        # object with a specific schema (session-88j narrative_seed_bundle
        # rendered `output_schema_block` as a JSON snippet), emit a
        # matching JSON object so `_parse_bundle_response` succeeds without
        # falling back to per-section. Detects the schema by looking for
        # the literal `<rewritten section body>` placeholder the prompt
        # emits for every requested section key.
        placeholder = "<rewritten section body>"
        if placeholder in prompt:
            import json as _json
            import re as _re

            keys = _re.findall(rf'"([^"]+)":\s*"{_re.escape(placeholder)}"', prompt)
            obj = {k: f"[Mock LLM response #{self.call_count} — {k}]" for k in keys}
            body = _json.dumps(obj, ensure_ascii=False)
        else:
            body = (
                f"[Mock LLM response #{self.call_count}]\nModel: {self.last_model}\nFirst prompt line: {snippet[:120]}"
            )
        return ProviderResponse(
            text=body,
            input_tokens=max(1, len(prompt.split())),
            output_tokens=max(1, len(body.split())),
            model=self.last_model,
            latency_ms=0,
        )

    def health_check(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return ["mock"]
