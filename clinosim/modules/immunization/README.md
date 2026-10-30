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
  coverage lookup (per-dose `coverage_by_sex` for paediatric series);
  occurrence-date placement (annual → month drawn from
  `seasonal_distribution`, else fixed `season_month`; every-n-years →
  step of `interval_years` from the eligible start; once → month drawn
  from `wave_epochs` when declared, else uniform in the eligible
  window; pediatric_series → per-dose `[age_days_min, age_days_max]`
  window snapped to the canonical well-child visit age, a missed dose
  discontinuing the rest of the series); US maternal Tdap (CVX 115,
  27–36 weeks of each non-aborted pregnancy, coverage 0.78);
  refusal-documentation emission at rate
  `IMMUNIZATION_NOT_DONE_RECORDING_RATE`; binding doses to existing
  encounters and synthesising a companion vaccination encounter for
  in-window orphans (see *Encounter binding*); synthetic
  lot number generation (structural placeholder, NOT an authoritative
  batch); Feb 29 birthday clamping to Feb 28 in non-leap years;
  optional `history_years` retention window (e.g. flu → 10 y).
- **Out of scope**: paediatric immunization catch-up modelling,
  reaction / adverse-event generation, scheduling immunization visits
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
their records, then `_align_to_encounters` (deterministic, no rng):

1. binds a dose dated inside an inpatient stay to that stay and keeps
   its date (e.g. the hepatitis B birth dose in the nursery);
2. otherwise snaps the dose to the nearest outpatient encounter within
   ±60 days and records its `encounter_id`.

A dose still unbound and dated before the simulation window start
(`config.time_range[0]`) is marked `primary_source=False` and left
unlinked. An in-window orphan gets a synthesised outpatient
`ENC-VAX-*` encounter (department `primary_care`, admission diagnosis
`Z23`, attending picked deterministically from the primary-care
physician roster), hosted once per patient. When any `ENC-VAX-*`
encounter exists, `document.engine.document_enricher` is re-invoked so
those encounters get their document stubs.

## Dependencies

- `clinosim.modules._shared` — `is_us` / `is_jp`,
  `get_attr_or_key` / `set_attr_or_key`.
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.types.encounter` — `ImmunizationRecord` (imported
  lazily inside the engine functions); `Encounter` /
  `EncounterStatus` / `EncounterType` for companion encounters.
- `clinosim.codes` (indirect, via the FHIR builder) — CVX display
  lookup.
- `numpy` — `np.random.Generator` for coverage sampling.
- `hashlib.sha256` — via `_det_hash`, for lot-number determinism.

The only other module dependency is a lazy import of
`clinosim.modules.document.engine.document_enricher` for companion
encounter documents.

## Constants and configuration

- Module-level constant (in `engine.py`):
  - `IMMUNIZATION_NOT_DONE_RECORDING_RATE = 0.02` — per-scheduled-dose
    probability of emitting an explicit `status="not-done"` record on
    a failed coverage draw. Represents documented refusals /
    deferrals, distinct from silent no-shows. Applied in the
    `annual`, `every_n_years` and `pediatric_series` branches and to
    maternal Tdap; the `once` branch emits no `not-done` record.
- Locale schedules (no `reference_data/` directory in this module):
  - [`clinosim/locale/us/immunization_schedule.yaml`](../../locale/us/immunization_schedule.yaml)
    — CDC ACIP schedule. Currently 18 entries: 5 adult (Influenza,
    COVID-19 mRNA, PPSV23, Tdap, RZV Shingrix) + 13 paediatric
    (12 `pediatric_series` + annual paediatric influenza).
  - [`clinosim/locale/jp/immunization_schedule.yaml`](../../locale/jp/immunization_schedule.yaml)
    — MHLW 定期接種 schedule. Currently 13 entries: 3 adult
    (Influenza, COVID-19 mRNA, PPSV23) + 10 paediatric
    `pediatric_series`.
- Schedule entry shape:
  | Key | Meaning |
  |---|---|
  | `cvx` | CDC CVX code (string). |
  | `min_age` | Minimum eligible age. |
  | `frequency` | `"annual"`, `"once"`, `"every_n_years"`, or `"pediatric_series"`. |
  | `interval_years` | `every_n_years` only. Interval in years. |
  | `season_month` | `annual` only. Fixed month used when no `seasonal_distribution` (default 10). |
  | `seasonal_distribution` | `annual` only. `{month: weight}` for per-season month sampling. |
  | `wave_epochs` | `once` only. Epochs with `start` / `end` / `age_weight` / `monthly_curve`. |
  | `doses` | `pediatric_series` only. Per dose: `age_days_min`, `age_days_max`, `dose_number`, `coverage_by_sex`. |
  | `available_from` | Program availability date (`YYYY-MM-DD`). |
  | `history_years` | Optional. EHR retention window (e.g. flu → 10 y). |
  | `coverage_by_age_sex` | `{"age_band": {sex: rate}}` in [0, 1] (non-paediatric branches). |
  | `program_type` | Paediatric entries (`mandatory` / `elective`); informational, not read by the engine. |
- CVX code table:
  [`clinosim/codes/data/cvx.yaml`](../../codes/data/cvx.yaml)
  — 34 codes.
  FHIR system URI `http://hl7.org/fhir/sid/cvx`.

## Directory contents

```
clinosim/modules/immunization/
  __init__.py                     empty (see Public API note)
  engine.py                       generate_immunizations + load_schedule + helpers
  enricher.py                     POST_RECORDS enrichment (patient-scoped sub-RNG)
```

The module has **no `reference_data/` directory and no `audit.py`** —
country data lives under `clinosim/locale/`, and no
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
| CSV adapter | [`clinosim/modules/output/csv_adapter.py`](../output/csv_adapter.py) (`~L327`, `~L417`) | Writes `immunizations.csv` from `record["immunizations"]`. |
| FHIR `Immunization` builder | [`clinosim/modules/output/fhir_r4/procedures/immunization.py`](../output/fhir_r4/procedures/immunization.py) | Emits one FHIR R4 `Immunization` per record; id `imm-<12hex>` derived from the structural key `{patient_id}-{index}` (kept as an identifier). `vaccineCode` = CVX + locale display, `occurrenceDateTime` = the record date, `primarySource` from the record (`false` for pre-window doses), `encounter` from `encounter_id` (emit-time keyword match as fallback), `statusReason` PATOBJ for `not-done`, `protocolApplied[0].doseNumberPositiveInt` from `dose_number`, `performer` populated from `administered_by` when non-empty, `lotNumber` from `_synthetic_lot` when present. |
| Enricher registry | [`clinosim/simulator/enrichers.py:241`](../../simulator/enrichers.py) | POST_RECORDS registration. |

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
  schedule, pregnancy Tdap.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
