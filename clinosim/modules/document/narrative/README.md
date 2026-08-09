# `clinosim.modules.document.narrative` — narrative text generation

## Purpose

Narrative-generation subpackage of
[`clinosim.modules.document`](../README.md). Turns a
`NarrativeContext` into a `NarrativeOutput` for each document type,
either through deterministic templates (default) or through an LLM
provider (opt-in per CLI flag).

Follows AD-65 Stage 2 architecture: a `NarrativePass` walks structural
CIF in `(doc_type, language)` group order and delegates the actual
content generation to a constructor-injected `NarrativeGenerator`
(Protocol defined in
[`clinosim/types/document.py`](../../../types/README.md)).

## Scope

- **In scope**: template-based deterministic narrative generation,
  LLM-backed narrative generation (opt-in per section), section-level
  replacement strategy, layer-1 in-memory narrative cache, semantic
  post-check of generated output, fact extraction from CIF for
  narrative inputs.
- **Out of scope**: document-type registry (that lives one level up in
  [`clinosim/modules/document/`](../README.md)), FHIR emission (in
  [`clinosim/modules/output/`](../../output/README.md)), the LLM
  service itself (in [`clinosim/modules/llm_service/`](../../llm_service/README.md)).

## Public API

```python
from clinosim.modules.document.narrative import (
    TemplateNarrativeGenerator,   # Stage 1 deterministic generator
    LLMNarrativeGenerator,        # template base + per-section LLM replacement
    NarrativeCache,               # layer-1 in-memory cache
    apply_replacement_strategy,   # section-replacement dispatcher
)
```

Two `NarrativePass` variants (`TemplateNarrativePass`,
`LLMNarrativePass`) are wired into the enricher registry and consume
the generators above.

## Generators

- **`TemplateNarrativeGenerator`** — deterministic renderer that fills
  section templates with values extracted from `NarrativeContext`. The
  default generator; used by `TemplateNarrativePass` and as the base
  layer of the LLM path.
- **`LLMNarrativeGenerator`** — wraps `TemplateNarrativeGenerator`
  and replaces the sections listed in
  `DocumentTypeSpec.llm_enabled_sections` via
  `apply_replacement_strategy` →
  `LLMService.complete_prompt` (AD-11 opt-in). Provider failure
  falls back to template output per document (never per section) —
  no silent partial generation.

Opt-in is the explicit CLI choice
`narrate --provider bedrock|ollama|mock` (`LLMNarrativePass`). There
is no environment-variable gate.

## Caching

- **Layer 1** — `NarrativeCache` (in-memory, in this subpackage). Key:
  clinical-context hash + template-seed hash. Enables cross-patient
  section reuse when the underlying context is equivalent.
- **Layer 2** — `PromptCache` inside `LLMService` (persistent, disk).
  Not owned by this subpackage; consulted only via `LLMService`.

## Dependencies

- `clinosim.types.document` — `NarrativeGenerator` Protocol,
  `NarrativeContext`, `NarrativeOutput`, `DocumentTypeSpec`.
- `clinosim.modules.document` (upstream) — factory / registry.
- `clinosim.modules.llm_service` — `LLMService` (opt-in, only for
  `LLMNarrativeGenerator`).

## Constants and configuration

- Section templates live in this subpackage as data
  (see the file layout below).
- Provider selection is CLI-only; no runtime env variables.
- `apply_replacement_strategy` decides per-section whether to invoke
  the LLM or fall back to the template; that logic is in
  `replacement_strategy.py`.

## Directory contents

```
clinosim/modules/document/narrative/
  __init__.py               public API
  passes.py                 TemplateNarrativePass, LLMNarrativePass
  template_generator.py     TemplateNarrativeGenerator (Stage 1 renderer)
  llm_generator.py          LLMNarrativeGenerator (Stage 2, LLM path)
  cache.py                  NarrativeCache (layer-1, in-memory)
  registry.py               loader + backwards-compatible re-exports
  context.py                NarrativeContext factory
  scenario_spine.py         disease-scenario spine driving section order
  fact_extractor.py         extract narrative facts from CIF records
  section_extractor.py      section-level fact extraction
  replacement_strategy.py   template-vs-LLM per-section decision
  semantic_check.py         post-generation semantic sanity check
```

## Adding a new document type or template

1. Register the `DocumentTypeSpec` in
   [`clinosim/modules/document/`](../README.md) engine.
2. Add template strings for each section in
   `template_generator.py` (or a section-scoped file it loads).
3. If LLM replacement is desired for any section, list its section
   ID in `DocumentTypeSpec.llm_enabled_sections`.
4. Add a fact extractor in `fact_extractor.py` if new context data
   is required.
5. Add unit tests under `tests/unit/modules/document/narrative/`.

## Testing

```bash
pytest tests/unit/modules/document/narrative/ -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
