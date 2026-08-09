# `clinosim.modules.llm_service` — LLM provider integration for narrative generation

## Purpose

Provides the LLM-provider abstraction used by
[`clinosim.modules.document.narrative`](../document/narrative/README.md)
for the LLM-backed narrative pipeline (AD-11 opt-in). Handles provider
selection, prompt caching, cost accounting, and structured-output
parsing.

## Scope

- **In scope**: `LLMService` orchestrator, provider registry,
  concrete providers (Mock / AWS Bedrock / Ollama / OpenAI-compatible),
  layer-2 persistent `PromptCache`, per-run cost accounting, prompt
  registry, response-format handling.
- **Out of scope**: the narrative-text templates themselves (in
  [`clinosim/modules/document/narrative/`](../document/narrative/README.md)),
  section-level replacement strategy (also in the narrative
  subpackage), any non-narrative use of LLMs (the module is scoped to
  narrative generation).

## Public API

```python
from clinosim.modules.llm_service import (
    LLMService,                  # orchestrator (from_config, complete_prompt, cost_report)
    Provider,                    # ABC (health_check, list_models, complete)
    LLMResponse,                 # dataclass (text, tokens, cost, cache_hit, fallback_reason)
)
from clinosim.modules.llm_service.factory import build_from_config_file
```

CLI wiring is in `clinosim.simulator.cli_narrate` which calls
`factory.build_from_config_file`.

## Providers

| Provider | File | Purpose |
|---|---|---|
| Mock | `providers/mock.py` | Deterministic canned responses for tests and offline dev. |
| AWS Bedrock | `providers/bedrock.py` | Anthropic Claude on AWS Bedrock. |
| Ollama | `providers/ollama.py` | Local self-hosted models via Ollama. |
| OpenAI-compatible | `providers/openai.py` | Any endpoint speaking the OpenAI Chat Completions API. |

Adding a new provider:

1. Create `providers/<name>.py` implementing the `Provider` ABC
   (`health_check`, `list_models`, `complete`).
2. Register it in `providers/__init__.py`.
3. Add a corresponding config YAML at
   `clinosim/config/llm_service.<name>.yaml`.
4. Add unit tests.

## Prompt layout

Prompts live under `prompts/`, split by language:

```
prompts/
  en/                     English prompt templates
    <section>.jinja
  ja/                     Japanese prompt templates
    <section>.jinja
```

Templates are jinja-style with `{{variable}}` placeholders. The
`PromptRegistry` (`prompt_registry.py`) loads them lazily; use its
`.has(name)` probe before invoking to decide whether the section is
LLM-eligible for the given language.

## Dependencies

- `clinosim.types.config` — LLM-service config models.
- `pyyaml` — config-file loading.
- `httpx` — HTTP transport for Bedrock / Ollama / OpenAI-compatible.
- No dependency on `clinosim.modules.document.*` (one-way boundary).

## Constants and configuration

- Cost accounting per provider (`fallback_on_budget_exceeded`,
  `max_tokens_per_run`, `timeout_seconds`) — see
  `clinosim/types/config.py`.
- Cache tuning (`cache_enabled`, `cache_max_entries`,
  `cache_persist_to_disk`) — same location.
- Runtime provider selection is CLI-only (`narrate --provider`); no
  environment-variable gate.
- Default configs at:
  - `clinosim/config/llm_service.yaml`
  - `clinosim/config/llm_service.bedrock.yaml`
  - `clinosim/config/llm_service.cloud.yaml`

## Directory contents

```
clinosim/modules/llm_service/
  __init__.py               public API
  engine.py                 LLMService orchestrator
  factory.py                build_from_config_file (CLI hook)
  prompt_registry.py        PromptRegistry (loader + has() probe)
  providers/
    __init__.py             provider registry
    base.py                 Provider ABC (health_check, list_models, complete)
    mock.py                 MockProvider
    bedrock.py              AWS Bedrock provider
    ollama.py               local Ollama provider
    openai.py               OpenAI-compatible provider
  prompts/
    en/                     English prompt templates
    ja/                     Japanese prompt templates
```

## Testing

```bash
pytest tests/unit -k llm_service -q
pytest tests/integration -k llm -q
```

Integration tests use the Mock provider so no network is required.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
