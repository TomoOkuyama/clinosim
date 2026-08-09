# `fhir_r4/conditions/` — condition / allergy / immunization FHIR R4 builders

## Purpose

Emits FHIR R4 resources for clinical conditions, allergies, and
immunizations: `Condition`, `AllergyIntolerance`, `Immunization`, and
the associated coding (ICD-10-CM for US, ICD-10-JP for JP, RxNorm /
SNOMED for allergens, CVX for vaccines).

## Scope

- **In scope**: `Condition` (primary + secondary diagnoses, chronic
  conditions), `AllergyIntolerance`, `Immunization`.
- **Out of scope**: diagnosis / allergy / immunization *generation*
  (in [`clinosim.modules.diagnosis/`](../../../diagnosis/README.md),
  [`clinosim.modules.allergy/`](../../../allergy/README.md),
  [`clinosim.modules.immunization/`](../../../immunization/README.md)),
  the code registries themselves (`clinosim/codes/`).

## Public API

Builders are dispatched through the parent facade
(`register_bundle_builder`), not called directly from outside.

## Dependencies

- `clinosim.types.diagnosis` — `DiagnosisRecord`.
- `clinosim.types.allergy` — `Allergy`, `AllergyReaction`.
- `clinosim.types.encounter` — `ImmunizationRecord`.
- `clinosim.codes.data.{icd10cm,icd10-jp,snomed,cvx}` — coding
  lookups.
- Sibling `lib/` — shared helpers.

## Constants and configuration

- ICD-10 dispatch rule: US emits ICD-10-CM (billable), JP emits
  WHO ICD-10 (3-4-character, JP-Core convention). Detail in
  [`clinosim.locale/`](../../../../locale/README.md)
  `code_mapping_diagnosis.yaml`.
- Allergen coding: RxNorm (US drug allergies), SNOMED (food and
  environmental).
- Vaccine coding: CVX (cross-country).

## Directory contents

```
clinosim/modules/output/fhir_r4/conditions/
  __init__.py               subpackage facade
  condition.py              Condition builder
  allergy.py                AllergyIntolerance builder
  immunization.py           Immunization builder
```

## Testing

```bash
pytest tests/unit -k conditions -q
pytest tests/integration -k condition -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
