# `clinosim.modules.immunization` — immunization-history synthesis

## Purpose

Generates each patient's vaccine history (adult schedule, paediatric
routine series and, for US, pregnancy-triggered maternal Tdap) from a
per-country CVX-coded schedule (eligibility age, program availability
date, frequency, season, EHR retention window, age × sex coverage) and
writes the result to `CIFPatientRecord.immunizations`, binding each
dose to an encounter where one exists. Downstream FHIR
and CSV adapters emit `Immunization` resources and an
`immunizations.csv` file. A small fraction of scheduled doses are
recorded as explicit refusals (`status="not-done"`) to mirror real
EHR documentation.

## Scope

- **In scope**: sampling `annual`, `every_n_years`, `once`, or
  `pediatric_series` vaccinations per schedule entry; per-age × sex
  coverage lookup (per-dose marginal `coverage_by_sex` for paediatric
  series, drawn conditionally on the previous dose — Issue #3288);
  occurrence-date placement (annual → month drawn from
  `seasonal_distribution`, else fixed `season_month`, then the day: a
  clinic day of that month within the eligible range, picked by sha256 of
  patient, vaccine and season (no draw; `generate_immunizations_for_country`, the enricher's call, takes the country;
  Issue #3683); every-n-years →
  step of `interval_years` from the eligible start; once → month drawn
  from `wave_epochs` when declared, else uniform in the eligible
  window; pediatric_series → per-dose `[age_days_min, age_days_max]`
  window snapped to the canonical well-child visit age, a missed dose
  discontinuing the rest of the series, and each dose kept at least its
  `min_interval_days` after the earlier dose — Issue #3001); US maternal Tdap (CVX 115,
  27–36 weeks of each non-aborted pregnancy, coverage 0.78);
  refusal-documentation emission at rate
  `IMMUNIZATION_NOT_DONE_RECORDING_RATE`; binding doses to existing
  encounters and synthesising a companion vaccination encounter for
  in-window orphans (see *Encounter binding*); synthetic
  lot number generation (structural placeholder, NOT an authoritative
  batch); Feb 29 birthday clamping to Feb 28 in non-leap years;
  optional `history_years` retention window (e.g. flu → 10 y).
- **Out of scope**: paediatric catch-up outside the catch-up vaccination
  visits (see *Encounter binding*), reaction / adverse-event generation, scheduling immunization visits
  in the simulator's encounter loop (vaccination encounters are only
  synthesised post hoc by the enricher), FHIR / CSV serialisation
  ([`clinosim.modules.output`](../output/README.md)), CVX display
  text ([`clinosim/codes/data/cvx.yaml`](../../codes/data/cvx.yaml)).

## Public API

`__init__.py` is empty; consumers import the building blocks
directly:

```python
from clinosim.modules.immunization.engine import (
    generate_immunizations,          # (patient, schedule, as_of, rng, nurse_ids=None)
    generate_immunizations_for_country,  # (country, patient, schedule, as_of, rng, nurse_ids=None): flu dose on a clinic day (Issue #3683)
                                     #   -> list[ImmunizationRecord] (sorted by date)
    generate_pregnancy_tdap,         # (patient, as_of, rng, country, default_nurse="")
                                     #   -> list[ImmunizationRecord] (US only)
    load_schedule,                   # (country) -> {vaccine_name: {cvx, min_age, frequency, ...}}
    IMMUNIZATION_NOT_DONE_RECORDING_RATE,  # 0.02
)
from clinosim.modules.immunization.enricher import enrich_immunizations
```

`load_schedule` returns `{}` for unsupported countries (2026-07-02
grand-design contract) — the enricher's empty-map path is a no-op.

## Determinism

- Sub-seed offset `0x494D` (`"IM"`), registered in
  [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["immunization"]`.
- Per-patient RNG:
  `derive_sub_seed(master_seed, offset, patient_id)` — the main
  patient RNG stream is not consumed. `generate_pregnancy_tdap` draws
  from the same per-patient generator after the schedule pass.
- Paediatric doses snap to the well-child anchor age plus a
  deterministic 0..+6-day scatter (`_det_hash(pid, anchor) % 7`); the
  per-dose rng offset is still drawn and discarded to keep the cursor
  stable.
- Companion vaccination encounter ids are
  `ENC-VAX-{patient_id}-{sha256(patient|date|synth-vax)[:12]}` — keyed
  on (patient, date), so all doses given the same day share one
  encounter.
- **Lot number determinism uses SHA-256, not Python's builtin
  `hash()`**. Python's builtin string hash is salted per interpreter
  invocation (`PYTHONHASHSEED`), so lot numbers used to vary between
  two runs at a fixed seed. P1-7 caught the drift via
  `reproduce.sh`; `_det_hash` in `engine.py` now backs every lot-number
  computation.
- **A re-dated dose gets the lot of its new date** (Issue #3282). The lot
  `L<MFR>-<YYYYMM>-<BATCH>` embeds the dose month; every path that moves
  `occurrence_date` (vaccination-visit binding, nearest-encounter
  alignment, clinic-day hold) goes through `engine.redate`, which
  regenerates the lot of a given dose, keyed by the schedule entry's CVX
  (`lot_cvx_by_cvx`). No lot is dated after its administration.
- Family-nurse assignment for `administered_by`: deterministic
  `nurse_ids[sum(ord(c) for c in patient_id) % len(nurse_ids)]` — one
  nurse per patient (RM-3, matches JP practice where nurses
  administer routine vaccines).

## Cumulative record vs per-season semantics

`coverage_by_age_sex` in each schedule YAML holds **per-scheduled-dose**
probabilities — for annual vaccines that means the **per-season** rate
(matching MHLW 接種率 / CDC FluVaxView statistics), and for `once`
vaccines it is the lifetime "ever received" rate.

**Do not misread aggregate audit metrics.** Because `history_years=10`
retains a decade of annual flu shots, a 65+ patient's probability of
having ≥1 flu Immunization on record approaches 1.0 even at a
per-season rate of ~0.55. Combined with the once-in-lifetime COVID and
PPSV23 draws, aggregate "% of 65+ patients with ≥1 Immunization
record" approaches 100%. This is the correct EHR behavior — a
hospital-attending elderly patient realistically has a multi-year
vaccination history on file.

Comparing that aggregate against a per-season statistic (e.g. MHLW
インフルエンザ 65+ ~53%) is an apples-to-oranges error. The correct
audit is the per-vaccine, per-scheduled-dose rate:

```python
# For annual vaccines: total shots / (n_eligible_patients * history_years)
# For once vaccines:   n_patients_with_shot / n_eligible_patients
```

The audit script under
[`scripts/audit_realworld_stats_jp.py`](../../../scripts/audit_realworld_stats_jp.py)
uses these correct metrics.

## Snapshot (AD-32)

`as_of = ctx.config.snapshot_date` when set, otherwise the latest
encounter admission date on the record (a `ValueError` is raised when
neither exists); either way it is capped at the patient's
`date_of_death`. `occurrence_date > as_of` is skipped, so partial data
during in-progress snapshots is not back-dated.

## Encounter binding

`enrich_immunizations` pools each patient's encounters across all of
their records, then binds each dose (deterministic, no rng):

1. a dose dated inside an inpatient stay binds to that stay and keeps
   its date (e.g. the hepatitis B birth dose in the nursery); the dose is
   also ordered at the admission (`_order_stay_doses`, Issue #3688: a
   medication order of the vaccine's `order_drug_id`, no medication
   administration, since the `Immunization` is the administration);
2. `visits.bind_to_vaccination_visits` (Issue #2868): an outpatient
   visit with reason `Z23` records the doses given at it, re-dated to the
   visit. The season's flu dose goes to the season's first flu
   vaccination visit (`flu_vaccination` encounter condition; a new dose
   when the engine drew none) and no other flu record of that season is
   kept. For a person the healthcare calendar offers flu visits to
   (`population.is_flu_vaccination_candidate`), a season the calendar
   covered without a visit keeps no flu dose: the visit draw is the
   season's decision, so the engine's draw does not add to it. Any season
   keeps at most one flu record. A pediatric immunization visit records
   the `pediatric_series` doses whose age window holds the visit age
   (the engine's dose moved there, or a new one when the series is on
   track: dose 1, or the previous dose given). At a visit the pediatric
   schedule flags `catch_up` (kindergarten, adolescent; Issue #3282) a
   series the child is behind on (doses 1..k given before the visit, no
   refusal charted) also gets its next dose k+1, once the visit age has
   reached that dose's window and is within the series'
   `catch_up_max_age_days`, and the series' minimum interval since dose k
   holds — the continuation of the series, never a restart; one dose of a
   series per visit;
3. otherwise snaps the dose to the nearest outpatient encounter within
   ±60 days and records its `encounter_id`; a flu dose only to an
   encounter in its own season and vaccination months, and no dose to an
   encounter before its vaccine's `min_age_days` floor. A dose is never
   snapped onto a day that holds another dose of the same vaccine, out of
   series order, or closer to a neighbouring dose than the series'
   `min_interval_days` (Issue #3001); with no allowed encounter it keeps
   its own date. A series dose is never snapped outside its schedule
   window (`age_days_min`..`age_days_max`), and doses the engine gave one
   date (the infant series co-due at one well-child visit) move together to
   one visit — all of them or none (Issue #3567). A dose is never snapped
   onto an acute-illness or febrile visit (Issue #3655): a pediatric visit
   whose `visit_condition_id` is one of the pediatric schedule's
   `presentations` (`pediatric.calendar.is_acute_illness_condition`), or any
   visit with a temperature at or above `febrile_celsius` of
   `reference_data/vaccination_precautions.yaml` (38.0 C) on its day
   (`enricher.acute_visit_encounter_ids`); the dose takes a well, vaccination
   or follow-up visit, else its own `ENC-VAX-*` visit.

A tetanus toxoid dose given in the emergency department (a one-time order
whose administration the ED records) is also an Immunization (Issue #3685):
`enricher.ed_vaccine_doses` adds, for each given administration of a drug of
`reference_data/ed_vaccine_doses.yaml` `drug_cvx` (`tetanus_toxoid` -> CVX 35),
a completed dose on the administration's date, bound to its order's
encounter, with a synthetic lot and the administering nurse, once per patient
however many records carry it. A scheduled tetanus-containing dose
(`tetanus_containing_cvx`: 35, 113, 115) within `after_wound_dose_days` (1826,
5 years) after it is not given (`drop_wound_covered_doses`; maternal Tdap and
the paediatric series are untouched). No rng draw.

A dose still unbound and dated before the simulation window start
(`config.time_range[0]`) is marked `primary_source=False` and left
unlinked. An in-window orphan gets a synthesised outpatient
`ENC-VAX-*` encounter (department `primary_care`, admission diagnosis
`Z23`, attending picked deterministically from the primary-care
physician roster), hosted once per patient. When any `ENC-VAX-*`
encounter exists, `document.engine.document_enricher` is re-invoked so
those encounters get their document stubs.

A synthesised `ENC-VAX-*` encounter lasts `duration_minutes` (15, `reference_data/vaccination_visit.yaml`; Issue #3656), so its pre-vaccination check and the dose fall inside its period; the FHIR builder gives a vital-sign set taken outside the primary encounter's period the record's other outpatient encounter whose period holds it (`ed_reattribution.vital_sign_encounter_id`).

Each synthesised `ENC-VAX-*` encounter also gets the visit's pre-vaccination
vital signs (Issue #3464): one `VitalSignRecord` at the visit instant,
temperature and pulse for a child and additionally blood pressure for an
adult (`_visit_vitals` in `locale/shared/chronic_followup.yaml`), derived
from the patient's physiological state through a sub-RNG seeded by the
encounter id, so no existing stream gains a draw.

`Z23` is the ICD-10-CM "Encounter for immunization" the CIF records on a
vaccination visit. In WHO ICD-10 (JP output) `Z23` means single bacterial
diseases only, so `visits.vaccination_visit_reason_codes(country, cvx_codes)`
gives a JP visit the WHO need-for-immunization code of each vaccine given at
it (`locale/jp/code_mapping_vaccination_reason.yaml`: influenza Z25.1,
COVID-19 / varicella / rotavirus Z25.8, JE Z24.1, hepatitis B Z24.6, MR
Z27.8, DTaP-IPV Z27.3, BCG Z23.2, Hib / pneumococcal Z23.8; Z26.9 when no
listed vaccine is linked). The FHIR Encounter and Procedure `reasonCode` use
it; US output keeps `Z23` (Issue #3008).

## Dependencies

- `clinosim.modules._shared` — `is_us` / `is_jp`,
  `get_attr_or_key` / `set_attr_or_key`.
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.types.encounter` — `ImmunizationRecord` (imported
  lazily inside the engine functions); `Encounter` /
  `EncounterStatus` / `EncounterType` for companion encounters.
- `clinosim.codes` — `system_key_for` (enricher); CVX display lookup
  happens in the FHIR builder.
- `clinosim.countries` — `is_jp` (enricher); `clinosim.locale.i18n`
  — `t`.
- `clinosim.age_bands` — `lookup_age_band`.
- `clinosim.datafiles` — `load_data_yaml` (schedule YAML).
- `clinosim.determinism` — per-patient sub-RNG construction.
- `numpy` — `np.random.Generator` for coverage sampling.
- `hashlib.sha256` — via `_det_hash`, for lot-number determinism.

Other module dependencies are lazy imports in the enricher:
`clinosim.modules.staff.engine.scoped_nurses` (the primary-care and
ward nurse pools that `administered_by` is chosen from) and
`clinosim.modules.document.engine.document_enricher` (companion
encounter documents).
`visits.py` lazily imports `clinosim.modules.pediatric.calendar.catch_up_visit_reasons`
(the labels of the catch-up vaccination visits, Issue #3282),
`clinosim.modules.population` (flu-visit candidacy and months) and
`clinosim.modules.encounter.protocol` (the flu visit's chief complaint).

## Constants and configuration

- Module-level constant (in `engine.py`):
  - `IMMUNIZATION_NOT_DONE_RECORDING_RATE = 0.02` — per-scheduled-dose
    probability of emitting an explicit `status="not-done"` record on
    a failed coverage draw. Represents documented refusals /
    deferrals, distinct from silent no-shows. Applied in every
    scheduling branch (`annual`, `every_n_years`, `once`,
    `pediatric_series`) and to maternal Tdap (`once` since #2207).
- Locale schedules (the module's `reference_data/` holds only `vaccination_precautions.yaml`):
  - [`clinosim/locale/us/immunization_schedule.yaml`](../../locale/us/immunization_schedule.yaml)
    — CDC ACIP schedule. Currently 18 entries: 5 adult (Influenza,
    COVID-19 mRNA, PPSV23, Tdap, RZV Shingrix) + 13 paediatric
    (12 `pediatric_series` + annual paediatric influenza).
  - [`clinosim/locale/jp/immunization_schedule.yaml`](../../locale/jp/immunization_schedule.yaml)
    — MHLW 定期接種 schedule. Currently 14 entries: 3 adult
    (Influenza, COVID-19 mRNA, PPSV23) + 11 paediatric
    `pediatric_series`.
- Schedule entry shape:
  | Key | Meaning |
  |---|---|
  | `cvx` | CDC CVX code (string). |
  | `products` | Optional `[{cvx, from, until}]` (inclusive dates): the product in use on the dose date (`engine.product_cvx`; Issue #2629). US influenza / COVID-19 and JP COVID-19 (従来型 1価 CVX 208 to 2022-09-19, 2価 CVX 300 from 2022-09-20, CVX 309 from 2023-09-20; Issue #3014). `cvx` is the fallback. |
  | `min_age` | Minimum eligible age. |
  | `min_age_days` | Optional. Licensure floor in days from birth, checked on the dose date (Issue #2979: influenza 182 = 6 months). No dose, no vaccination-visit dose, no alignment onto an earlier encounter and no healthcare-calendar flu visit before it; an `annual` season month drawn before it moves to the season's first month after it. |
  | `frequency` | `"annual"`, `"once"`, `"every_n_years"`, or `"pediatric_series"`. |
  | `interval_years` | `every_n_years` only. Interval in years. |
  | `season_month` | `annual` only. Fixed month used when no `seasonal_distribution` (default 10). |
  | `seasonal_distribution` | `annual` only. `{month: weight}` for per-season month sampling. |
  | `wave_epochs` | `once` only. Epochs with `start` / `end` / `age_weight` / `monthly_curve`. |
  | `doses` | `pediatric_series` only. Per dose: `age_days_min`, `age_days_max`, `dose_number`, `coverage_by_sex` (the dose's marginal coverage — the share of children who receive it, never rising along a series; a child who received the previous drawn dose gets this one with probability `coverage_k / coverage_{k-1}` (`engine.conditional_dose_coverage`, Issue #3288), so the completed series matches the cited national coverage: US NIS-Child / kindergarten / NIS-Teen, JP 厚生労働省「定期の予防接種実施者数」); from dose 2 on, `min_interval_days` (minimum days after the previous dose; US CDC General Best Practice Guidelines Table 3-1, JP 予防接種実施規則) and optionally `min_interval_after_dose` (the earlier dose the interval counts from when it is not the previous one, e.g. JP hepatitis B dose 3: 139 days after dose 1) and `max_interval_days` (the latest the dose may come after that dose, e.g. JP Japanese encephalitis 1期初回 dose 2: 6-28 days; Issue #3006). The generator, the vaccination-visit binder and the encounter alignment all keep these rules (`engine.series_allows`). Issue #3001. A dose may set `independent_of_previous: true` with `coverage_if_previous_missed` (JP MR 第2期: one dose in the year before school for every child whatever the 第1期 history, 実施要領 第2 各論 2 (1) イ; Issue #3301): a child who missed the previous dose still draws it, from a sha256-seeded sub-RNG (the patient stream is untouched), at `coverage_if_previous_missed` (an assumed 0.5, no source); the previous-dose-given threshold is `engine.independent_dose_coverage`, which keeps the dose's marginal coverage. Its `dose_number` is the schedule position (第2期 = 2), not a count of doses received. |
  | `catch_up_max_age_days` | `pediatric_series` only, optional. Oldest age (days) at which a child behind on the series is caught up at a `catch_up` vaccination visit (Issue #3282). US: CDC Child and Adolescent Catch-up Immunization Schedule — DTaP 2555 (< 7 y; Tdap/Td from 7 y), IPV / MMR / varicella / HepB / HepA 6938 (through 18 y). JP: 予防接種法施行令 target ages — DTaP-IPV, DTaP-IPV-Hib and Japanese encephalitis 第1期 2737 (< 90 months). Absent (never caught up) where a late start changes the number of doses (Hib, PCV) or the target age has passed (rotavirus, BCG, JP hepatitis B / MR 第1期 / varicella). |
  | `birth_from` / `birth_until` | Optional, inclusive birth dates between which the entry applies (`engine.schedule_for_birth`, used by the generator and the vaccination-visit binder; Issue #3301). JP: 2024-02-01 and later births get the 5-valent DPT-IPV-Hib (`pediatric_dtap_ipv_hib`, CVX 120; 定期接種実施要領 第2 各論 1 (1): 3 primary doses at 2-7 months, 20 days apart, booster 6-18 months after) and earlier births keep 4-valent DPT-IPV + Hib, so a child's series is never split between products (実施要領 第1 総論 (15)). |
  | `available_from` | Program availability date (`YYYY-MM-DD`). |
  | `history_years` | Optional. EHR retention window (e.g. flu → 10 y). |
  | `program`, `routine_from_age` | JP only, optional (Issue #3660): `program` is `routine` (default) or `voluntary`; with `voluntary`, `routine_from_age` is the age from which the dose is routine (influenza and COVID-19: 65). `engine.vaccine_program(country, cvx, age_years)` resolves it for the FHIR Immunization reason text (定期接種 / 任意接種); the loader rejects any other value. US and every other country are `routine`. |
  | `first_season_second_dose` | `annual` only, optional: `{max_age_months, min_interval_days}` (Issue #3684; US paediatric influenza 107 = under 9 years, 28 days; ACIP: children 6 months through 8 years who need two doses). `engine.add_first_season_flu_doses`, called at the end of `bind_to_vaccination_visits_for_country` (the enricher's call; `bind_to_vaccination_visits` is it without a country), gives a child whose first completed flu dose is given under `max_age_months` — and whose licensure floor lies inside `history_years`, so no earlier dose is unknown — a second dose at least `min_interval_days` later on a clinic day of the same flu season (not after the as-of date; none left, no second dose), `dose_number` 1 and 2, a sha256 day pick with no rng draw. The interval is registered in `dose_intervals_by_cvx`, so the enricher's snapping keeps it. JP has no paediatric influenza entry and is unchanged. |
  | `administration` | How a dose is given (Issue #3005): `route` (a `codes/data/snomed-maps.yaml` route key: `IM` / `SC` / `PO` / `PERCUTANEOUS`), `dose_ml` (omitted when the label states no fixed volume, e.g. BCG) and optional `dose_ml_by_age` `[{max_age_months, ml}]` (e.g. JP Japanese encephalitis 0.25 mL under 3 years). The schedule's top-level `administration_sites` gives the SNOMED body site per route and age band (infant IM in the thigh, upper arm otherwise; no site for an oral dose). Read by `engine.vaccine_administration(country, cvx, age_months)` for the FHIR Immunization `route` / `site` / `doseQuantity`. |
  | `coverage_by_age_sex` | `{"age_band": {sex: rate}}` in [0, 1] (non-paediatric branches). |
- CVX code table:
  [`clinosim/codes/data/cvx.yaml`](../../codes/data/cvx.yaml)
  — 39 codes.
  FHIR system URI `http://hl7.org/fhir/sid/cvx`.

## Directory contents

```
clinosim/modules/immunization/
  __init__.py                     empty (see Public API note)
  engine.py                       generate_immunizations + load_schedule + helpers
  enricher.py                     POST_RECORDS enrichment (patient-scoped sub-RNG)
  visits.py                       doses given at vaccination (Z23) visits
  reference_data/
    ed_vaccine_doses.yaml         ED one-time vaccine drug -> CVX; tetanus booster reset
    vaccination_visit.yaml        duration_minutes of a synthesised vaccination visit
    vaccination_precautions.yaml  febrile_celsius: visits a routine dose is not given at
```

The module has **no `audit.py`** — country schedules live under
`clinosim/locale/` (the module's own `reference_data/` holds only the
vaccination precautions), and no
`ModuleAuditSpec` is registered. Verification lives in the tests
below.

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) under
`register_builtin_enrichers`:

- `name="immunization"`, `stage=POST_RECORDS`, `order=30`,
  `enabled=lambda c: True`.
- Runs after `nursing` (order 20) and before `family_history`
  (order 40). Because it appends `ENC-VAX-*` encounters after the
  POST_ENCOUNTER `document` enricher has run, it re-invokes
  `document_enricher` itself.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| CSV adapter | [`clinosim/modules/output/csv_adapter.py`](../output/csv_adapter.py) (`convert_cif_to_csv`) | Writes `immunizations.csv` from `record["immunizations"]`. |
| FHIR `Immunization` builder | [`clinosim/modules/output/fhir_r4/procedures/immunization.py`](../output/fhir_r4/procedures/immunization.py) | Emits one FHIR R4 `Immunization` per record; id `imm-<12hex>` derived from the structural key `{patient_id}-{index}` (kept as an identifier). `vaccineCode` = CVX + locale display, `occurrenceDateTime` = the record date, `primarySource` from the record (`false` for pre-window doses), `encounter` from `encounter_id` (emit-time keyword match as fallback), `statusReason` PATOBJ for `not-done`, `protocolApplied[0].doseNumberPositiveInt` from `dose_number`, `performer` populated from `administered_by` when non-empty, `lotNumber` from the record's `lot_number` when non-empty (generated by `engine.synthetic_lot_number`). |
| Enricher registry | [`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) `register_builtin_enrichers` | POST_RECORDS registration. |

## Testing

```bash
pytest tests/unit -k immunization -q         # engine
pytest tests/integration -k immunization -q  # enricher + FHIR emission
```

Individual files:

- [`tests/unit/test_immunization.py`](../../../tests/unit/test_immunization.py)
  — engine sampling / lot-number determinism.
- [`tests/integration/test_immunization_enricher.py`](../../../tests/integration/test_immunization_enricher.py)
  — enricher determinism + nurse-roster assignment.
- [`tests/integration/test_fhir_immunization.py`](../../../tests/integration/test_fhir_immunization.py)
  — `Immunization` emission end-to-end.
- [`tests/unit/modules/immunization/`](../../../tests/unit/modules/immunization/)
  — encounter alignment, companion vaccination encounter, same-day
  merge, document dispatch, well-child bundling, US paediatric
  schedule, pregnancy Tdap, doses given at vaccination visits.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
