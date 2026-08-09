# `clinosim.modules.code_status` — advance-directive / code-status assignment

## Purpose

Assigns advance-directive / code-status metadata (Full Code / DNR /
DNI / Comfort Care) to patients based on age, chronic conditions, and
country-appropriate defaults. Emits `CodeStatusRecord` dataclasses
attached to inpatient encounters.

## Scope

- **In scope**: per-encounter code-status assignment, code-status
  change events during a stay (e.g. patient family switches to DNR
  after prolonged critical illness), country-appropriate defaults
  and prevalence rates.
- **Out of scope**: DNR-driven treatment-plan modifications (would
  belong in [`clinosim.modules.clinical_course`](../clinical_course/README.md)),
  FHIR `Consent` serialisation (in
  [`clinosim.modules.output`](../output/README.md)).

## Public API

```python
from clinosim.modules.code_status import (
    assign_code_status,          # (patient, encounter, rng) -> CodeStatusRecord
)
```

## Dependencies

- `clinosim.types.patient` — `PatientProfile.age`.
- `clinosim.types.encounter` — code-status related fields.

## Constants and configuration

- Age-band prevalence of DNR / DNI / Comfort Care lives inline and is
  flagged for extraction in
  [`docs/reviews/2026-08-09-constants-audit.md`](../../../docs/reviews/2026-08-09-constants-audit.md).
- Country-specific defaults dispatch on `SimulatorConfig.country`
  (US default = Full Code with age-band DNR prevalence; JP defaults
  differ per 病院方針 patterns).

## Directory contents

```
clinosim/modules/code_status/
  __init__.py           public API
  engine.py             code-status assignment logic
  audit.py              per-module audit spec
  reference_data/       age-band prevalence tables
```

## Testing

```bash
pytest tests/unit -k code_status -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
