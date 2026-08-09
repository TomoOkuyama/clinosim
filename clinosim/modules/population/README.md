# `clinosim.modules.population` — population sampling and demographics

## Purpose

Generates the initial patient population that the rest of the simulator
consumes. Handles country-appropriate demographic distributions
(age × sex × comorbidity), name / address / date-of-birth generation
delegated to `clinosim.locale`, chronic-condition prevalence sampling,
baseline-vitals derivation, and readmission-tracking metadata.

## Scope

- **In scope**: population-scale demographic sampling with realistic
  age × sex × comorbidity joint distributions, `PatientProfile`
  construction, chronic-condition sampling per disease-prevalence
  weights, baseline-vitals derivation from anthropometrics, first-
  visit / readmission tracking metadata.
- **Out of scope**: name / address / date-of-birth generation (in
  [`clinosim/locale/`](../../locale/README.md)), individual patient
  activation into encounters (in
  [`clinosim/modules/patient/`](../patient/README.md)), disease-
  protocol definitions (in
  [`clinosim/modules/disease/`](../disease/README.md)).

## Public API

```python
from clinosim.modules.population import (
    generate_population,         # (config, rng) -> list[PatientProfile]
    sample_chronic_conditions,   # (age, sex, country, rng) -> list[ChronicCondition]
    derive_baseline_vitals,      # (patient, rng) -> BaselineVitals
)
```

## Dependencies

- `clinosim.types.patient` — `PatientProfile`, `BaselineVitals`,
  `ChronicCondition`.
- `clinosim.types.population` — population-generation intermediate
  types.
- `clinosim.locale` — country name / address / demographic pools.
- `clinosim.modules.disease` — chronic-condition prevalence sources.

## Constants and configuration

- Age / sex distributions per country live in `reference_data/*.yaml`
  and in `clinosim/config/{us,japan}.yaml`.
- Chronic-condition prevalence weights (per age band × sex × country)
  are inline in `engine.py` and are flagged for extraction in
  [`docs/reviews/2026-08-09-constants-audit.md`](../../../docs/reviews/2026-08-09-constants-audit.md).
- `has_visited_hospital` / `last_disease_id` / `was_readmission` /
  `residual_inflammation` — first-visit tracking metadata.

## Directory contents

```
clinosim/modules/population/
  __init__.py           public API
  engine.py             population generation + chronic-condition sampling
  audit.py              per-module audit spec
  reference_data/       demographic distribution YAMLs
```

## Testing

```bash
pytest tests/unit -k population -q
pytest tests/integration -k population -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
