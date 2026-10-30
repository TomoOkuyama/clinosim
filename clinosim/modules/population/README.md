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
  pediatric visits, the **pregnancy lifecycle** for women aged 15–49 —
  an annual conception Bernoulli against
  `shared/perinatal.yaml::lifecycle.annual_conception_rate`, then prenatal
  visits, delivery + postpartum visits or an abortion event, via
  `_pregnancy.py::_pregnancy_lifecycle_events` — and **chemotherapy
  cycle** LifeEvents for oncology-marker patients at each regimen's
  cycle interval via `_chemo.py::_chemo_cycle_events` reading
  `clinosim/locale/shared/chemo_regimens.yaml`); the annual aging
  step (`aging.py::advance_population`), forward community mortality
  (`mortality.py`), death bookkeeping (`vital_status.py`) and newborn
  registration / inheritance (`newborn.py`, `person_init.py`,
  `inheritance.py`, `single_gene_inheritance.py`).
- **In scope (chronic-prevalence schema)**: two `chronic_prevalence`
  entry forms are supported per condition — the historical single-sex
  form (`sex: M|F` + `bands`) for codes locked to one sex (e.g. `N40`
  BPH, `Z34` pregnancy, `C61` prostate), and the `by_sex` form
  (`by_sex: {F: {bands}, M: {bands}}`) which activates the primary
  sex as usual plus an opposite-sex `augment_sex_bands` sub-population
  under an independent per-`(patient, code)` sub-seed
  (`chronic_augment_sex_seed`). Male breast cancer (~1 % of C50) is
  the canonical `by_sex` consumer; the two forms MUST NOT be mixed on
  the same code.
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

## Population lifecycle (as implemented)

The simulation advances month by month in one forward loop
(`clinosim/simulator/phases/_forward_loop.py`):

1. **Initial cohort** — `generate_population` builds households and persons
   at the window start; POST_POPULATION enrichers add identity, allergies
   and metabolic codes.
2. **Year boundary** — `aging.advance_population`: one forward
   **community-death** draw per person over the part of the year they are
   simulated and alive (`mortality.py`: life-table qx × comorbidity SMR /
   the mean SMR of the same age band and sex × the locale's
   `community_death_share`), the aging passes (stroke sequela, allergy
   drift) and the longitudinal stage / onset step. The forward loop then
   generates and queues the year's healthcare calendar.
3. **Each month** — life events, the month's ED visits, and every queued
   event (admissions, readmissions, follow-ups, calendar visits, deliveries)
   are dispatched in date order.
4. **Death** — recorded once per person (`PersonRecord.record_death`,
   `death_place` = `hospital` or `community`). An in-hospital death comes
   from the inpatient simulator; a community death needs no hospital visit.
   Every later event is gated by `in_population_at(date)`.
5. **Birth** — a delivery registers the newborn (`newborn.register_newborn`);
   the newborn enrolls the day after the birth-stay discharge
   (`PersonRecord.enrolled_from`), gets a rest-of-year calendar, and from
   then on ages, accrues conditions, visits and can die like everyone else.

Migration (move-in / move-out) is not modelled.

## Public API

```python
from clinosim.modules.population import (
    PersonRecord,                       # dataclass (types.population)
    HospitalizationSummary,             # dataclass (types.population)
    LifeEvent,                          # dataclass (types.population)
    generate_population,                # (size, country, rng, base_year=2024, demo=None) -> PopulationRegistry
    generate_monthly_events,            # (registry, year, month, rng, country="US", demo=None,
                                        #  master_seed=None, inpatient_departments=None) -> list[LifeEvent]
    generate_healthcare_calendar,       # (registry, year, country, rng) -> list[LifeEvent]
    BMI_OVERWEIGHT_THRESHOLD,           # float constants (_population_thresholds)
    BMI_OBESE_THRESHOLD,
    BMI_MORBID_OBESITY_THRESHOLD,
)
```

Submodule entry points used by the simulator (imported by path, not
re-exported): `aging.advance_population(registry, year, locale,
window=None)`, `mortality.draw_community_death` /
`annual_death_probability`, `vital_status.record_hospital_death` /
`sync_profile_death_dates` / `death_counts_by_place`, and
`newborn.register_newborn`.

Internal helpers (not re-exported) worth knowing about:
`Household` + `PopulationRegistry` dataclasses in `engine.py`;
`ChronicConditionSpec` frozen dataclass for parsed chronic
prevalence (`_chronic.py`); `_derive_rh_factor(person_id, country)`
for the Rh-factor SHA-256 derivation (Issue #795 pattern,
`_demographics.py`); the many `_sample_*` helpers
(`_sample_age_band`, `_sex_ratio_male_probability`,
`_sample_blood_type` in `_demographics.py`; `_sample_surname`,
`_sample_given_name`, `_sample_occupation` in `_identity.py`).

## Cohort skew vs sampled population

`demographics.yaml → age_distribution` is the **input sampling target**
for the synthetic general population, matching each country's public
Census (US Census Bureau 2020 / 総務省統計局 2020 国勢調査). It is
**not** the target for the emitted patient cohort.

The pipeline drops non-visiting persons at two stages:

1. **`care_seeking` threshold** (per-person random draw, elderly more
   likely to seek care) — filters out persons who never contact a
   provider in the simulated window.
2. **Encounter-emission gate** — persons with zero encounters in the
   window are excluded from Patient.ndjson output.

The compound effect is an elderly-heavy patient cohort. For JP
p=1000 s=42 the observed 65+ share is ~48%, compared with 30% in
the sampled population — matching MHLW 患者調査 2020 (65+ ≈ 56%
of total hospital patients) far more closely than 国勢調査 (65+ ≈ 30%
of the general population).

**Do not "correct" `age_distribution`** to make the emitted cohort
match Census. The general-population sampling contract is depended on
by demographics-conditional risk calculations (life expectancy,
comorbidity correlations, seasonal event risk) that expect a Census-
shaped input. Cohort skew audits should compare against the hospital
patient survey benchmark, not the general Census.

See [`scripts/audit_realworld_stats_jp.py`](../../../scripts/audit_realworld_stats_jp.py)
for the correct comparison metric.

## Marginal-preserving prevalence (B-3)

`chronic_prevalence[code][band]` in each locale's `demographics.yaml` is
semantically the **target marginal prevalence in the sampled synthetic
population** (the input to the pipeline), not a per-patient conditional
probability. The **emitted patient cohort** (after downstream
care-seeking + encounter-emission filters) skews sicker than the sampled
population by design — see "Cohort skew vs sampled population" above.

The engine samples each chronic code as:

```
scaled_base = base_prev / E[compound multiplier over (age, sex)]
final_prev  = min(1, scaled_base * corr_mult(patient) * life_mult(patient))
```

where `E[compound]` is the population-expected product of comorbidity
correlation and lifestyle (BMI + smoking) multipliers a fresh draw for
this code would experience given the age × sex population. Because
`E[corr_mult(patient) * life_mult(patient)] ≈ E[compound]` (independence
of BMI × smoking × prior-code sampling), the population marginal
converges to `base_prev` while the multipliers still shape WHICH
patients get the condition.

Helper functions in `_chronic.py` (all pure, no new tunable constants — everything is
derived from yaml `chronic_prevalence`, `comorbidity_correlations`,
`lifestyle_risk_multipliers`, `physiology.bmi`, and
`lifestyle_distribution.smoking`):

- `_target_prev_at_age_legacy(spec, age)` — looks up the primary-sex
  band that contains `age` (ignores `augment_sex_bands`); returns 0 if
  none.
- `_bmi_category_probabilities(demo, sex_key)` — analytical Normal CDF
  on `(mean, std)` against the `overweight` / `obese` thresholds.
- `_smoking_status_probabilities(demo, sex_key, age)` — normalized
  yaml distribution; forced to `{never:1.0}` under `LEGAL_ADULT_AGE`.
- `_expected_lifestyle_multiplier(demo, code, sex_key, age)` —
  `E[bmi_mult] * E[smoking_mult]`.
- `_expected_comorbidity_multiplier(chronic_data, code, age, sex,
  comorbidity_cfg)` — `Π (1 + P_prior * (m_prior→code - 1))` over
  earlier codes in `chronic_data` iteration order.

This replaces the earlier "reduce base_prev to compensate for the
multiplicative pipeline" Issue #739 workaround. The Issue #739 downscales
in `chronic_prevalence` are now over-compensations against the new
engine and will be reverted in a follow-up recalibration PR (B-3 phase 2).

## Determinism

- **No sub-seed offset in `ENRICHER_SEED_OFFSETS`**. This module is
  the head of the pipeline; the CLI provides the master seed and
  every downstream enricher derives its own sub-seed against that
  master (AD-16). `generate_population` uses the master `rng`
  directly; the forward loop passes `generate_monthly_events` a
  per-month RNG and `generate_healthcare_calendar` a per-year RNG
  (per-person for a newborn's rest-of-year calendar), all from
  `clinosim.seeding.derive_phase_rng`.
- **Aging / mortality sub-seeds**: `aging.aging_sub_seed(person_id,
  year, pass_name)` gives each aging pass, the community-death draw
  (`"mortality"`) and the longitudinal step their own per-(person,
  year) RNG, so skipping or adding a person does not shift anyone
  else's draws.
- **RNG-neutral additive derivations**: new per-person fields
  (`rh_factor`, and any future biological attribute that follows the
  same pattern) are computed from
  `sha256(person_id + salt)` so master RNG is not consumed. This
  keeps memoize snapshots byte-identical across additions of
  RNG-neutral fields (Issue #795 pattern; contrast with attributes
  that must remain RNG-sampled because they depend on age / sex).
- **Per-patient sub-seeds** (defined in
  [`clinosim/seeding.py`](../../seeding.py) alongside
  `ENRICHER_SEED_OFFSETS`): `chronic_augment_sex_seed(patient_id, code)`
  gates the `by_sex` opposite-sex augmentation so the master
  chronic-prevalence RNG stream stays byte-identical to the
  pre-augmentation path; `chronic_isolated_seed(patient_id, code)`
  draws codes marked `rng_isolated: true` off the master stream;
  `perinatal_delivery_seed(patient_id, year)` drives the pregnancy
  lifecycle draws (conception, delivery-date jitter);
  `chemotherapy_regimen_seed(patient_id, cancer_code)` picks a chemo
  regimen from `chemo_regimens.yaml` and the cycle-1 start date;
  newborn perinatal-condition sampling (P59.9 / P07.3 → P22.0 /
  L22 / L20.9) and abortion-outcome sampling (O03.9 / O04.5) route
  through sibling per-patient sub-seeds owned in
  [`clinosim/simulator/perinatal.py`](../../simulator/perinatal.py).
- Monthly event and calendar generation consume their `rng` sequentially
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
  `load_addresses`, `load_naming_rules`, `load_chronic_followup`,
  `load_perinatal_config`, `load_chemo_regimens`,
  `load_actuarial_life_table`, `load_condition_mortality_smr`,
  `load_comorbidity_progression_multipliers`,
  `load_single_gene_diseases`; `clinosim.locale.loaders.clinical` —
  `load_ckd_under60_prevalence`.
- `clinosim.modules.longitudinal.engine` — `initial_snapshot`,
  `advance_one_year`.
- `clinosim.modules.allergy.engine`, `clinosim.modules.identity.assign`
  — allergy drift and newborn identity.
- `clinosim.seeding` — per-patient sub-seeds;
  `clinosim.simulator.perinatal.resolve_pregnancy_outcome` — abortion
  roll for the pregnancy lifecycle.
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
  - `shared/actuarial_life_table.yaml` (qx by locale / sex / 5-year
    band, plus `community_death_share` per locale) and
    `shared/condition_mortality_smr.yaml` (`smr_table`,
    `combine_method`) — forward community mortality.
  - `shared/perinatal.yaml` (`lifecycle`), `shared/chemo_regimens.yaml` —
    pregnancy lifecycle and chemotherapy cycles.

## Directory contents

```
clinosim/modules/population/
  __init__.py                          re-exports Person/Life/Hospitalization + 3 generators + BMI thresholds
  engine.py                            registry construction + monthly events + calendar
  aging.py                             advance_population — yearly mortality draw + aging passes + longitudinal step
  mortality.py                         forward community mortality (life-table qx × relative SMR × community share)
  vital_status.py                      in-hospital death recording + profile death-date sync + death counts
  newborn.py                           register_newborn — newborn PersonRecord from the delivery
  person_init.py                       newborn biology / identity / care-seeking + birth-year death draw
  inheritance.py                       newborn blood type / Rh inheritance (RNG-neutral)
  single_gene_inheritance.py           single-gene carrier status (initial cohort + newborn)
  condition_mutex.py                   mutually exclusive chronic-code rules
  _chronic.py                          ChronicConditionSpec + marginal-preserving prevalence helpers
  _demographics.py                     age / sex / race / blood-type / care-seeking sampling
  _identity.py                         name / occupation / address / phone sampling
  _pregnancy.py                        pregnancy lifecycle scheduler
  _chemo.py                            chemotherapy regimen pick + cycle events
  _ckd_under60.py                      RNG-neutral CKD (N18) assignment under age 60
  _pediatric_anthropometry.py          pediatric height / BMI reference lookup
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
`generate_population` with the CLI's master RNG; the forward loop
calls `advance_population`, `generate_monthly_events` and (via
`phases/_healthcare_calendar.py`) `generate_healthcare_calendar`
directly with derived RNGs.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Simulator boot | [`clinosim/simulator/engine.py`](../../simulator/engine.py) | Calls `generate_population` once; after the loop, `sync_profile_death_dates` + `death_counts_by_place`. |
| Forward loop | [`clinosim/simulator/phases/_forward_loop.py`](../../simulator/phases/_forward_loop.py), [`_healthcare_calendar.py`](../../simulator/phases/_healthcare_calendar.py) | `advance_population` + calendar at each year boundary, `generate_monthly_events` each month. |
| Inpatient death | [`clinosim/simulator/_dispatch.py`](../../simulator/_dispatch.py), [`phases/_readmission.py`](../../simulator/phases/_readmission.py) | `record_hospital_death` for stays that end in death. |
| Perinatal | [`clinosim/simulator/perinatal.py`](../../simulator/perinatal.py) | `register_newborn` at delivery; sets `enrolled_from` to the day after the birth-stay discharge. |
| Inpatient / discharge encounters | [`clinosim/simulator/{inpatient,discharge_gate,unknown_condition}.py`](../../simulator/) | Read `PersonRecord` + `HospitalizationSummary` fields (chronic conditions, prior hospitalizations, care-seeking threshold, lifestyle). |
| Enumeration / CLI single-encounter driver | [`clinosim/simulator/enumerate.py`](../../simulator/enumerate.py), [`cli_test_encounter.py`](../../simulator/cli_test_encounter.py) | Build `PersonRecord`s directly for forced / smoke cases (no `PopulationRegistry`). |
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
  — developmental-stage occupation labels for minors
  (`_sample_occupation` age brackets).
- [`tests/unit/test_cli_population_no_sentinel.py`](../../../tests/unit/test_cli_population_no_sentinel.py)
  — CLI ensures no sentinel leakage.
- [`tests/integration/test_population_severity_source.py`](../../../tests/integration/test_population_severity_source.py)
  — severity sampled via `clinosim.modules.disease.severity`, not
  hard-coded here.
- [`tests/integration/test_bug_d_explicit_population.py`](../../../tests/integration/test_bug_d_explicit_population.py)
  — explicit-population regression guard.
- [`tests/unit/test_death_record_2166.py`](../../../tests/unit/test_death_record_2166.py)
  — `record_death` / `is_alive` / `vital_status` death bookkeeping.
- [`tests/unit/test_forward_mortality_2167.py`](../../../tests/unit/test_forward_mortality_2167.py)
  — forward community-mortality draw in `advance_population`.
- [`tests/unit/test_newborn_enrollment_2168.py`](../../../tests/unit/test_newborn_enrollment_2168.py)
  — newborn enrollment at birth-stay discharge.
- [`tests/integration/test_forward_loop_lifecycle_2169.py`](../../../tests/integration/test_forward_loop_lifecycle_2169.py)
  — forward-loop lifecycle invariants (no encounter after death,
  newborn joins the population).

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
