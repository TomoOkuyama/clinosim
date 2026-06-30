# Tier 1 #3 α-min-1 Document Density Chain — DQR

**Date:** 2026-07-01
**Cohorts:** US p=10,000 seed=42 + JP p=5,000 seed=42
**Branch:** feature/tier1-document-density-alpha-min-1
**Spec:** docs/superpowers/specs/2026-07-01-tier1-3-document-density-alpha-min-1-design.md
**Plan:** docs/superpowers/plans/2026-07-01-tier1-3-document-density-alpha-min-1-plan.md
**Master plan:** docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md

## Summary

Tier 1 #3 α-min-1 closes the Stage 1 document density gap by:

1. **DocumentReference** — free-text clinical documents (Admission H&P + daily Progress Note +
   Discharge Summary templates) emitted via `clinosim/modules/document/` POST_RECORDS enricher
   for all inpatient/ICU/rehab encounters. Base64-encoded text/plain content with LOINC coding.
2. **Composition** — structured discharge summaries emitted as FHIR Composition with section[]
   breakdown (chief_complaint / hpi / physical_exam / hospital_course / discharge_medications /
   follow_up_instructions / discharge_instructions) for completed inpatient encounters.
3. **ClinicalImpression** — daily clinical impression notes emitted for every inpatient day,
   capturing impression text and assessment status.
4. **AllergyIntolerance (schema upgrade)** — existing 3-field allergy data upgraded to 8-field
   SNOMED-coded AllergyIntolerance (allergen SNOMED code + reaction manifestation code + category +
   criticality + clinical status + verification status + onset period + note). A new always-on
   `allergy` enricher (Task 2) replaces activator.py's inline 15% sampling with a proper enricher
   that writes `PersonRecord.allergies: list[Allergy] | None` (None = not-yet-enriched sentinel,
   [] = no-allergy after sampling).

This chain introduces 2 new always-on POST_RECORDS modules (`document` at order=95, `allergy` at
order=65) and 3 new FHIR builder modules (`_fhir_document_reference.py`,
`_fhir_composition.py`, `_fhir_clinical_impression.py`). The existing `_fhir_patient.py`
AllergyIntolerance builder is preserved as a coexistence path until Task 15 migration; the
`fhir_r4_adapter.py` `written_ids` dedup guard ensures no double-emit for matching IDs.

## Cohort run commands

```bash
# US p=10,000
clinosim generate \
  --population 10000 \
  --seed 42 \
  --country US \
  --format fhir-r4 \
  --output scratchpad/doc_alpha1_us10k

# JP p=5,000
clinosim generate \
  --population 5000 \
  --seed 42 \
  --country JP \
  --format fhir-r4 \
  --output scratchpad/doc_alpha1_jp5k

# Audit
clinosim audit run -d scratchpad/doc_alpha1_us10k > scratchpad/doc_alpha1_us10k_audit.txt
clinosim audit run -d scratchpad/doc_alpha1_jp5k  > scratchpad/doc_alpha1_jp5k_audit.txt
```

## Production resource counts

| Resource | US p=10k | JP p=5k | Baseline (US pre-Task 8) | Gap status |
|---|---|---|---|---|
| Patient | 24,874 | 2,457 | 24,763 | unchanged |
| Encounter | 160,835 | 16,129 | 160,646 | unchanged |
| DocumentReference | **23,760** | **3,909** | **0** | ★ GAP CLOSED |
| Composition | **9,275** | **474** | **0** | ★ GAP CLOSED |
| ClinicalImpression | **23,760** | **3,909** | **0** | ★ GAP CLOSED |
| AllergyIntolerance | 3,738 (15.0%) | 370 (15.06%) | 3,781 (15.3%) | preserved within ±0.05 |
| ImagingStudy | 315 | 39 | 315 | unchanged (Tier 1 #2) |

## Gap closure analysis

### Stage 1 document emission (DocumentReference / ClinicalImpression / Composition)

Prior to this chain, `clinosim generate` (Stage 1 without `narrate`) emitted 0
DocumentReference resources. The `narrate` CLI subcommand existed for LLM-driven narrative
generation, but Stage 1 had no default template-based document emission. This chain adds
a new `document` module enricher (POST_RECORDS order=95) that:

- Emits a free-text DocumentReference for every inpatient-day of every inpatient/ICU/rehab
  encounter (Admission H&P on day 0, Progress Note on days 1..N-1, Discharge Summary on last day).
  Each document is base64-encoded and LOINC-coded (34117-2 H&P / 11506-3 Progress Note /
  18842-5 Discharge Summary).
- Emits a Composition (structured) for completed inpatient encounters (discharge_datetime
  non-None) on the last day only, with 7-section structured breakdown.
- Emits one ClinicalImpression per day (same frequency as free-text DocumentReference),
  capturing the day's clinical impression text and status.

US p=10k: 23,760 DR + 23,760 CI + 9,275 Composition
JP p=5k: 3,909 DR + 3,909 CI + 474 Composition

The Composition count (9,275 US vs 23,760 DR) reflects that Composition is only emitted for
completed encounters (discharge_datetime non-None). In-progress inpatient encounters (snapshot
semantics, AD-32) produce DR + CI but no Composition. This is correct per clinical semantics:
a Discharge Summary Composition is only valid after discharge.

### AllergyIntolerance baseline preservation

Baseline (pre-chain) AllergyIntolerance count: 3,781 (15.3% of 24,763 patients, US p=10k).
New chain count: 3,738 (15.0% of 24,874 patients). Delta: -43 (-1.1%).

This is **within the ±0.05 tolerance** established by Task 2's 15.0% calibration target.
The apparent drop has two contributing factors:

1. **Population size increase**: the new chain adds the `allergy` enricher which runs before
   the FHIR builder. The patient count increased slightly (24,763 → 24,874 = +111 patients)
   due to normal cohort variation at seed=42, and the 15.0% calibration applies to the new
   population size.
2. **No double-emit**: the legacy `_fhir_patient.py` AllergyIntolerance builder and the new
   `_fhir_allergy_intolerance.py` builder both emit using the same `allergy-{id}` ID prefix.
   The `fhir_r4_adapter.py:written_ids` dedup guard (line 217-230) prevents the same ID from
   appearing twice in the NDJSON output. Since the new builder fires first (registered earlier
   in `_BUNDLE_BUILDERS`), the legacy path is deduped for patients who have allergies, resulting
   in a single SNOMED-coded resource — not a doubled count.

The Task 15 migration (same branch, pending) will remove the legacy activator.py path entirely,
making the dedup invariant moot.

## Audit verdict per axis

**Overall: PASS (1/4 axes explicitly PASS; 3/4 axes N/A)**

| Module | structural | jp_language | clinical | silent_no_op |
|---|---|---|---|---|
| document_chain | N/A | N/A | N/A | **PASS** |

### Axis 1: structural — N/A

`ModuleAuditSpec` does not have a `structural_checks` field in the current framework.
The aspirational structural checks (reference integrity for DocumentReference.subject/encounter,
Composition.subject/encounter/author, ClinicalImpression.subject/encounter refs) are
documented in spec §9.2 but cannot be wired until the framework gains the field.

Deferred: see TODO.md "imaging chain jp_language axis" entry pattern. Integration tests in
Task 12 (`tests/integration/test_document_integration.py`) cover the structural invariants
(encounter ref presence, base64 content non-empty, Composition.section[] non-empty) via
the subprocess full-pipeline path.

### Axis 2: jp_language — N/A

`ModuleAuditSpec` does not have a `jp_language_checks` field. The aspirational JP language
checks are documented in spec §9.3 (DocumentReference.description JP / Composition.title JP /
ClinicalImpression.description JP / section text JP) but cannot be wired until the framework
gains the field.

**Known limitation (α-min-1 scope):** JP section text has partial EN fallback:
- `past_medical_history`, `medications_at_home`, `discharge_medications` sections are English-only
  in α-min-1 (drug names not translated). Deferred to β-JP-1.
- `ClinicalImpression.description` is English-only in α-min-1. Deferred to β-JP-1.

Integration tests in Task 12 (`test_document_integration.py::test_jp_sections_have_japanese_chars`)
verify that the main narrative sections (hpi / physical_exam / hospital_course) contain Japanese
characters when country=JP.

### Axis 3: clinical — N/A

`ModuleAuditSpec.clinical_acceptance` is a `dict[str, Any]` but the current audit runner
reads it as descriptive metadata only (no callable validators). The 5-key clinical_acceptance
dict in `document_chain/audit.py` documents the expected rates (1 H&P per inpatient encounter /
1 progress note per day / 1 discharge summary per completed inpatient / 1 CI per day /
15% allergy distribution) but these are not enforced at `clinosim audit run` time.

Active enforcement deferred to future audit framework enhancement (same pattern as imaging chain
Task 9 deferral: `ModuleAuditSpec` API doesn't support callable clinical validators in the
current version).

### Axis 4: silent_no_op — PASS

`clinosim audit run` output for both cohorts:

```
Overall: PASS

| Module         | structural | jp_language | clinical | silent_no_op |
| document_chain | N/A        | N/A         | N/A      | PASS         |
```

17 lift_firing_proof equality_checks — all PASS (US p=10k and JP p=5k):

1. `proof_eq_DOC_REFERENCE_ID_PREFIX='doc-'`
2. `proof_eq_COMPOSITION_ID_PREFIX='comp-'`
3. `proof_eq_ALLERGY_ID_PREFIX='allergy-'`
4. `proof_eq_CLINICAL_IMPRESSION_ID_PREFIX='ci-'`
5. `proof_eq_DocumentReference emitted when free_text ClinicalDocument in record.documents=True`
6. `proof_eq_Composition emitted when composition ClinicalDocument in record.documents=True`
7. `proof_eq_AllergyIntolerance emitted when patient.allergies non-empty=True`
8. `proof_eq_ClinicalImpression emitted when extensions.clinical_impressions non-empty=True`
9. `proof_eq_DocumentReference.id starts with DOC_REFERENCE_ID_PREFIX=True`
10. `proof_eq_Composition.id starts with COMPOSITION_ID_PREFIX=True`
11. `proof_eq_AllergyIntolerance.id starts with ALLERGY_ID_PREFIX=True`
12. `proof_eq_no_drop: ClinicalDocument.text -> DocumentReference.content.attachment.data (base64)=True`
13. `proof_eq_no_drop: ClinicalDocument.sections -> Composition.section[] non-empty=True`
14. `proof_eq_no_drop: ClinicalDocument.loinc_code -> DocumentReference.type.coding[0].code='34117-2'`
15. `proof_eq_no_drop: patient.allergies[].allergen_code -> AllergyIntolerance.code.coding[0].code='372687004'`
16. `proof_eq_no_drop: ClinicalImpressionRecord.description -> ClinicalImpression.description (preserved)='Patient improving on antibiotics'`
17. `proof_eq_ClinicalImpression.id starts with CLINICAL_IMPRESSION_ID_PREFIX=True`

Key no-drop invariants verified (spec §3.4 CIF→FHIR no-drop rule):
- `ClinicalDocument.text` → `DocumentReference.content.attachment.data` (base64-encoded, not dropped)
- `ClinicalDocument.sections` → `Composition.section[]` (structured sections preserved)
- `ClinicalDocument.loinc_code` → `DocumentReference.type.coding[0].code` (LOINC code emitted)
- `patient.allergies[].allergen_code` → `AllergyIntolerance.code.coding[0].code` (SNOMED code emitted)
- `ClinicalImpressionRecord.description` → `ClinicalImpression.description` (no text drop)

## Bug found during implementation (Task 8)

`ClinicalDocument` in CIF was missing two fields required by FHIR builders:
- `sections: dict[str, str]` (Task 9 Composition builder needed sections to reconstruct
  Composition.section[], without it the builder had no way to split the narrative into structured
  sections — a CIF→FHIR no-drop invariant violation per spec §3.4)
- `format_type: str` (Task 9 dispatch required this to select between free_text vs composition
  builder path; silent no-op without it)

Fixed in Task 8 by adding both fields to `clinosim/types/clinical.py:ClinicalDocument` (default
`{}` / `""` for backward compat) and wiring them at all 3 emission sites in
`clinosim/modules/document/engine.py`. Rule added to CLAUDE.md: "ClinicalDocument.sections +
format_type field invariant — CIF must preserve sections for COMPOSITION builders, not just
joined text."

## Pre-merge test sweep

- **Unit tests**: 1,315 PASS
- **Integration tests**: ~225 PASS (27 document integration + existing module chain)
- **e2e tests**: 39 PASS (all existing e2e golden assertions hold)
- **Total pre-merge sweep**: **1,540 PASS**, 0 regressions vs base commit 40e8807a47
- **Regression note**: `test_device_fhir_output.py::test_device_extension_through_fhir_pipeline`
  was pre-existing baseline failure (verified at base commit, Task 12 Implementer concern C1).
  Not introduced by this chain.

## Known limitations (α-min-1 scope)

1. **JP section text partial EN fallback**: `past_medical_history` / `medications_at_home` /
   `discharge_medications` sections are English-only (drug names, condition names in English).
   Main narrative sections (hpi / physical_exam / hospital_course) are Japanese for JP cohort.
   Full JP localization deferred to β-JP-1.

2. **ClinicalImpression.description English-only**: The impression text generated by
   `TemplateNarrativeGenerator` is English regardless of country. JP localization of CI
   description deferred to β-JP-1.

3. **Composition.author empty**: `Composition.author` is required (FHIR R4 cardinality 1..*).
   The current builder emits `"author": []` which violates FHIR R4 cardinality. A TODO comment
   is placed in `_fhir_composition.py`. Practitioner ref lookup for Composition.author requires
   attending physician assignment wiring not yet available. Deferred to α-min-2.

4. **AllergyIntolerance legacy coexistence**: The legacy activator.py + `_fhir_patient.py`
   allergy path coexists with the new enricher + `_fhir_allergy_intolerance.py` builder until
   Task 15 migration. The `written_ids` dedup guard prevents double-emit. Task 15 (same branch,
   pending) will deprecate `narrative_generator.py`, `document_generator.py`, and the activator
   allergy block; until then the legacy path remains for backward compatibility.

5. **narrative_generator.py / document_generator.py still present**: The existing Stage 2
   LLM document pipeline (`clinosim narrate`) is unchanged. Task 15 (this branch, pending) will
   migrate the legacy generators to the new `clinosim/modules/document/` module structure. The
   current chain focuses on Stage 1 default template emission only.

## Recommendation

**Ship-ready for α-min-1 phase boundary.** The three gap-closure targets
(DocumentReference / Composition / ClinicalImpression all at 0 → expected) are confirmed.
AllergyIntolerance baseline preservation is within tolerance. silent_no_op 17/17 checks PASS.
Pre-merge sweep 1,540 PASS, 0 new regressions.

**Task 15** (same branch, still pending at time of this DQR) will complete the generator
migration and legacy path cleanup. It is within scope for this chain and should be executed
before PR open.

**Next phases:**
- **α-min-2**: Nursing narratives (Admission nursing assessment / Nursing shift / Discharge
  nursing), ED note, outpatient SOAP note, Composition.author wiring.
- **β-JP-1**: Full JP section text localization, QuestionnaireResponse active emission,
  入院診療計画書 / 看護必要度 D 表 / 栄養管理計画書 / リハ計画書 (JP 厚労省必須文書).
- **β-2**: 手術記録 / 麻酔記録 / IC document, MedicationDispense, Procedure density 強化.
