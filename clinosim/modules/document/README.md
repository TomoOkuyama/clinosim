# `clinosim.modules.document` — clinical-document stubs + ClinicalImpression

## Purpose

Tier 1 #3 α-min-1 always-on AD-55 module. POST_ENCOUNTER enricher
(`document_enricher`) that emits **stub `ClinicalDocument` records**
(admission H&P / progress notes / discharge summary /
operative note / procedure note / referral note / nurse notes /
ED_NOTE / ED_TRIAGE_NOTE / HEALTH_CHECKUP_REPORT, etc.) plus
`ClinicalImpression` daily records for inpatient / ICU / rehab
encounters. Each stub has `narrative=None`; the two-pass
[`narrative`](narrative/README.md) subpackage fills the narrative
content during the Stage 2 pass (AD-65). Also owns the canonical
FHIR resource ID prefixes every consumer imports.

## Scope

- **In scope**: `document_enricher` (POST_ENCOUNTER order=95, always-on);
  `DocumentTypeSpec` + spec loaders / filters (from
  [`narrative/registry`](narrative/registry.py)); document-type +
  format-type re-exports from `clinosim.types.document`; canonical
  ID prefix constants (`DOC_REFERENCE_ID_PREFIX = "doc-"`,
  `COMPOSITION_ID_PREFIX = "comp-"`, `ALLERGY_ID_PREFIX =
  "allergy-"`, `CLINICAL_IMPRESSION_ID_PREFIX = "ci-"`);
  `NURSING_LOINCS` frozenset (AD-65 Bug B — nursing-authored
  documents dispatch author to `encounter.primary_nurse_id`
  instead of `attending_physician_id`); reference-data loaders
  ([`reference_data_loaders.py`](reference_data_loaders.py) —
  `load_physical_exam_findings`, `load_discharge_instructions`
  with 6-layer validators); per-encounter document-type dispatch
  (`_pick_document_author`, `_referral_note_fires`,
  `_enc_type_value`, `_enc_status_value`, `_compute_los_days`,
  `_make_doc_stub`).
- **In scope (audit)**: [`audit.py`](audit.py) — fifth per-module
  AD-60 plug-in (after hai / antibiotic / order / imaging).
  49-check `lift_firing_proof` guards canonical constants
  (`DOC_REFERENCE_ID_PREFIX` / `COMPOSITION_ID_PREFIX` /
  `ALLERGY_ID_PREFIX` / `CLINICAL_IMPRESSION_ID_PREFIX` /
  `CARE_TEAM_ID_PREFIX`), emission counts, ID-prefix invariants,
  CIF → FHIR no-drop matrix (Section 3.4), the LOINC 54094-8
  dispatch gate, the AD-65 Bug A `us_admission_hp_zero_ja_chars`
  invariant, and the α-min-3 3-shift extensions.
  `clinical_acceptance` covers per-encounter doc count +
  ClinicalImpression daily emission + AllergyIntolerance
  distribution + CareTeam/triage/nursing/outpatient/ED
  per-encounter targets (13 keys total).
- **Out of scope**: narrative content assembly / template rendering
  ([`narrative`](narrative/README.md) subpackage owns the Stage 2
  passes and the LLM/template dispatch); LLM gateway
  ([`llm_service`](../llm_service/README.md)); FHIR
  `DocumentReference` / `Composition` / `ClinicalImpression` /
  `CareTeam` emission
  ([`output/fhir_r4/documents/`](../output/fhir_r4/documents/README.md)).

## Public API

```python
from clinosim.modules.document import (
    # Types (re-exported from clinosim.types.document)
    DocumentType,
    FormatType,
    NarrativeContext,
    NarrativeOutput,

    # Registry
    DocumentTypeSpec,
    load_document_type_specs,       # () -> list[DocumentTypeSpec]
    specs_for_country,              # (country) -> list[DocumentTypeSpec]
    specs_for_encounter_type,       # (encounter_type) -> list[DocumentTypeSpec]

    # Reference-data loaders
    load_physical_exam_findings,    # () -> dict (@lru_cache, 6-layer validated)
    load_discharge_instructions,    # () -> dict (@lru_cache, 6-layer validated)
    load_hpi_pertinent_negatives,   # () -> dict (@lru_cache)

    # Canonical ID prefixes
    DOC_REFERENCE_ID_PREFIX,        # "doc-"
    COMPOSITION_ID_PREFIX,          # "comp-"
    ALLERGY_ID_PREFIX,              # "allergy-"
    CLINICAL_IMPRESSION_ID_PREFIX,  # "ci-"

    # Author dispatch
    NURSING_LOINCS,                 # frozenset (AD-65 Bug B)
)
from clinosim.modules.document.engine import document_enricher
```

## Determinism

- Sub-seed offset `0x444F` (`"DO"`, Tier 1 #3 α-min-1 PR1) —
  registered in [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["document"]`.
- Per-encounter sub-RNG:
  `derive_sub_seed(master_seed, offset, encounter_id)` — main
  patient RNG untouched (AD-16).
- Two-pass contract (AD-65): `document_enricher` produces stubs
  with `narrative=None`; populating narrative during the same
  simulation pass would silently no-op the Stage 2 differ. The
  contract is guarded by `test_narrative_populates_only_stage2`.

## Dependencies

- `clinosim.modules._shared` — `get_attr_or_key`,
  `set_attr_or_key`, `is_jp`.
- `clinosim.modules.document.narrative.registry` — spec loaders +
  filters.
- `clinosim.modules.document.reference_data_loaders` — physical
  exam findings + discharge instructions.
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.audit.registry` (via `audit.py`) — AD-60 audit
  registration.
- `clinosim.types.document` — `DocumentType`, `FormatType`,
  `NarrativeContext`, `NarrativeOutput`.
- `clinosim.types.clinical` — `ClinicalDocument`,
  `ClinicalDocumentNarrative`.
- `clinosim.types.encounter` — encounter types + primary_nurse_id
  / attending_physician_id fields.
- `yaml`, `numpy`.

## Constants and configuration

- **Canonical ID prefixes** (writer-owned; every FHIR builder
  imports these): `DOC_REFERENCE_ID_PREFIX`,
  `COMPOSITION_ID_PREFIX`, `ALLERGY_ID_PREFIX`,
  `CLINICAL_IMPRESSION_ID_PREFIX`. `_fhir_patient.py` still writes
  `allergy-{patient_id}-{index:02d}` inline; the constant here
  canonicalises the prefix for Task 9 FHIR builders (concern
  logged; unification tracked).
- **`NURSING_LOINCS`** (frozenset, loaded via `_load_nursing_loincs`
  from `engine.py`) — LOINC codes for nursing-authored documents.
  `_pick_document_author` dispatches to
  `encounter.primary_nurse_id` when the document's LOINC is in the
  set, else to `attending_physician_id` (AD-65 Bug B fix).
- **Document-type specs**
  ([`reference_data/document_type_specs.yaml`](reference_data/document_type_specs.yaml))
  — per-document-type registry entries. Each carries LOINC,
  `format_type` (`"free_text"` / `"composition"`),
  `encounter_types_supported` allowlist (AD-64 α-min-2 — an EMPTY
  tuple means "matches ALL encounter types", so specs for
  inpatient-only documents MUST declare
  `[inpatient, icu, rehab_inpatient]` explicitly to avoid leaking
  into outpatient / ED encounters), country gate, author-role
  hint.
- **6-layer reference-data validators** (Task 5 pattern) —
  `_validate_physical_exam_findings` and
  `_validate_discharge_instructions` run empty-top / missing-key /
  per-bucket / required-key / pre-use ordering / per-entry
  required-field checks; a YAML typo raises at import.
- **Chronic SOAP + hedging** reference YAMLs
  (`chronic_soap_templates.yaml`, `hedging_phrases.yaml`) are read
  from within [`narrative`](narrative/README.md) submodules but
  live in this package's `reference_data/`.

## Directory contents

```
clinosim/modules/document/
  __init__.py                        public API + canonical ID prefixes
  engine.py                          document_enricher + doc-stub helpers + NURSING_LOINCS
  reference_data_loaders.py          load_physical_exam_findings + load_discharge_instructions (6-layer)
  audit.py                           AD-60 audit plug-in #5 — 49-check lift_firing_proof
  reference_data/
    document_type_specs.yaml         per-document-type registry
    physical_exam_findings.yaml      per-disease PE findings (baseline + override)
    discharge_instructions.yaml      per-disease discharge instructions
    chronic_soap_templates.yaml      chronic-condition SOAP note templates
    hedging_phrases.yaml             narrative hedging phrase pool
  narrative/                         narrative subpackage (Stage 2 pipeline) — see narrative/README.md
```

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`~L340-348`):

- `name="document"`, `stage=POST_ENCOUNTER`, `order=95`,
  `enabled=lambda c: True`. Runs LAST in POST_ENCOUNTER (after
  imaging=90, triage=93, nursing_assignment=94) so it can consume
  every upstream extension slot.
- `audit.py` registers with the AD-60 audit framework at import
  time.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py:344`](../../simulator/enrichers.py) | POST_ENCOUNTER order=95 registration. |
| Audit registry | [`clinosim/modules/document/audit.py`](audit.py) | AD-60 audit plug-in — 49-check lift_firing_proof + clinical_acceptance. |
| Narrative Stage 2 | [`clinosim/modules/document/narrative/passes.py`](narrative/passes.py) | Fills `narrative.sections` on every stub emitted here. |
| FHIR document builders | [`clinosim/modules/output/fhir_r4/documents/`](../output/fhir_r4/documents/README.md) | Emit `DocumentReference` / `Composition` / `ClinicalImpression` from the stubs + populated narratives. |

## Testing

```bash
pytest tests/unit -k "document" -q
pytest tests/integration -k "document_chain" -q
clinosim audit run -d <cohort_dir> --module document
```

Coverage: extensive — search `tests/unit -k document` for the
per-spec / per-encounter / per-country tests, and see
`tests/integration/test_document_chain.py` for the end-to-end
CIF → FHIR chain guard.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
