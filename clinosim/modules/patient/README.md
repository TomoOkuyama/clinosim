# `clinosim.modules.patient` — patient activation

## Purpose

Turns a `PatientProfile` (produced by
[`clinosim.modules.population`](../population/README.md)) into an
active simulation subject. Handles chronic-condition activation by
severity, sets the initial physiological baseline, and wires up
patient-scoped RNG derivation for downstream stochastic paths.

## Scope

- **In scope**: `activate_patient` orchestration, per-condition
  severity → activation-probability sampling, chronic-medication
  attachment from disease profiles, `HomeMedication` list assembly,
  hardcoded test-patient fixture (`create_test_patient`) for v0.1-alpha
  tests.
- **Out of scope**: patient *generation* (in
  [`clinosim.modules.population`](../population/README.md)),
  disease *definitions* (in
  [`clinosim.modules.disease`](../disease/README.md)), encounter
  simulation (in [`clinosim.simulator`](../../simulator/README.md)).

## Public API

```python
from clinosim.modules.patient import activate_patient
from clinosim.modules.patient.test_patient import create_test_patient
```

`activate_patient(patient, rng, ...) -> PatientProfile` mutates the
input in place (attaches chronic conditions, initial state, home
medications) and returns it for fluency.

`create_test_patient()` returns a deterministic 72-year-old Japanese
female with hypertension + type-2 diabetes for use in v0.1-alpha unit
tests that need a stable patient without invoking the full
population module.

## Dependencies

- `clinosim.types.patient` — `PatientProfile`, `HomeMedication`,
  `ChronicCondition`, `PatientPhysiologicalProfile`, `BaselineVitals`.
- `clinosim.types.allergy` — `Allergy`, `AllergyReaction`.
- `clinosim.modules.disease` — chronic-medication sources.
- `clinosim.simulator.helpers` — sub-seed derivation (AD-16).

## Constants and configuration

- Severity-to-activation-probability dicts per chronic-condition ICD
  code live inline in `activator.py` and are one of the three
  high-leverage hotspots identified in
  [`docs/reviews/2026-08-09-constants-audit.md`](../../../docs/reviews/2026-08-09-constants-audit.md)
  (Hotspot C).
- `_RESERVE_BETA_PARAMS = (30, 2)` — Beta distribution shape for
  physiological reserve; documented as an empirical tuning constant.

## Directory contents

```
clinosim/modules/patient/
  __init__.py           public API
  activator.py          activate_patient + chronic-condition activation
  test_patient.py       create_test_patient (v0.1-alpha hardcoded fixture)
  audit.py              per-module audit spec
```

## Testing

```bash
pytest tests/unit -k patient -q
pytest tests/integration -k patient -q
```

Approximately 20+ test files reference this module.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
