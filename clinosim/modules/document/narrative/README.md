# `clinosim.modules.document.narrative` — Stage 2 narrative generation pipeline

## Purpose

Implements the AD-65 Stage 2 narrative pass. `NarrativePass` walks
structural CIF (produced by
[`clinosim.modules.document`](../README.md) as stubs with
`narrative=None`) in (doc_type, language) group order and hands each
document to a `NarrativeGenerator`. Two generators exist:

- **`TemplateNarrativeGenerator`** — Stage 1 deterministic renderer;
  the default `TemplateNarrativePass` uses it and it also serves as
  the base layer inside the LLM path.
- **`LLMNarrativeGenerator`** — wraps the template generator and
  replaces `DocumentTypeSpec.llm_enabled_sections` with LLM output
  via `LLMService.complete_prompt` (AD-11 — all LLM calls through
  [`clinosim.modules.llm_service`](../../llm_service/README.md)).
  Provider failure falls back per document to template output. Opt-in
  is the explicit CLI choice
  `clinosim narrate --provider bedrock|ollama|mock` — no env gate.

`NarrativeCache` is the layer-1 in-memory cache (clinical-context +
template-seed-hash key) for cross-patient section reuse; the layer-2
disk `PromptCache` lives inside `llm_service`.

## Scope

- **In scope**: two-pass architecture (`NarrativePass` abstract +
  `TemplateNarrativePass` + `LLMNarrativePass`); the two generators;
  `apply_replacement_strategy` per-section dispatch (`template_only`
  / LLM-driven); prompt-construction pipeline
  (`context.py` CIF→ctx factory, `scenario_spine.py` DiseaseProtocol
  → NarrativeSpine, `fact_extractor.py` FactTag materialisation
  (AD-65 E2 — β-JP-1 refuses numbers not in `materialized_facts`),
  `section_extractor.py` per-COMPOSITION-section slicing (AD-65 E3)),
  `template_generator.py` placeholder engine (large — vitals /
  discharge / home-med / hedging placeholder resolution),
  chronic-disease SOAP resolver (`_chronic_soap.py` — the 32
  disease YAMLs cover acute inpatient only; chronic conditions
  appear as ICD-10 codes and need a separate SOAP template
  library), hedging phrase pool (`_hedging.py` — enforces
  "Template = adequate density on its own"), narrative-interpretation
  thresholds (`_narrative_interpretation_thresholds.py`), narrative
  cache (`cache.py`), semantic-check gate (`semantic_check.py` —
  the verification gate for non-deterministic LLM output where
  byte-diff no longer applies), `DocumentTypeSpec` registry
  ([`registry.py`](registry.py) — 6-layer validated document-type
  spec loader + `specs_for_country` + `specs_for_encounter_type`
  filters + `AD-64` `encounter_types_supported` empty-tuple
  gotcha).
- **Out of scope**: LLM provider I/O
  ([`llm_service`](../../llm_service/README.md)); stub emission
  ([`document`](../README.md)); FHIR
  `Composition` / `DocumentReference` serialisation
  ([`output/fhir_r4/documents/`](../../output/fhir_r4/documents/README.md)).

## Public API

Package `__init__.py` re-exports four symbols; the rest are
imported from submodules by callers that need them:

```python
from clinosim.modules.document.narrative import (
    TemplateNarrativeGenerator,   # Stage 1 deterministic
    LLMNarrativeGenerator,        # template base + per-section LLM replacement
    NarrativeCache,               # layer-1 in-memory cache
    apply_replacement_strategy,   # section-level replacement dispatch
)
from clinosim.modules.document.narrative.passes import (
    NarrativePass,                # abstract
    TemplateNarrativePass,        # default (Stage 1)
    LLMNarrativePass,             # narrate --provider {bedrock|ollama|mock}
)
from clinosim.modules.document.narrative.registry import (
    DocumentTypeSpec,
    load_document_type_specs,     # () -> {DocumentType: DocumentTypeSpec}
    specs_for_country,            # (country) -> list[DocumentTypeSpec]
    specs_for_encounter_type,     # (encounter_type) -> list[DocumentTypeSpec]
)
from clinosim.modules.document.narrative.context import build_context     # (CIF, encounter, doc) -> NarrativeContext
from clinosim.modules.document.narrative.scenario_spine import build_spine  # (protocol, day) -> NarrativeSpine
from clinosim.modules.document.narrative.fact_extractor import materialize_facts
from clinosim.modules.document.narrative.section_extractor import extract_section_facts
from clinosim.modules.document.narrative.semantic_check import check_narratives
```

## Determinism

- **`TemplateNarrativeGenerator` is byte-deterministic** — the entire
  Stage 1 output is a pure function of the structural CIF + template
  seed. `TemplateNarrativePass` is the default and preserves
  byte-diff across runs.
- **`LLMNarrativeGenerator` is non-deterministic** on real backends.
  `semantic_check.check_narratives(cif_dir, version_id, …)` is the
  β-JP-1 verification gate that replaces byte-diff for the LLM path.
- **NarrativeCache seed_hash** (N-chain adv-1 C-1) — the cache key
  includes `sha256` of the template seed text so cross-patient reuse
  is structurally sound (a wrong-patient hit would change the seed
  hash and miss the cache).
- **Group walk order** (AD-65) — `NarrativePass` walks documents
  grouped by (doc_type, language) so a single prompt prefix is
  reused for a batch → the Bedrock prompt-cache 5-minute TTL hits
  maximally. `LLMNarrativePass` inherits the same walk order for
  drop-in cache friendliness.
- **fact-first constraint** (AD-65 E2) — β-JP-1 `LLMNarrativePass`
  refuses to emit numbers not present in `materialized_facts`, so
  the LLM cannot hallucinate lab values.

## Dependencies

- `clinosim.modules.llm_service` — `LLMService.complete_prompt` +
  `LLMTaskType` / `LLMResponse` (LLM path only).
- `clinosim.modules.document` — canonical ID prefixes +
  `NURSING_LOINCS` (imports back only for the constants, not the
  enricher itself).
- `clinosim.modules.disease.protocol` — `DiseaseProtocol` for
  scenario spine extraction.
- `clinosim.modules.encounter.protocol` —
  `EncounterConditionProtocol` for outpatient / ED templates.
- `clinosim.types.document` — `NarrativeContext`, `NarrativeOutput`,
  `DocumentType`, `FormatType`, plus `NarrativeGenerator` Protocol.
- `clinosim.types.clinical` — `ClinicalDocument`,
  `ClinicalDocumentNarrative`.
- `hashlib.sha256` — cache key derivation.
- `yaml`.

## Constants and configuration

- **`_narrative_interpretation_thresholds.py`** — every scalar the
  template generator uses when narrativising a lab or vital value
  (`"BP is slightly elevated"` vs `"markedly elevated"`) is lifted
  here with a clinical citation (Issue #637 sweep).
- **`_hedging.py`** — hedging-phrase pool with the "SCENARIO-derived
  (未確定) information" contract: the template MUST hedge on values
  it did not observe directly.
- **Document-type spec YAML** — lives in
  [`../reference_data/document_type_specs.yaml`](../reference_data/document_type_specs.yaml)
  (owned by the parent `document` package but loaded from here). The
  registry loader `_validate_document_type_specs` runs the standard
  6-layer defense.
- **`DocumentTypeSpec.stage2_strategy`** — `"template_only"` skips
  the LLM entirely; other values dispatch to
  `apply_replacement_strategy` per section.
- **`DocumentTypeSpec.llm_enabled_sections`** — allowlist of
  section keys the LLM path is permitted to replace; any section
  not in the list stays as template output.
- **`DocumentTypeSpec.encounter_types_supported`** — AD-64 α-min-2
  empty-tuple gotcha: an EMPTY tuple means "matches ALL encounter
  types", so inpatient-only specs MUST declare
  `[inpatient, icu, rehab_inpatient]` explicitly to prevent
  outpatient / ED leakage.

## Directory contents

```
clinosim/modules/document/narrative/
  __init__.py                              re-exports 4 symbols (2 generators + NarrativeCache + apply_replacement_strategy)
  passes.py                                NarrativePass ABC + TemplateNarrativePass + LLMNarrativePass
  registry.py                              DocumentTypeSpec + loader + filters (6-layer validated)
  context.py                               build_context (CIF → NarrativeContext)
  scenario_spine.py                        build_spine (protocol → NarrativeSpine, AD-65 E1)
  fact_extractor.py                        materialize_facts (FactTag list, AD-65 E2 β-JP-1 constraint)
  section_extractor.py                     extract_section_facts (per-COMPOSITION section, AD-65 E3)
  template_generator.py                    TemplateNarrativeGenerator + placeholder engine (~4300 LOC)
  llm_generator.py                         LLMNarrativeGenerator (template base + per-section LLM replacement)
  replacement_strategy.py                  apply_replacement_strategy dispatch (~1300 LOC)
  cache.py                                 NarrativeCache (layer-1 in-memory, seed_hash keyed)
  semantic_check.py                        check_narratives (β-JP-1 verification gate)
  _hedging.py                              hedging phrase pool
  _chronic_soap.py                         chronic-disease SOAP resolver (v9 density fix)
  _narrative_interpretation_thresholds.py  interpretation cutoff scalars (Issue #637)
```

The subpackage has **no `audit.py`, no `enricher.py`, no
`reference_data/`** — reference data lives in the parent `document`
package.

## Enricher wiring

Not applicable — the passes are invoked by the CLI (`narrate`
subcommand) after the encounter loop completes, not via
`register_builtin_enrichers`. The parent `document` package's
`document_enricher` produces the stubs the passes consume.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| CLI `narrate` subcommand | [`clinosim/simulator/cli_narrate.py`](../../../simulator/cli_narrate.py) | Instantiates `TemplateNarrativePass` (default) or `LLMNarrativePass` (per `--provider`) and calls `.run(cif_dir, version_id)`. |
| Document package | [`clinosim/modules/document/__init__.py`](../__init__.py) | Re-exports `DocumentTypeSpec` + spec loader / filters from `registry`. |
| FHIR document builders | [`clinosim/modules/output/fhir_r4/documents/`](../../output/fhir_r4/documents/README.md) | Read `ClinicalDocumentNarrative.sections` / `text` (populated by these passes) into `Composition.section[].text.div`. |
| Semantic-check CLI | (`clinosim narrate` when `--check` flag on) | Calls `check_narratives` to verify LLM output against fact constraints. |

## Testing

```bash
pytest tests/unit -k narrative -q
pytest tests/unit -k template_narrative -q
pytest tests/integration -k document_chain -q
```

Fixture golden narratives live under
`tests/fixtures/patient_profiles/*.llm-mock.golden.json` — the
mock provider replays them deterministically so `LLMNarrativePass`
tests stay I/O-free.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
