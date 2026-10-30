# `clinosim.modules.llm_service` — single LLM gateway (AD-11)

## Purpose

The single gateway every other module uses for LLM calls (AD-11 —
"LLM calls only via `llm_service`", AD-24). Provider SDKs
(Ollama / Bedrock / vLLM / mock) are **never** called directly by
any other module. Owns task-type enums, prompt construction,
response validation, prompt caching, and provider selection.

## Scope

- **In scope**: `LLMService` (top-level orchestrator, sync +
  concurrency-safe call surface); `LLMTaskType` /
  `LLMTaskCategory` (StrEnum task inventory);
  `TASK_CATEGORY` (task → category map); `DOCUMENT_LOINC` /
  `loinc_for(task_type)` (LOINC code per document-generation task);
  `PatientSummary` + `ClinicalEventData` (input DTOs);
  `LLMResponse` + `LLMCompletionError`; document-task validation
  (`_validate_document_task_sync`); per-task prompt builders
  (`_build_prompt` dispatch + language-specific
  `_jp_chief_complaint`, `_en_chief_complaint`, `_progress_note`,
  `_discharge_summary`, `_admission_hp`, `_diagnostic_reasoning`,
  `_treatment_decision`, `_death_summary_template`,
  `_operative_note_template`, `_procedure_note_template`);
  `PromptRegistry` + `PromptSpec` (per-task prompt manifest);
  `PromptCache` (SHA-256 keyed disk cache for reproducibility +
  Stage 2 re-run economy); `build_from_config` +
  `build_from_config_file` factory; the four bundled providers under
  `providers/` (`bedrock`, `ollama`, `vllm`, `mock`) plus their
  aliases (`local` → `ollama`, `openai_compatible` → `vllm`).
- **Out of scope**: narrative-content assembly / template rendering
  ([`clinosim.modules.document.narrative`](../document/narrative/README.md)
  owns the two-pass narrative generation and imports `LLMService`);
  cost tracking / accounting; FHIR emission
  ([`clinosim.modules.output`](../output/README.md)).

## Public API

Every downstream module imports from the package root; the 18
symbols below (`__all__`) are the entire public surface:

```python
from clinosim.modules.llm_service import (
    # Core
    LLMService,                  # top-level gateway (sync + concurrency-safe)
    LLMTaskType,                 # StrEnum task inventory (per judgment + narrative task)
    LLMTaskCategory,             # StrEnum {"judgment", "narrative"}
    LLMResponse,                 # normalised response dataclass
    LLMCompletionError,          # RuntimeError subclass

    # Task metadata
    TASK_CATEGORY,               # {LLMTaskType: LLMTaskCategory}
    DOCUMENT_LOINC,              # {LLMTaskType: LOINC code}
    loinc_for,                   # (task_type) -> LOINC | None

    # Input DTOs
    PatientSummary,
    ClinicalEventData,

    # Factory + registry
    build_from_config,           # (config_dict) -> LLMService
    build_from_config_file,      # (path) -> LLMService
    PromptRegistry,
    PromptSpec,
    PromptCache,

    # Provider surface (see providers/README.md)
    LLMProvider,                 # Protocol
    ProviderResponse,            # dataclass
    MockProvider,                # deterministic fixture for tests
)
```

## Determinism

- The `LLMService.generate(...)` / `LLMService.complete_prompt(...)`
  paths are deterministic when `PromptCache` is enabled AND the
  underlying provider is either `MockProvider` or a real provider
  with `temperature=0`. Cache keys are
  `sha256(system_prompt + user_prompt + model)` (`PromptCache._hash`;
  task type and temperature are not part of the key) so the cache is
  content-addressed.
- Concurrency safety: `PromptCache` guards its counters with a
  `threading.Lock` and writes entries atomically (temp file +
  `os.replace`); `LLMService` itself holds no per-call lock. The
  `tests/unit/test_narrate_concurrency_byte_identity.py` test pins
  the byte-identity contract across `concurrency=1` and
  `concurrency=8` narrate runs.
- Stage 2 re-run economy: after a failed narrate, identical prompts
  do not re-invoke the LLM — `PromptCache` returns the prior JSON
  entry. See [`cache.py`](cache.py) for the on-disk layout
  (`<cache_dir>/<sha256_prefix>/<sha256>.json`).

## Dependencies

- `clinosim.modules.llm_service.providers` — the `LLMProvider`
  Protocol + four concrete providers (bedrock / ollama / vllm /
  mock).
- Provider SDKs (loaded lazily by each provider file, not by
  `llm_service` itself): `boto3` (bedrock), `httpx` (ollama + vllm).
- `hashlib.sha256` — cache key derivation.
- `yaml` — config-file loader in `factory.py`.
- No dependency on any other `clinosim.modules.*` (this module is
  a leaf that every other module may depend on).

## Constants and configuration

- **`LLMTaskType`** (StrEnum) — the full enumerated task inventory
  (24 values: 4 judgment tasks — `diagnostic_reasoning`,
  `treatment_decision`, `clinical_judgment`, `consistency_review` —
  and 20 narrative tasks, e.g. `chief_complaint`, `admission_hp`,
  `progress_note`, `discharge_summary`, `death_summary`,
  `operative_note`, `procedure_note`, the nursing / ED / care-plan
  document types, `referral_note`, `health_checkup_report`,
  `death_certificate`, `death_discharge_summary`). Every
  `clinosim.types.document.DocumentType` value must exist here
  (`_validate_document_task_sync`, checked at import).
- **`TASK_CATEGORY`** — `{LLMTaskType: LLMTaskCategory}` mapping so
  a caller can gate on category (judgment vs narrative) without
  hard-coding a task list; selects the judgment vs narrative
  provider. Data lives in
  [`reference_data/task_categories.yaml`](reference_data/task_categories.yaml).
- **`DOCUMENT_LOINC`** — LOINC code per document-generation task,
  used by FHIR builders through `loinc_for(task_type)` so a new
  document type registers its LOINC once and every consumer looks
  it up from the same map. Data lives in
  [`reference_data/task_loincs.yaml`](reference_data/task_loincs.yaml).
- **Prompt manifest**: [`prompts/{en,ja}/`](prompts/) — per-language
  prompt files loaded by `PromptRegistry`. Adding a new language
  is a matter of adding the folder + `PromptSpec` entries; no
  engine code change.
- **Config schema** (consumed by `build_from_config`; examples in
  [`clinosim/config/llm_service*.yaml`](../../config/)): top-level
  `judgment` / `narrative` sections, each with `provider` (a
  registry key from `providers/`: `local` / `ollama` / `bedrock` /
  `vllm` / `openai_compatible` / `mock`, or one added via
  `register_provider`), `mode` (`"llm" | "template" | "none"`;
  `template` / `none` build no provider), `model_map` (`small` /
  `medium` / `large` → actual model IDs), a provider-specific
  sub-block named after the provider key, and (narrative section)
  `retry_attempts` / `retry_backoff_seconds`; plus `cache`
  (`enabled`, `directory` / `cache_dir`, `max_entries`) and
  `prompts.registry_path`.

## Directory contents

```
clinosim/modules/llm_service/
  __init__.py                    public API surface (18 symbols)
  engine.py                      LLMService + task enums + prompt builders (~950 LOC)
  factory.py                     build_from_config + build_from_config_file
  prompt_registry.py             PromptRegistry + PromptSpec
  cache.py                       PromptCache (SHA-256 keyed disk cache)
  prompts/
    en/                          English prompt manifest
    ja/                          Japanese prompt manifest
  reference_data/
    task_categories.yaml         LLMTaskType -> judgment / narrative (TASK_CATEGORY)
    task_loincs.yaml             LLMTaskType -> LOINC (DOCUMENT_LOINC)
  providers/                     LLMProvider Protocol + 4 bundled providers (bedrock/ollama/vllm/mock); anthropic_direct is not bundled (register via register_provider)
  SPEC.md                        extended design reference (not runtime)
```

The module has **no `audit.py` and no `enricher.py`**.

## Enricher wiring

Not applicable — this module is a leaf library called from the
narrative and CLI paths. It is not registered with
`register_builtin_enrichers` and has no seed offset in
`ENRICHER_SEED_OFFSETS`.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Narrative pass | [`clinosim/modules/document/narrative/llm_generator.py`](../document/narrative/llm_generator.py), [`replacement_strategy.py`](../document/narrative/replacement_strategy.py), [`passes.py`](../document/narrative/passes.py) | Stage 2 narrative generation calls `LLMService.complete_prompt(...)` per document type. |
| CLI `narrate` subcommand | [`clinosim/simulator/cli_narrate.py`](../../simulator/cli_narrate.py) | Boot: builds `LLMService` from `--llm-config` (or the bundled `config/llm_service*.yaml` / in-code `MockProvider` per `--provider`; `PromptCache` is wired by `build_from_config`), then runs `LLMNarrativePass`. |

## Testing

```bash
pytest tests/unit -k "llm" -q
```

Individual files:

- [`tests/unit/test_llm_service.py`](../../../tests/unit/test_llm_service.py)
  — `LLMService.generate` orchestration.
- [`tests/unit/test_llm_service_complete_prompt.py`](../../../tests/unit/test_llm_service_complete_prompt.py)
  — `LLMService.complete_prompt` (retry, PromptCache, no template fallback).
- [`tests/unit/test_llm_task_enum_sync.py`](../../../tests/unit/test_llm_task_enum_sync.py)
  — `LLMTaskType` ↔ `TASK_CATEGORY` ↔ `DOCUMENT_LOINC` coverage
  invariants.
- [`tests/unit/test_llm_narrative_pass.py`](../../../tests/unit/test_llm_narrative_pass.py)
  — narrative-pass integration through `LLMService`.
- [`tests/unit/test_narrate_concurrency_byte_identity.py`](../../../tests/unit/test_narrate_concurrency_byte_identity.py)
  — concurrency safety (`concurrency=1` vs `concurrency=8` narrate
  produces identical output).
- [`tests/unit/test_clinical_documents.py`](../../../tests/unit/test_clinical_documents.py)
  — cross-module document emission guards.
- Fixture packs under [`tests/fixtures/patient_profiles/`](../../../tests/fixtures/patient_profiles/)
  — `*.llm-expectations.yaml` + `*.llm-mock.golden.json` per-profile
  golden narratives used by the mock provider.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
