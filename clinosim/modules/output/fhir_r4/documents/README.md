# `fhir_r4/documents/` — Composition + DocumentReference FHIR R4 builders

## Purpose

Emits every FHIR R4 resource in the clinical-document family:
`Composition` (structured document — sections come from
`ClinicalDocument.narrative.sections` populated by the AD-65 Stage 2
narrative pass), `DocumentReference` (metadata pointer to
narrative text) for standard clinical documents, and the
specialised `DocumentReference` builder for JP-eCheckup 事業者健診
reports.

Composition dispatch is **format-type driven**: only
`ClinicalDocument` records with `format_type == "composition"` emit
Compositions; the rest emit `DocumentReference`. JP-CLINS
Composition variants (DISCHARGE_SUMMARY / REFERRAL_NOTE /
eCheckup) each have their own template-specialised builder in
`composition.py`.

## Scope

- **In scope**: `_bb_compositions` dispatch (walks `record.documents`
  where `format_type == "composition"`, skips stubs whose
  `narrative` is still `None` — the Stage 2 pass has not yet run —
  with a warning rather than emitting an empty Composition);
  `_build_composition` root builder + `_build_composition_generic`
  fallback; three JP-CLINS specialised builders
  (`_build_jp_clins_discharge_summary_composition`,
  `_build_jp_clins_referral_note_composition`,
  `_build_jp_eCheckup_general_composition`);
  `_localize_section_title` + `_section_title_from_section_display`
  (α-min-1 adv-1 Lens 3 I-3 TODO: JP section-title locale is
  deferred to β-JP-1, keys remain English snake_case for now);
  `_bb_document_references` + `_build_dref_from_clinical_doc` +
  `_build_prior_doc_chain` (`DocumentReference` builder with prior
  document chain); `_bb_document_references_checkup` +
  `_build_dref` (eCheckup-specialised `DocumentReference`);
  `_fhir_instant_or_empty` (safe ISO-instant conversion).
- **Out of scope**: `ClinicalDocument` stub emission
  ([`clinosim.modules.document`](../../../document/README.md)); narrative
  content generation
  ([`clinosim.modules.document.narrative`](../../../document/narrative/README.md));
  narrative version tracking (managed by the CIF writer);
  `ClinicalImpression` (emitted by
  [`../conditions/clinical_impression.py`](../conditions/clinical_impression.py)).

## Public API

Every builder is registered with the parent facade
(`_BUNDLE_BUILDERS` in [`../__init__.py`](../__init__.py)).

```python
from clinosim.modules.output.fhir_r4.documents.composition import (
    _bb_compositions,                            # bundle-builder (ctx: BundleContext)
    _build_composition,                          # root Composition builder (dispatches to specialised builders)
    _build_composition_generic,                  # generic-shape fallback
    _build_jp_clins_discharge_summary_composition,
    _build_jp_clins_referral_note_composition,
    _build_jp_eCheckup_general_composition,
    _localize_section_title,                     # (section_title, lang) -> localised title (JP deferred to β-JP-1)
    _section_title_from_section_display,
)
from clinosim.modules.output.fhir_r4.documents.documents import (
    _bb_document_references,                     # bundle-builder for standard DocumentReference
    _build_dref_from_clinical_doc,               # per-record DocumentReference
    _build_prior_doc_chain,                      # prior document chain resolver
)
from clinosim.modules.output.fhir_r4.documents.document_reference_checkup import (
    _bb_document_references_checkup,             # eCheckup-specialised bundle-builder
    _build_dref,                                 # eCheckup per-record DocumentReference
    _fhir_instant_or_empty,                      # safe ISO-instant conversion
)
```

## Determinism

Not applicable — every builder is pure over the input CIF record +
merged narrative. The Stage 2 narrative pass is deterministic for the
template path (byte-identical); for the LLM path the semantic-check
gate replaces byte-diff (see
[`document/narrative`](../../../document/narrative/README.md)).

## Dependencies

- `clinosim.modules._shared` — `is_jp`, `resolve_lang`.
- `clinosim.modules.output.fhir_r4.lib.common` — `_coding_with_display`,
  `loinc_coding`, `BundleContext`, `entry`,
  `attach_ecs_institutional_extensions`.
- `clinosim.modules.output.fhir_r4.conditions.primary_ref` —
  `primary_condition_ref` for Composition `Composition.subject` /
  `Composition.encounter` linkage cross-checks.
- `clinosim.codes` — LOINC lookup for document-type codes.
- `clinosim.types.clinical` — `ClinicalDocument`,
  `ClinicalDocumentNarrative`.

## Constants and configuration

- **Format-type dispatch** (`_bb_compositions`) — only
  `format_type == "composition"` records emit Compositions.
  `format_type == "free_text"` records emit `DocumentReference`
  via `_bb_document_references` instead.
- **JP-CLINS Composition variants** — dispatched inside
  `_build_composition` by document-type LOINC:
  - `18842-5` DISCHARGE_SUMMARY → JP-CLINS discharge-summary builder.
  - REFERRAL_NOTE → JP-CLINS referral-note builder.
  - eCheckup (JP 事業者健診) → JP-eCheckup general builder.
  - Other document types (ADMISSION_HP `34117-2`,
    ADMISSION_NURSING_ASSESSMENT `78390-2`,
    NURSING_DISCHARGE_SUMMARY `34745-0`,
    OUTPATIENT_SOAP `34131-3`, ED_NOTE `34878-9`) → generic builder.
- **Section-title language** — α-min-1 adv-1 Lens 3 I-3 TODO:
  section titles remain English snake_case keys; JP localisation is
  deferred to β-JP-1. `_localize_section_title` currently returns
  the input unchanged for JP.
- **Prior-doc chain** — `_build_prior_doc_chain` walks
  `raw_docs` to build the `DocumentReference.relatesTo` chain
  (progress-note ↔ discharge-summary linkage, ADMISSION_HP ↔
  DISCHARGE_SUMMARY linkage).
- **Stub skip contract** (AD-65): a `ClinicalDocument` whose
  `narrative is None` MUST be skipped with a warning — emitting an
  empty Composition violates the FHIR R4
  `Composition.section` `.text` cardinality and would silently
  ship an unreadable document.

## Directory contents

```
clinosim/modules/output/fhir_r4/documents/
  __init__.py                        empty (builders imported by parent __init__)
  composition.py                     _bb_compositions + generic + 3 JP-CLINS specialised builders (~1200 LOC)
  documents.py                       _bb_document_references + prior-doc chain
  document_reference_checkup.py      _bb_document_references_checkup (JP-eCheckup)
```

## Testing

```bash
pytest tests/unit -k "composition or document_reference or checkup" -q
pytest tests/integration -k "document_chain" -q
clinosim audit run -d <cohort_dir> --module document
```

The `document` AD-60 audit plug-in
([`../../../document/audit.py`](../../../document/audit.py)) —
49-check `lift_firing_proof` — is the load-bearing gate for this
family. It cross-verifies the canonical ID prefixes
(`DOC_REFERENCE_ID_PREFIX`, `COMPOSITION_ID_PREFIX`,
`CLINICAL_IMPRESSION_ID_PREFIX`, `ALLERGY_ID_PREFIX`,
`CARE_TEAM_ID_PREFIX`), the LOINC 54094-8 dispatch gate, and the
CIF → FHIR no-drop matrix (Section 3.4).

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
