# `clinosim.modules.health_checkup` — JP employer-provided health checkup (opt-in)

## Purpose

Opt-in POST_RECORDS enricher that adds Japanese **employer-provided
annual health checkup** encounters (事業者健診, established under the
Industrial Safety and Health Act) to JP cohorts.

Selects a deterministic 30 % subset of adult patients (age ≥ 40)
via SHA-256 hash on `patient_id` (rate tunable via
`HEALTH_CHECKUP_SUBSET_RATE`) and adds one `CHECKUP` encounter per year
before the simulation snapshot, together with the five statutory
health-checkup measurements (BMI / systolic BP / diastolic BP / HbA1c
/ LDL cholesterol) and a `HEALTH_CHECKUP_REPORT` ClinicalDocument stub
(narrative left `None` — populated by
[`document.narrative`](../document/narrative/README.md) if enabled).

## Scope

- **In scope**: JP-only checkup encounter generation for adult
  patients on an annual cadence, five statutory measurements per
  encounter, deterministic patient-subset selection, ClinicalDocument
  stub emission.
- **Out of scope**: US-side health checkups (US health-maintenance
  encounters follow different regulatory patterns and are not
  currently modelled), narrative-text generation for the checkup
  report (that's [`document.narrative`](../document/narrative/README.md)),
  FHIR serialisation (in [`clinosim/modules/output/`](../output/README.md)),
  non-adult (< 40 yr) health-checkup variants (school checkups,
  specific-age adult checkups are follow-up scope).

## Public API

```python
from clinosim.modules.health_checkup import (
    HEALTH_CHECKUP_SUBSET_RATE,  # deterministic subset rate (default 0.30)
    enrich_health_checkup,       # AD-56 post_records enricher entry
)
```

The enricher is registered at import time; it runs only when
`SimulatorConfig.modules["health_checkup"] == True` and
`SimulatorConfig.country == "JP"`.

## Design principles

- **Opt-in (default OFF)** — preserves the "acute-care hospital"
  assumption of the default clinosim configuration. Gate:
  `SimulatorConfig.modules["health_checkup"]`.
- **JP-only** — gate: `SimulatorConfig.country == "JP"`.
- **AD-16 deterministic** — no new RNG. Patient selection uses
  hash-based logic on `patient_id`.
- **AD-56 Module** (post_records enricher) — matches the shape of
  every other opt-in module.

## Dependencies

- `clinosim.types.patient` — `PatientProfile`, age computation.
- `clinosim.types.encounter` — `Encounter`, `EncounterType.CHECKUP`,
  observation records.
- `clinosim.types.clinical` — `ClinicalDocument`.

## Constants and configuration

- `HEALTH_CHECKUP_SUBSET_RATE = 0.30` — fraction of eligible adults
  (age ≥ 40) selected via SHA-256 hash on `patient_id`. Adjusting this
  changes cohort output byte-identity; treat as a public-API constant.
- Five statutory measurements are hard-coded in the engine because
  they are legally mandated (BMI / SBP / DBP / HbA1c / LDL). Adding a
  sixth measurement is a scope-expansion PR.

## Directory contents

```
clinosim/modules/health_checkup/
  __init__.py           public API (constants + entry point)
  enricher.py           POST_RECORDS enricher body
  audit.py              per-module audit spec
```

## Testing

```bash
pytest tests/unit -k health_checkup -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
