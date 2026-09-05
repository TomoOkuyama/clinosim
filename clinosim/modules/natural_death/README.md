# `clinosim.modules.natural_death` — actuarial mortality sampling (Issue #1114 C11g-2)

## Purpose

Samples a per-person natural death date at population-generation time
from national period life tables (US CDC + JP MHLW). Populates the
`PersonRecord.date_of_death` field so downstream event generators can
gate emission on `PersonRecord.is_alive_at(t)`. Ships the "sampling
step" half of the mortality lifecycle — the actual filter wiring is
follow-up work (C11g-3, per #1114 decomposition).

## Scope

- **In scope**: age × sex × country annual qx lookup from
  `locale/shared/actuarial_life_table.yaml`; per-person Bernoulli
  across each sim-window year; assignment of `PersonRecord.date_of_death`
  to a random day in the first firing year; cohort-mortality log line
  via `sim_log`.
- **Out of scope**: filtering the event dispatchers on `is_alive_at(t)`
  (C11g-3), emitting `FHIR Patient.deceasedDateTime` for natural
  deaths (C11g-4/5), in-hospital death (already lives in
  [`discharge_gate.py`](../../simulator/discharge_gate.py) which
  flips `PatientProfile.deceased`).

## Public API

```python
from clinosim.modules.natural_death import sample_natural_deaths  # POST_POPULATION enricher entrypoint
```

The enricher is registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) at
`POST_POPULATION order=20` (after `identity` order=10, before any
event generation). Always-on for both US and JP; a no-op when the
actuarial YAML is missing (test / partial-config paths).

## Determinism

- **Sub-seed offset**: `0x4E44` (`"ND"`) registered in
  [`clinosim/seeding.py`](../../seeding.py) as
  `ENRICHER_SEED_OFFSETS["natural_death"]`. Each person's death draw
  uses a `derive_sub_seed(master_seed, offset, person_id)` sub-RNG, so
  the main simulation stream is untouched (AD-16).
- Byte-shape impact: adds one new per-person RNG cursor. Non-death
  event streams (calendar / inpatient / perinatal / etc.) are
  byte-identical to a pre-C11g-2 run.

## Data source

- `clinosim/locale/shared/actuarial_life_table.yaml`
  - US 2020: CDC NCHS NVSR 71-01, Tables 2 + 3, 5-year band means of
    single-year qx (mean of ages 0-4, 5-9, ..., 95-99).
  - JP 2020: 厚生労働省 第23回生命表 (完全生命表), 生命表(男)+(女),
    same 5-year band mean structure.
- Provenance URLs live in the YAML `provenance` block so a future
  release-cycle bump can grep for stale years.

## Sampling model

For each person P:

1. Walk each calendar year `y` in the sim window
   (`config.time_range[0]` to `config.time_range[1]`).
2. Compute `age_at_y = P.age + (y - sim_start_year)`.
3. Look up `qx(country, sex, age_at_y)` from the 5-year band
   containing `age_at_y`.
4. Bernoulli against `qx` using P's sub-RNG.
5. First year that fires becomes the death year; pick a uniform-day-in-year
   within that year (clamped to the sim-window bounds).
6. Assign `P.date_of_death = <picked date>`; break out of the
   year loop.

Persons who never fire keep `date_of_death = None` and stay alive
for the full window.

## What C11g-2 does NOT do

- Encounters for patients with `date_of_death` still emit at their
  original cadence — the event dispatchers (`generate_monthly_events`,
  `generate_healthcare_calendar`, chronic-followup, calendar
  screening) still check the naive `is_alive` boolean, not the new
  `is_alive_at(t)` predicate. C11g-3 wires the date-aware filter.
- FHIR `Patient.deceasedDateTime` is not populated from `date_of_death`
  yet. In-hospital deaths still use the pre-existing
  `PatientProfile.deceased` boolean flipped by the discharge gate.
  C11g-4/5 unify these paths.
- No `Observation-death-summary` or SSDMF-style FHIR resource emit.

Attempting a partial wire-up (populate `date_of_death` AND filter
some emit sites but not others) is exactly the "impossible data"
regression the #1114 defer comment warned against; keeping the C11g-2
scope isolated is deliberate.

## Verification

- Unit tests: `tests/unit/test_natural_death.py` (9 cases).
  Covers `is_alive_at(t)` correctness, deterministic reproduction
  under the same seed, cohort mortality rate in a realistic band
  (8-40 /kyr for a uniform-per-age cohort of 1000+; the widened band
  accounts for the fact that the CDC 8.7 /kyr headline number is
  weighted against the actual US age pyramid, whereas the uniform-age
  test cohort integrates over more of the very-old tail), death
  date within sim window, and age monotonicity (elderly > 5× young).
- Cohort log: after each simulation the log carries a
  `{"module": "natural_death", "event": "cohort_mortality_sampled",
  "n_total": ..., "n_dead": ..., "per_kyr": ...}` line for grep-based
  audit.

## Related

- [`clinosim/modules/discharge_gate.py`](../../simulator/discharge_gate.py)
  — the existing in-hospital death path (`PatientProfile.deceased`).
- Issue [#1114](https://github.com/TomoOkuyama/clinosim/issues/1114)
  — the 5-part C11g decomposition tracker.
- [`clinosim/locale/shared/actuarial_life_table.yaml`](../../locale/shared/actuarial_life_table.yaml)
  — the qx data source (C11g-1, PR #1147).
