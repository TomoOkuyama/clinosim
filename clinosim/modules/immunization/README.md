# `clinosim.modules.immunization` — immunization record generation

## Purpose

Generates the immunization history for each patient (routine childhood
immunisations, adult boosters, seasonal flu / COVID vaccines) and
emits `ImmunizationRecord` dataclasses that the FHIR `Immunization`
builder consumes.

## Scope

- **In scope**: per-patient immunization sampling based on
  age-appropriate schedules (CDC ACIP for US, 厚生労働省 定期予防接種
  for JP), lot-number generation, dose-in-series tracking, refusal
  reason handling.
- **Out of scope**: reaction / adverse-event generation, immunization-
  driven encounter creation (immunization visits are not currently
  first-class encounters), FHIR serialisation (in
  [`clinosim.modules.output`](../output/README.md)).

## Public API

```python
from clinosim.modules.immunization import (
    assign_immunizations,        # (patient, country, rng) -> list[ImmunizationRecord]
)
```

## Dependencies

- `clinosim.types.encounter` — `ImmunizationRecord` fields
  (`vaccine_cvx`, `dose_number`, `lot_number`).
- `clinosim.types.patient` — `PatientProfile.immunizations`.
- `clinosim.codes` (via FHIR builder) — CVX vaccine-code display
  lookup.

## Constants and configuration

- Immunization-schedule reference data lives in
  `reference_data/*.yaml`, split by country.
- Vaccine codes use CVX (`http://hl7.org/fhir/sid/cvx`) for
  cross-country interoperability.
- Schedule sources:
  - US: CDC ACIP recommended schedule.
  - JP: 厚生労働省 定期予防接種 schedule.

## Directory contents

```
clinosim/modules/immunization/
  __init__.py           public API
  engine.py             immunization assignment logic
  audit.py              per-module audit spec
  reference_data/       per-country immunization schedules
```

## Testing

```bash
pytest tests/unit -k immunization -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
