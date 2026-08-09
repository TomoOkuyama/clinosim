# `clinosim.modules.sdoh` — social determinants of health

## Purpose

Assigns social-determinant-of-health attributes to each patient:
employment status, health literacy, housing stability, primary
language, and (US) insurance-type distributions. These fields feed
into narrative generation and downstream FHIR
`Observation` / `Condition` category codes for social-history.

## Scope

- **In scope**: per-patient assignment of SDOH attributes with
  country-appropriate distributions, wiring into
  `PatientProfile.employment_status` / `.health_literacy` /
  language / housing fields.
- **Out of scope**: SDOH-driven care-plan modifications (would
  belong in [`clinosim/modules/clinical_course/`](../clinical_course/README.md)),
  FHIR `Observation.category="social-history"` serialisation (in
  [`clinosim/modules/output/`](../output/README.md)).

## Public API

```python
from clinosim.modules.sdoh import (
    assign_sdoh,                 # (patient, country, rng) -> None (mutates)
    enrich_sdoh,                 # optional post_records enricher
)
```

## Dependencies

- `clinosim.types.patient` — `PatientProfile.employment_status`,
  `.health_literacy`.
- `clinosim.locale` — country language / housing pools.

## Constants and configuration

- SDOH attribute distributions per country live in
  `reference_data/*.yaml`. Country dispatches on
  `SimulatorConfig.country`.

## Directory contents

```
clinosim/modules/sdoh/
  __init__.py           public API
  engine.py             SDOH attribute assignment
  audit.py              per-module audit spec
  reference_data/       per-country SDOH distributions
```

## Testing

```bash
pytest tests/unit -k sdoh -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
