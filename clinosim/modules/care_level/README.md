# `clinosim.modules.care_level` — care-level / activity-of-daily-living scoring

## Purpose

Assigns care-level ratings (independent / assisted / dependent) and
ADL scoring to patients based on age, chronic conditions, and current
functional state. Emits `CareLevelRecord` dataclasses attached to
inpatient / rehab encounters.

The JP variant maps to **要介護度** (Long-Term Care Insurance /
介護保険 levels 要支援 1-2 / 要介護 1-5) when applicable.

## Scope

- **In scope**: per-patient care-level assignment, ADL scoring
  scaffolding (feeds into the nursing module's Barthel index),
  JP 要介護度 mapping when country is JP and patient age ≥ 65.
- **Out of scope**: nursing assessments themselves (in
  [`clinosim.modules.nursing`](../nursing/README.md)), FHIR
  serialisation (in [`clinosim.modules.output`](../output/README.md)).

## Public API

```python
from clinosim.modules.care_level import (
    assign_care_level,           # (patient, encounter, rng) -> CareLevelRecord
)
```

## Dependencies

- `clinosim.types.encounter` — care-level fields on the encounter
  record, Barthel-related types.
- `clinosim.types.patient` — `PatientProfile.age`, chronic conditions.

## Constants and configuration

- Care-level assignment thresholds live inline in `engine.py` and are
  flagged for extraction in
  [`docs/reviews/2026-08-09-constants-audit.md`](../../../docs/reviews/2026-08-09-constants-audit.md).
- JP 要介護度 mapping table lives in `reference_data/*.yaml`.

## Directory contents

```
clinosim/modules/care_level/
  __init__.py           public API
  engine.py             care-level assignment logic
  audit.py              per-module audit spec
  reference_data/       care-level and ADL reference tables
```

## Testing

```bash
pytest tests/unit -k care_level -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
