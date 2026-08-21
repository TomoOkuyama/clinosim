# `fhir_r4/conditions/` — Condition / AllergyIntolerance / ClinicalImpression / HAI / CodeStatus builders

## Purpose

Emits every FHIR R4 resource in the "condition + clinical impression"
family: `Condition` (primary + secondary + chronic + HAI),
`AllergyIntolerance`, `ClinicalImpression`, and the CodeStatus
survey `Observation` (custom SNOMED resuscitation-status). Also
owns the **canonical primary-Condition reference resolver**
(`primary_ref.primary_condition_ref`) that every downstream builder
(Encounter.reasonReference / diagnosis[].condition, Procedure /
MedicationRequest reasonReference) MUST use so the encounter's
primary reason points at the SAME `Condition.id` everywhere.

## Scope

- **In scope**: `_bb_conditions` (primary + secondary + chronic
  Condition builder); `_bb_allergy_intolerances`;
  `_bb_clinical_impressions`; `_bb_hai_conditions` (HAI-derived
  Condition from `extensions["hai"]`); `_bb_code_status` (custom
  survey `Observation`, JP encounters carry
  `meta.profile = JP_Observation_Common`); `primary_condition_ref`
  + `primary_condition_ref_from_codes` + `is_chronic_primary` +
  `_chronic_index_for_primary` + `_icd_base` (canonical
  primary-Condition resolver); `_ecs_diagnosis_type_extension`,
  `_bodysite_for`, `_jfagy_coding_for_category` (JP-specific
  fragment builders).
- **Out of scope**: `Immunization` (that lives in
  [`../procedures/immunization.py`](../procedures/immunization.py),
  not here — immunization is a Procedure family FHIR resource
  despite its clinical proximity to conditions);
  condition / allergy / impression **generation** (in
  [`clinosim.modules.diagnosis`](../../../diagnosis/README.md),
  [`clinosim.modules.allergy`](../../../allergy/README.md),
  [`clinosim.modules.document`](../../../document/README.md) for
  `ClinicalImpression`,
  [`clinosim.modules.hai`](../../../hai/README.md) for HAI events,
  [`clinosim.modules.code_status`](../../../code_status/README.md));
  code registries themselves ([`clinosim/codes/`](../../../../codes/)).

## Public API

Every builder is registered with the parent facade
(`_BUNDLE_BUILDERS` in
[`../__init__.py`](../__init__.py)); outside callers rarely import
them directly. Named builder functions:

```python
from clinosim.modules.output.fhir_r4.conditions.conditions import _bb_conditions
from clinosim.modules.output.fhir_r4.conditions.allergy_intolerance import _bb_allergy_intolerances
from clinosim.modules.output.fhir_r4.conditions.clinical_impression import _bb_clinical_impressions
from clinosim.modules.output.fhir_r4.conditions.hai import _bb_hai_conditions
from clinosim.modules.output.fhir_r4.conditions.code_status import _bb_code_status

# Canonical primary-Condition resolver (imported by other resource families)
from clinosim.modules.output.fhir_r4.conditions.primary_ref import (
    primary_condition_ref,             # (record, patient_id, encounter_id) -> Condition.id
    primary_condition_ref_from_codes,  # (record, patient_id, encounter_id, primary_code, admission_code)
    is_chronic_primary,                # (record) -> bool  (encounter primary is a chronic problem)
)
```

## Determinism

Not applicable — every builder is a pure function of the input CIF
record. No RNG, no time-of-run dependence; the parent facade sorts
the emitted NDJSON by resource id so line order is deterministic.

## Dependencies

- `clinosim.modules._shared` — `get_attr_or_key`, `is_jp`,
  `resolve_lang`.
- `clinosim.modules.output.fhir_r4.lib.common` — fragment helpers
  (`_coding_with_display`, `build_diagnosis_codeable_concept`,
  `infer_severity`, `map_diagnosis_code`, `severity_coding`,
  `to_fhir_date`, `survey_category`, `BundleContext`).
- `clinosim.modules.output.fhir_r4.lib.localization` — JP display
  localisation helpers.
- `clinosim.codes` — `get_system_uri`, `system_key_for`, `lookup`
  for ICD-10 / ICD-10-CM / SNOMED / RxNorm / JP-Core `jp-core-*`
  code display.
- `clinosim.types.diagnosis` — `DiagnosisRecord`.
- `clinosim.types.allergy` — `Allergy`, `AllergyReaction`.
- `clinosim.types.clinical` — `ClinicalImpressionRecord`.
- `clinosim.types.encounter` — `HAIEvent`.
- No dependency on the parent `__init__.py` (no cycle back through
  the adapter facade).

## Constants and configuration

- **Canonical primary-Condition resolver** (`primary_ref.py`) —
  single-source-of-truth rule:
  - Given an encounter's `clinical_diagnosis.discharge_diagnosis_code`
    (or admission-code fallback), compare its 3-char ICD base
    against the patient's `chronic_conditions[].code` bases.
  - **Match** → return the patient-scoped chronic Condition id
    (`cond-chronic-{patient_id}-{index:02d}`). Emitting a parallel
    `cond-{enc}-primary` would duplicate the row and drift ICD
    granularity (e.g. I50 vs I50.9).
  - **No match** → return the encounter-scoped id
    (`cond-{enc}-primary`).
  - Every downstream builder that references the encounter's
    primary reason MUST call `primary_condition_ref` so the
    reference always points at the SAME emitted `Condition.id`.
- **ICD-10 dispatch**: US emits ICD-10-CM billable codes; JP emits
  WHO ICD-10 4-char (JP-Core convention). The mapping lives in
  [`clinosim/locale/jp/code_mapping_diagnosis.yaml`](../../../../locale/jp/code_mapping_diagnosis.yaml).
- **Allergen coding**: SNOMED CT (allergens + reaction manifestations).
  RxNorm remains the US drug-allergy code system (via
  `_jfagy_coding_for_category` when the allergen is drug-typed).
- **HAI coding**: ICD-10-CM (US billable) + WHO ICD-10 (JP) +
  SNOMED CT International — dual-coded per the AGENTS.md
  `dual-slot` convention.
- **JP eCS diagnosis-type extension**: `_ecs_diagnosis_type_extension`
  emits the JP-CLINS `JP_Condition_eCS` diagnosis-type extension
  for chronic Conditions.
- **CodeStatus profile**: JP encounters gain
  `meta.profile = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common"`
  on the custom survey Observation.

## Directory contents

```
clinosim/modules/output/fhir_r4/conditions/
  __init__.py                    empty (builders imported by parent __init__)
  conditions.py                  _bb_conditions (primary + secondary + chronic)
  allergy_intolerance.py         _bb_allergy_intolerances + JP fagy category coding
  clinical_impression.py         _bb_clinical_impressions
  hai.py                         _bb_hai_conditions (from extensions["hai"])
  code_status.py                 _bb_code_status (custom survey Observation)
  primary_ref.py                 primary_condition_ref + is_chronic_primary + _icd_base (canonical resolver)
```

## Testing

```bash
pytest tests/unit -k "condition or allergy_intolerance or clinical_impression or hai_condition or code_status" -q
pytest tests/integration -k "document_chain or hai" -q
```

The audit runs (`clinosim audit run --module hai` /
`--module document`) exercise this family transitively — HAI
Condition emission is guarded by the `hai` AD-60 plug-in, and
ClinicalImpression + primary-Condition-ref invariants are guarded
by the `document` AD-60 plug-in (49-check lift_firing_proof).

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
