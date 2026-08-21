# `clinosim.modules.population` — catchment-area sampling + healthcare life-events

## Purpose

Generates the initial catchment-area population (households + persons
with demographics, addresses, phones, anthropometrics, lifestyle,
chronic conditions), then drives the year-scale healthcare calendar
(monthly acute-disease events, chronic-follow-up visits, screening,
pediatric visits — merged from
[`clinosim.modules.pediatric`](../pediatric/README.md)). This module
is the head of the simulation pipeline; every downstream module
consumes the `PopulationRegistry` it returns.

## Scope

- **In scope**: household + person construction with country-appropriate
  age × sex sampling, chronic-condition prevalence (with optional
  `sex: M`/`F` filter), name / address / phone generation via
  `clinosim.locale`, anthropometrics (BMI, height with age-based
  shrinkage over `HEIGHT_SHRINKAGE_AGE_THRESHOLD`), lifestyle
  attributes (smoking, alcohol, care-seeking threshold),
  deterministic per-person Rh-factor derivation
  (`_derive_rh_factor` via SHA-256 hash of person_id + country —
  RNG-neutral), monthly acute-disease event sampling with
  seasonal / lifestyle / occupation risk multipliers, annual
  healthcare-calendar generation (chronic follow-ups, mammography /
  colonoscopy / diabetic retinopathy / flu-vaccine screening,
  pediatric visits).
- **Out of scope**: name / address / phone raw data
  ([`clinosim/locale/<country>/`](../../locale/)), disease-protocol
  definitions ([`clinosim.modules.disease`](../disease/README.md)),
  patient activation into an encounter
  ([`clinosim.modules.patient.activator`](../patient/README.md)),
  identity / insurance numbering
  ([`clinosim.modules.identity`](../identity/README.md)), the
  encounter simulator itself
  ([`clinosim.simulator`](../../simulator/)), pediatric visit
  emission (this module delegates to
  [`clinosim.modules.pediatric.calendar.generate_pediatric_events`](../pediatric/README.md)).

## Public API

```python
from clinosim.modules.population import (
    PersonRecord,                       # dataclass (types.population)
    HospitalizationSummary,             # dataclass (types.population)
    LifeEvent,                          # dataclass (types.population)
    generate_population,                # (size, country, rng, base_year=2024, demo=None) -> PopulationRegistry
    generate_monthly_events,            # (registry, year, month, rng, country="US", demo=None) -> list[LifeEvent]
    generate_healthcare_calendar,       # (registry, year, country, rng) -> list[LifeEvent]
)
```

Internal helpers (not re-exported) worth knowing about:
`Household` + `PopulationRegistry` dataclasses in `engine.py`;
`ChronicConditionSpec` frozen dataclass for parsed chronic
prevalence; `_derive_rh_factor(person_id, country)` for the
Rh-factor SHA-256 derivation (Issue #795 pattern); the many
`_sample_*` helpers (`_sample_age_band`, `_sex_ratio_male_probability`,
`_sample_blood_type`, `_sample_surname`, `_sample_given_name`,
`_sample_occupation`).

## Determinism

- **No sub-seed offset in `ENRICHER_SEED_OFFSETS`**. This module is
  the head of the pipeline; the CLI provides the master seed and
  every downstream enricher derives its own sub-seed against that
  master (AD-16). Population sampling uses the master `rng` directly.
- **RNG-neutral additive derivations**: new per-person fields
  (`rh_factor`, and any future biological attribute that follows the
  same pattern) are computed from
  `sha256(person_id + salt)` so master RNG is not consumed. This
  keeps memoize snapshots byte-identical across additions of
  RNG-neutral fields (Issue #795 pattern; contrast with attributes
  that must remain RNG-sampled because they depend on age / sex).
- Monthly event and calendar generation consume the `rng` sequentially
  in a deterministic person / disease / order — YAML edits that add
  or reorder incidence entries can shift downstream stream position;
  this is expected and documented at the caller boundary.

## Dependencies

- `clinosim.modules._shared` — `is_jp`, `normalize_probabilities`
  (with `fallback="raise"` at every callsite).
- `clinosim.modules.disease.protocol` — `load_disease_protocol` for
  the acute-event dispatch.
- `clinosim.modules.disease.severity` — `sample_severity` at
  hospitalization-decision time.
- `clinosim.modules.population._household_thresholds` — household
  size distribution, address / phone digit ranges, apartment
  probabilities, wife-keeps-maiden-name probability, blood-type
  default distribution.
- `clinosim.modules.population._population_thresholds` — BMI /
  height defaults + clamps, care-seeking threshold defaults,
  smoking / alcohol fallback labels + probs, mobile-phone min age.
- `clinosim.modules.population._population_workflow_thresholds` —
  screening probabilities + minimum ages (mammography, colonoscopy,
  diabetic retinopathy, flu vaccine), chronic-visit month cap,
  event-day jitter ranges, unknown-condition rate parameters,
  mixed-conditions probability, prior-hospitalization recurrence
  multiplier.
- `clinosim.locale.loader` — `load_demographics`, `load_names`,
  `load_addresses`, `load_naming_rules`, `load_chronic_followup`.
- `clinosim.modules.pediatric.calendar` — `generate_pediatric_events`
  (imported inside `generate_healthcare_calendar`).
- `clinosim.types.population` — `PersonRecord`,
  `HospitalizationSummary`, `LifeEvent`.
- `hashlib.sha256` — RNG-neutral per-person derivations.
- `numpy` — `np.random.Generator`.

## Constants and configuration

- **Threshold tables** live in the three sibling `_*_thresholds.py`
  files (Issue #637 sweep); every scalar that used to sit inline
  was lifted with a docstring naming its purpose + provenance:
  - `_household_thresholds.py`: household + address + phone shape
    (US + JP), naming rules, blood-type default distribution.
  - `_population_thresholds.py`: BMI / height / care-seeking
    defaults, smoking + alcohol fallback distributions,
    `MOBILE_PHONE_MIN_AGE`, `HEIGHT_SHRINKAGE_AGE_THRESHOLD`.
  - `_population_workflow_thresholds.py`: monthly-event day jitter,
    chronic-visit and screening scheduling, `LEGAL_ADULT_AGE`,
    unknown-condition sampling, `PRIOR_HOSPITALIZATION_RECURRENCE_MULTIPLIER`.
- **Locale-driven data** (no `reference_data/` in this module —
  everything data-shaped lives under `clinosim/locale/`):
  - `demographics.yaml` — age distribution, sex ratio, chronic
    prevalence (with optional `sex` filter), disease incidence,
    seasonal modifiers, disease risk multipliers, lifestyle risk
    multipliers, unknown-condition patterns.
  - `names.yaml`, `addresses.yaml`, `naming_rules.yaml` —
    person / household name and address pools.
  - `chronic_followup.yaml` (locale-shared) — chronic-visit
    follow-up cadence per condition.

## Directory contents

```
clinosim/modules/population/
  __init__.py                          re-exports Person/Life/Hospitalization + 3 generators
  engine.py                            registry construction + monthly events + calendar
  _household_thresholds.py             household / address / phone / naming defaults
  _population_thresholds.py            anthropometrics + lifestyle + care-seeking defaults
  _population_workflow_thresholds.py   screening / chronic-visit / event-day scheduling
  SPEC.md                              extended design reference (not runtime)
```

The module has **no `reference_data/`, no `enricher.py`, no
`audit.py`** — locale YAML is the data source, and the pipeline
head is called directly by the simulator rather than through
`register_builtin_enrichers`.

## Enricher wiring

Not applicable — this module is the head of the simulation pipeline,
not an enricher. It is not registered with
`register_builtin_enrichers` and has no seed offset in
`ENRICHER_SEED_OFFSETS`. The simulator boot calls
`generate_population`, `generate_monthly_events`, and
`generate_healthcare_calendar` directly with the CLI's master RNG.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Simulator boot | [`clinosim/simulator/engine.py`](../../simulator/engine.py) | Calls `generate_population` once, then `generate_monthly_events` + `generate_healthcare_calendar` per year. |
| Inpatient / discharge encounters | [`clinosim/simulator/{inpatient,discharge_gate,unknown_condition}.py`](../../simulator/) | Read `PersonRecord` + `HospitalizationSummary` fields (chronic conditions, prior hospitalizations, care-seeking threshold, lifestyle). |
| Enumeration | [`clinosim/simulator/enumerate.py`](../../simulator/enumerate.py) | Walks `PopulationRegistry` to build per-person iterators. |
| CLI single-encounter driver | [`clinosim/simulator/cli_test_encounter.py`](../../simulator/cli_test_encounter.py) | Uses `generate_population(1, …)` for smoke runs. |
| Pediatric integration | [`clinosim/modules/pediatric/calendar.py`](../pediatric/calendar.py) | Called by `generate_healthcare_calendar` to append pediatric visits per (person, year). |

## Testing

```bash
pytest tests/unit -k population -q
pytest tests/integration -k population -q
```

Individual files:

- [`tests/unit/test_population_types.py`](../../../tests/unit/test_population_types.py)
  — dataclass shape.
- [`tests/unit/test_population_demographics.py`](../../../tests/unit/test_population_demographics.py)
  — demographic sampler invariants.
- [`tests/unit/test_population_engine_sampling.py`](../../../tests/unit/test_population_engine_sampling.py)
  — chronic prevalence + baseline vitals sampling.
- [`tests/unit/test_population_minor_smoking_alcohol_gate.py`](../../../tests/unit/test_population_minor_smoking_alcohol_gate.py)
  — `LEGAL_ADULT_AGE` gate on smoking / alcohol sampling.
- [`tests/unit/test_population_occupation_age_gate.py`](../../../tests/unit/test_population_occupation_age_gate.py)
  — occupation sampling respects `MIXED_CONDITIONS_MIN_AGE_DEFAULT`
  + the OCCUPATION_MISMATCH fallback.
- [`tests/unit/test_cli_population_no_sentinel.py`](../../../tests/unit/test_cli_population_no_sentinel.py)
  — CLI ensures no sentinel leakage.
- [`tests/integration/test_population_severity_source.py`](../../../tests/integration/test_population_severity_source.py)
  — severity sampled via `clinosim.modules.disease.severity`, not
  hard-coded here.
- [`tests/integration/test_bug_d_explicit_population.py`](../../../tests/integration/test_bug_d_explicit_population.py)
  — explicit-population regression guard.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
