# `clinosim.modules.natural_death` — actuarial mortality lifecycle (Issue #1114 C11g complete)

## Purpose

Samples a per-person natural death date at population-generation time
from national period life tables (US CDC + JP MHLW), then gates every
downstream event generator + FHIR emitter on
`PersonRecord.is_alive_at(t)`. The full mortality lifecycle
(sample → filter → FHIR emit) is complete as of session 103.

## Scope

- **In scope**:
  - **Sampling** (C11g-2, PR #1150): age × sex × country annual qx
    lookup from `locale/shared/actuarial_life_table.yaml`; per-person
    Bernoulli across each sim-window year; assignment of
    `PersonRecord.date_of_death` to a random day in the first firing
    year; cohort-mortality log line via `sim_log`.
  - **Event-dispatcher gating** (C11g-3a, PR #1152): `is_alive_at(t)`
    threaded into the 4 event dispatchers
    (`generate_monthly_events`, `generate_healthcare_calendar`,
    chronic-followup, ED / readmission) so no encounter is generated
    after a patient's `date_of_death`.
  - **FHIR Patient alignment** (C11g-3b + 4 + 5, PR #1153):
    `Patient.deceasedDateTime` populated from `date_of_death` +
    `Patient.active = false` on every deceased record. Living
    patients keep `active = true` + `deceasedBoolean = false`.
- **Out of scope**: in-hospital death (already lives in
  [`discharge_gate.py`](../../simulator/discharge_gate.py) which
  flips `PatientProfile.deceased`; C11g-2/3 do not disturb that
  path); explicit `Observation-death-summary` or SSDMF-style FHIR
  resource emit (unified `deceasedDateTime` is sufficient for the
  current downstream contract).

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

## What the C11g lifecycle does NOT do

- **No `Observation-death-summary` or SSDMF-style FHIR resource
  emit** — `deceasedDateTime` on `Patient` is the single source of
  truth for downstream consumers, matching FHIR R4 base and
  us-core-patient / jp-core-patient practice. Extending to a
  dedicated death Observation is possible but not currently
  requested.
- **No cause-of-death coding** — the sampling model draws a death
  date only, not an ICD-10 R99 / cause-specific code. Adding a
  drawn cause would require a separate mortality-cause distribution
  YAML (deferred; not requested).
- **In-hospital deaths continue to use `PatientProfile.deceased`**
  flipped by the discharge gate. `is_alive_at(t)` respects both
  the sampled `date_of_death` and the discharge-gate flip, so the
  two paths compose without double-counting.

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
  — the 5-part C11g decomposition tracker (fully closed).
- [`clinosim/locale/shared/actuarial_life_table.yaml`](../../locale/shared/actuarial_life_table.yaml)
  — the qx data source (C11g-1, PR #1147).
- Wiring PRs: [#1150](https://github.com/TomoOkuyama/clinosim/pull/1150)
  (C11g-2 sampling), [#1152](https://github.com/TomoOkuyama/clinosim/pull/1152)
  (C11g-3a event-dispatcher gating),
  [#1153](https://github.com/TomoOkuyama/clinosim/pull/1153) (C11g-3b + 4 + 5
  FHIR Patient alignment).
