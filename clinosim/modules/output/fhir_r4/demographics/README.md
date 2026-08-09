# `fhir_r4/demographics/` — demographics FHIR R4 builders

## Purpose

Emits FHIR R4 resources for patient demographics, practitioner
demographics, family history, and social-history observations
(smoking / alcohol).

## Scope

- **In scope**: `Patient`, `Practitioner`, `FamilyMemberHistory`,
  and social-history `Observation` (smoking status, alcohol intake).
- **Out of scope**: patient / practitioner *generation* (in
  [`clinosim.modules.population/`](../../../population/README.md),
  [`clinosim.modules.identity/`](../../../identity/README.md),
  [`clinosim.modules.staff/`](../../../staff/README.md)), family-
  history *generation* (in
  [`clinosim.modules.family_history/`](../../../family_history/README.md)),
  SDOH *generation* (in [`clinosim.modules.sdoh/`](../../../sdoh/README.md)).

## Public API

Builders are dispatched through the parent facade
(`register_bundle_builder`), not called directly from outside.

## Dependencies

- `clinosim.types.patient` — `PatientProfile`, `Address`, `ContactInfo`.
- `clinosim.types.staff` — `Practitioner`.
- `clinosim.types.family_history` — `FamilyMemberHistoryRecord`.
- `clinosim.codes.data.{snomed,loinc}` — social-history observation
  coding.
- Sibling `lib/` — shared helpers.

## Constants and configuration

- Patient MRN / insurance identifier system URIs come from
  [`clinosim.modules.identity/`](../../../identity/README.md)
  providers.
- Practitioner qualification / role coding — see
  `demographics/practitioner.py`.
- JP-Core `Patient` profile URI stamped on every JP patient.

## Directory contents

```
clinosim/modules/output/fhir_r4/demographics/
  __init__.py               subpackage facade
  patient.py                Patient builder
  practitioner.py           Practitioner builder
  family_history.py         FamilyMemberHistory builder
  smoking_alcohol.py        social-history Observation builder
```

## Testing

```bash
pytest tests/unit -k demographics -q
pytest tests/integration -k demographic -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
