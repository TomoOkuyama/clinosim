# `clinosim.modules.llm_service.providers` — LLM provider plug-in registry

## Purpose

Concrete LLM backends that
[`clinosim.modules.llm_service`](../README.md) dispatches to. Every
provider implements the `LLMProvider` Protocol so `LLMService` can
swap backends purely from config (AD-11 / AD-24). The parent package
owns orchestration (prompt cache, cost accounting, task-type
dispatch); this subpackage owns implementations + the registry.

## Scope

- **In scope**: `LLMProvider` Protocol (`base.py`), `ProviderResponse`
  dataclass, the five bundled provider implementations (`mock`,
  `ollama` + `local` alias, `bedrock`, `vllm` + `openai_compatible`
  alias), the `_REGISTRY` mapping, and the plug-in surface
  (`register_provider` + `build_provider`).
- **Out of scope**: prompt templates, response caching, task-type
  dispatch, LOINC mapping — all in
  [`clinosim.modules.llm_service`](../README.md).

## Public API

```python
from clinosim.modules.llm_service.providers import (
    LLMProvider,             # Protocol
    ProviderResponse,        # dataclass (text, input_tokens, output_tokens, model, latency_ms, metadata)
    MockProvider,            # deterministic, no I/O (tests + template-free dry runs)
    OllamaProvider,          # local self-hosted models (HTTP API)
    BedrockProvider,         # AWS Bedrock via Converse API
    VLLMProvider,            # vLLM + any OpenAI-compatible endpoint
    build_provider,          # (provider_name, provider_config) -> provider instance
    register_provider,       # (name, builder_callable) -> None (third-party extension)
)
```

The registry (`_REGISTRY` in `__init__.py`) maps config-section
names → provider builders:

| Config name | Builder |
|---|---|
| `mock` | `MockProvider(cfg)` |
| `ollama` | `OllamaProvider(cfg)` |
| `local` | `OllamaProvider(cfg)` (alias) |
| `bedrock` | `BedrockProvider(cfg)` |
| `vllm` | `VLLMProvider(cfg)` |
| `openai_compatible` | `VLLMProvider(cfg)` (alias) |

`anthropic_direct` is not bundled — third-party code can register it
via `register_provider("anthropic_direct", builder)`.

## Determinism

- `MockProvider` is fully deterministic (returns canned text based on
  the prompt hash / manifest lookup); it records `call_count`,
  `last_prompt`, `last_model` so tests can assert.
- The three networked providers are deterministic ONLY when the
  configured `temperature=0` AND the same model version is served
  by the backend. The parent-level `PromptCache` layer restores
  byte-identity across re-runs when both conditions hold, because
  the cache is content-addressed.

## Dependencies

- Standard library only for `base.py` + `mock.py` + `__init__.py`.
- `boto3` — lazily imported by `bedrock.py` (`import boto3` is inside
  `BedrockProvider.__init__`) so clinosim boot does not require the
  AWS SDK on hosts that never use Bedrock.
- `httpx` — required by `ollama.py` + `vllm.py` for HTTP calls.
- No dependency on any other `clinosim.modules.*`; no dependency on
  the rest of `llm_service` (this is a pure-implementation layer).

## Constants and configuration

- **`LLMProvider` Protocol** (`base.py`) — `@runtime_checkable`,
  single method `complete(prompt, model, max_tokens, system_prompt,
  temperature, stop_sequences) -> ProviderResponse`. Implementations
  raise on error; the caller (`LLMService`) handles retry / fallback
  / cost tallying.
- **`ProviderResponse` fields** — `text`, `input_tokens`,
  `output_tokens`, `model`, `latency_ms`, `metadata`
  (`dict[str, Any] | None` for arbitrary provider-specific fields
  like stop reason, safety flags, cost estimate).
- **Per-provider config shape** — each provider's `__init__(cfg: dict)`
  documents the config keys it consumes; see the docstrings in
  `bedrock.py`, `ollama.py`, `vllm.py`, `mock.py`.

## Directory contents

```
clinosim/modules/llm_service/providers/
  __init__.py                    registry + build_provider + register_provider
  base.py                        LLMProvider Protocol + ProviderResponse
  mock.py                        MockProvider — deterministic, no I/O
  ollama.py                      OllamaProvider — local Ollama HTTP API
  bedrock.py                     BedrockProvider — AWS Bedrock Converse API (lazy boto3)
  vllm.py                        VLLMProvider — vLLM + any OpenAI-compatible endpoint
```

The subpackage has **no `audit.py`, no `enricher.py`, no
`reference_data/`** — data (prompts + config) lives in
`clinosim.modules.llm_service` above.

## Enricher wiring

Not applicable — subpackage of a leaf library. No entry in
`register_builtin_enrichers`, no seed offset.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| `LLMService` construction | [`clinosim/modules/llm_service/factory.py`](../factory.py) | `_build_provider_from_section` → `build_provider(name, cfg)`. |
| Package re-export | [`clinosim/modules/llm_service/__init__.py`](../__init__.py) | `LLMProvider`, `ProviderResponse`, `MockProvider` are re-exported at the parent package root. |
| Third-party extension | (user code) | `register_provider(name, builder)` adds a custom provider without editing this file. |

## Testing

Provider-specific unit tests live under `tests/unit/` alongside the
`llm_service` tests — they typically instantiate `MockProvider`
directly to keep runs I/O-free. There is no dedicated test file
per network provider (Bedrock / Ollama / vLLM) — their behaviour is
covered end-to-end through the narrative pass with `--llm-config`
switched to the respective backend.

Coverage gap: individual provider unit tests (config parsing, error
translation, retry semantics) are a low-cost follow-up.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
