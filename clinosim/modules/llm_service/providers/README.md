# `clinosim.modules.llm_service.providers` — LLM provider plug-in registry

## Purpose

Backends that [`clinosim.modules.llm_service`](../README.md) can dispatch
to for narrative generation. Every provider implements the
[`LLMProvider` Protocol](base.py) so that `LLMService` can swap
backends purely from config (AD-11 / AD-24).

The parent package owns orchestration (prompt cache, cost accounting,
fallback ordering, response-format handling). This subpackage owns the
provider implementations and the registry that maps a config-name to
an instantiator.

## Scope

- **In scope**: `LLMProvider` Protocol, `ProviderResponse` dataclass,
  the four bundled providers (`mock`, `ollama`, `bedrock`, and the
  `local` alias for `ollama`), and the `_REGISTRY` /
  `register_provider` / `build_provider` plug-in surface.
- **Out of scope**: prompt templates, layer-2 disk cache, per-run cost
  aggregation — those live in [`clinosim.modules.llm_service`](../README.md).

## Bundled providers

| File | Registered under | Purpose |
| --- | --- | --- |
| `mock.py` | `mock` | Deterministic canned response for tests and template-free dry runs. No network I/O. Records `call_count` / `last_prompt` / `last_model` for assertions. |
| `ollama.py` | `ollama`, `local` | Local self-hosted models via the [Ollama](https://ollama.com/) HTTP API. Default for development. Config: `endpoint` (default `http://localhost:11434`), `model` (default `llama3.1:8b`). |
| `bedrock.py` | `bedrock` | AWS Bedrock via the Converse API (uniform across Claude / Llama / Mistral). Lazy `boto3` import so clinosim doesn't require AWS SDK on hosts that never use Bedrock. Config: `region`, `profile` (or default AWS credential chain), `model_id`, optional `inference_profile_arn` for cross-region inference profiles. |

Interface + response types shared by all providers:

- `base.LLMProvider` — `@runtime_checkable` Protocol with a single
  `complete(prompt, model, max_tokens, system_prompt, temperature, stop_sequences)`
  method. Implementations raise on error; the caller (`LLMService`)
  handles retry / fallback / cost tallying.
- `base.ProviderResponse` — unified dataclass: `text`, `input_tokens`,
  `output_tokens`, `model`, `latency_ms`, `metadata` (arbitrary
  provider-specific fields such as stop reason, safety flags, cost
  estimate).

## Registry API

The registry maps a config-name to a builder callable that turns a
config `dict` into a provider instance:

```python
_REGISTRY: dict[str, Callable[[dict[str, Any]], Any]] = {
    "local":   lambda cfg: OllamaProvider(cfg),
    "ollama":  lambda cfg: OllamaProvider(cfg),
    "bedrock": lambda cfg: BedrockProvider(cfg),
    "mock":    lambda cfg: MockProvider(cfg),
}
```

`build_provider(provider_name, provider_config)` is what `LLMService`
calls at startup. Unknown names raise `ValueError` with the current
registered set listed.

## Ship-your-own provider

Third-party or user code can extend the registry at runtime without
editing the bundled `__init__.py`:

```python
from typing import Any
from clinosim.modules.llm_service.providers import (
    ProviderResponse,
    register_provider,
)


class MyCustomProvider:
    """Any class that satisfies base.LLMProvider Protocol works — no ABC subclass required."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def complete(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 1000,
        system_prompt: str = "",
        temperature: float = 0.4,
        stop_sequences: list[str] | None = None,
    ) -> ProviderResponse:
        # ...call your backend, return a ProviderResponse
        return ProviderResponse(text="...", output_tokens=42, model=model or "mine")


register_provider("my_custom", lambda cfg: MyCustomProvider(cfg))
```

Once registered, the provider is selectable from the standard
`LLMService` config exactly like a bundled one:

```yaml
# clinosim/config/llm_service.my_custom.yaml
provider: my_custom
provider_config:
  api_key_env: MY_CUSTOM_API_KEY
  # ...
```

The Protocol is structural (`@runtime_checkable`) so nothing has to
inherit from `LLMProvider` — matching the method signature is enough.

## Cross-references

- Parent orchestrator: [`clinosim.modules.llm_service`](../README.md)
- Narrative consumer:
  [`clinosim.modules.document.narrative`](../../document/narrative/README.md)
- AWS Bedrock setup guide: [`docs/bedrock_setup.md`](../../../../docs/bedrock_setup.md)
- Provider config files: `clinosim/config/llm_service.<name>.yaml`
