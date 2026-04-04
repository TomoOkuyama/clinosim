# llm_service

Central LLM integration service. All LLM calls from all modules go through this service (AD-11). JUDGMENT and NARRATIVE can use different providers (AD-24).

## Public API

```python
from clinosim.modules.llm_service.engine import (
    LLMService,
    LLMTaskType,
    ClinicalEventData,
    PatientSummary,
    LLMResponse,
)

llm = LLMService(mode="template")  # "none" | "template" | "llm"
response = llm.generate(LLMTaskType.PROGRESS_NOTE, event_data)
```

### `LLMService.generate(task_type, event) -> LLMResponse`
Single entry point. Modules pass structured `ClinicalEventData`, never prompts. The service handles prompt construction, model selection, caching, and fallback.

### Task categories
- **JUDGMENT** (always English): DIAGNOSTIC_REASONING, TREATMENT_DECISION, CLINICAL_JUDGMENT, CONSISTENCY_REVIEW
- **NARRATIVE** (target language): CHIEF_COMPLAINT, ADMISSION_HP, PROGRESS_NOTE, DISCHARGE_SUMMARY, NURSING_NOTE

## How to add a new LLM provider

Providers live in `clinosim/modules/llm_service/providers.py`. Each provider is a class
that exposes a single method:

```python
def complete(
    self,
    prompt: str,
    model: str | None = None,
    max_tokens: int = 1000,
    system_prompt: str = "",
) -> ProviderResponse:
    ...
```

`ProviderResponse` is a dataclass with fields `text`, `input_tokens`, `output_tokens`,
`model`, and `latency_ms`. Steps to add a provider:

1. Add a new class in `providers.py` (see `OllamaProvider` as the reference implementation
   and `MockProvider` for a minimal skeleton).
2. Accept a `config: dict | None` in `__init__` for endpoint URL, auth headers, etc.
3. Implement `complete()`. On connection or HTTP errors, raise an exception — the
   `LLMService._llm_generate()` loop will retry up to 3 times and then fall back to the
   template generator.
4. Optionally implement `health_check() -> bool` and `list_models() -> list[str]` for
   operator tooling.
5. Instantiate the provider and pass it to `LLMService` via the `judgment_provider` or
   `narrative_provider` constructor arguments. The two task categories can use different
   providers (AD-24):
   ```python
   from clinosim.modules.llm_service.providers import MyNewProvider
   llm = LLMService(
       mode="llm",
       judgment_provider=MyNewProvider({"endpoint": "...", "api_key": "..."}),
       narrative_provider=OllamaProvider(),
   )
   ```

## How to add a new prompt template

Prompt templates are split into two functions in `engine.py`:

- **`_build_prompt()`** — used in `"llm"` mode; returns `(system_prompt, user_prompt)`
  strings sent to the actual LLM.
- **Template generators** (e.g. `_progress_note()`, `_discharge_summary()`) — used in
  `"template"` mode; return plain text without any LLM call.

To add a new task type:

1. Add a new value to the `LLMTaskType` enum and register its category in `TASK_CATEGORY`.
2. In `_template_generate()`, add a `case LLMTaskType.MY_NEW_TASK:` branch that calls a
   new helper function `_my_new_template(ps, ed, language) -> str`.
3. In `_build_prompt()`, add a matching `case` branch returning appropriate system and
   user prompts.
4. Write the template helper. It receives `PatientSummary` (patient context) and the
   `event_data` dict (caller-supplied structured data). For bilingual templates, branch on
   `language == "ja"` vs `"en"`.

Example skeleton:
```python
def _my_new_template(ps: PatientSummary, ed: dict, language: str) -> str:
    key_value = ed.get("my_key", "default")
    if language == "ja":
        return f"【新テンプレート】{key_value}"
    return f"New template: {key_value}"
```

## Dependencies
- None for template mode
- `httpx` for LLM mode (Ollama, Bedrock, etc.)

## Configuration
- `src/clinosim/config/llm_service.yaml` — default (local Ollama)
- `src/clinosim/config/llm_service.cloud.yaml` — cloud (Anthropic API)

## Testing
```bash
source .venv/bin/activate && python -m pytest tests/unit/test_llm_service.py -v
```

## Implementation status
- [x] Template mode (rule-based text generation)
- [x] JUDGMENT/NARRATIVE task category routing
- [x] Japanese and English template generators (chief complaint, progress note, discharge summary, admission H&P, diagnostic reasoning, treatment decision)
- [ ] Ollama provider (local Llama)
- [ ] Anthropic direct provider
- [ ] Bedrock gateway provider
- [ ] OpenAI-compatible provider
- [ ] Response caching
- [ ] Graceful degradation (retry → fallback)
- [ ] Cost tracking
