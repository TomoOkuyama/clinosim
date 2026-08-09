# `fhir_r4/medications/` — medication FHIR R4 builders

## Purpose

Emits FHIR R4 resources for medications: `MedicationRequest`
(prescription), `MedicationAdministration` (MAR — Medication
Administration Record). Handles JP-CLINS profile compliance for JP,
including the `MedicationRequest.status='completed'` invariant.

## Scope

- **In scope**: `MedicationRequest` (RxNorm for US, YJ / HOT codes
  for JP, JP-CLINS profile compliance), `MedicationAdministration`
  (per-dose MAR emission).
- **Out of scope**: prescription / MAR *generation* (in
  [`clinosim.modules.order/`](../../../order/README.md),
  [`clinosim.simulator/`](../../../../simulator/README.md), and
  [`clinosim.modules.antibiotic/`](../../../antibiotic/README.md)),
  the drug code registries (`clinosim/codes/data/{rxnorm,yj,hot}`).

## Public API

Builders are dispatched through the parent facade
(`register_bundle_builder`), not called directly from outside.

## JP-CLINS profile invariants

- `MedicationRequest.status = "completed"` is required for the
  JP-CLINS `MedicationRequest` profile; the builder pins this value
  when country is JP. Intent information (planned vs. active vs.
  discontinued) is carried by note / statusReason / Extension slots
  instead.
- Per policy §4, spec quotations from jpfhir.jp may be retained
  inline in Japanese with an English gloss.

## Dependencies

- `clinosim.types.encounter` — `Order` (medications), `MedicationAdministration`.
- `clinosim.codes.data.{rxnorm,yj,hot}` — drug-code lookups.
- `clinosim.locale.{us,jp}.code_mapping_drug.yaml` — internal drug
  key → national drug code resolution.
- Sibling `lib/` — shared helpers.

## Constants and configuration

- Drug-code system precedence:
  - US: RxNorm.
  - JP: YJ code (individual products) + HOT code (packaging unit) as
    per JP-CLINS specification.
- ID prefixes: `MEDICATION_REQUEST_ID_PREFIX`,
  `MEDICATION_ADMINISTRATION_ID_PREFIX`, `ABX_REGIMEN_ID_PREFIX`
  (kept short to stay under FHIR R4's 64-char id limit).

## Directory contents

```
clinosim/modules/output/fhir_r4/medications/
  __init__.py               subpackage facade
  medications.py            MedicationRequest + MedicationAdministration builder
```

## Testing

```bash
pytest tests/unit -k medications -q
pytest tests/integration -k medication -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
