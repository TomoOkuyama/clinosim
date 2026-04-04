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
