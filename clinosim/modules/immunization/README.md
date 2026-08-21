# `clinosim.modules.immunization` — adult immunization-history synthesis

## Purpose

Generates each patient's adult vaccine history from a per-country
CVX-coded schedule (eligibility age, program availability date,
frequency, season, EHR retention window, age × sex coverage) and
writes the result to `CIFPatientRecord.immunizations`. Downstream FHIR
and CSV adapters emit `Immunization` resources and an
`immunizations.csv` file. A small fraction of scheduled doses are
recorded as explicit refusals (`status="not-done"`) to mirror real
EHR documentation.

## Scope

- **In scope**: sampling `annual`, `every_n_years`, or `once`
  vaccinations per schedule entry; per-age × sex coverage lookup;
  deterministic occurrence-date placement (annual → `season_month`;
  every-n-years → step of `interval_years` from the eligible start;
  once → uniform in the eligible window); refusal-documentation
  emission at rate `IMMUNIZATION_NOT_DONE_RECORDING_RATE`; synthetic
  lot number generation (structural placeholder, NOT an authoritative
  batch); Feb 29 birthday clamping to Feb 28 in non-leap years;
  optional `history_years` retention window (e.g. flu → 10 y).
- **Out of scope**: paediatric immunization catch-up modelling,
  reaction / adverse-event generation, immunization-driven encounter
  creation (immunization visits are not first-class encounters),
  FHIR / CSV serialisation
  ([`clinosim.modules.output`](../output/README.md)), CVX display
  text ([`clinosim/codes/data/cvx.yaml`](../../codes/data/cvx.yaml)).

## Public API

`__init__.py` is empty; consumers import the two building blocks
directly:

```python
from clinosim.modules.immunization.engine import (
    generate_immunizations,          # (patient, schedule, as_of, rng, nurse_ids=None)
                                     #   -> list[ImmunizationRecord] (sorted by date)
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
  patient RNG stream is not consumed.
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

## Snapshot (AD-32)

`as_of = ctx.config.snapshot_date` when set, otherwise the latest
encounter admission date on the record. `occurrence_date > as_of` is
skipped, so partial data during in-progress snapshots is not
back-dated.

## Dependencies

- `clinosim.modules._shared` — `is_us` / `is_jp`,
  `get_attr_or_key` / `set_attr_or_key`.
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.types.encounter` — `ImmunizationRecord` (imported
  lazily inside `generate_immunizations`).
- `clinosim.codes` (indirect, via the FHIR builder) — CVX display
  lookup.
- `numpy` — `np.random.Generator` for coverage sampling.
- `hashlib.sha256` — via `_det_hash`, for lot-number determinism.

No dependency on any other `clinosim.modules.*`.

## Constants and configuration

- Module-level constant (in `engine.py`):
  - `IMMUNIZATION_NOT_DONE_RECORDING_RATE = 0.02` — per-scheduled-dose
    probability of emitting an explicit `status="not-done"` record on
    a failed coverage draw. Represents documented refusals /
    deferrals, distinct from silent no-shows. Applied uniformly
    across all three frequency branches.
- Locale schedules (no `reference_data/` directory in this module):
  - [`clinosim/locale/us/immunization_schedule.yaml`](../../locale/us/immunization_schedule.yaml)
    — CDC ACIP adult schedule. Currently 5 vaccines (Influenza,
    COVID-19 mRNA, PPSV23, Tdap, RZV Shingrix).
  - [`clinosim/locale/jp/immunization_schedule.yaml`](../../locale/jp/immunization_schedule.yaml)
    — MHLW 定期接種 schedule. Currently 3 vaccines (Influenza,
    COVID-19 mRNA, PPSV23).
- Schedule entry shape:
  | Key | Meaning |
  |---|---|
  | `cvx` | CDC CVX code (string). |
  | `min_age` | Minimum eligible age. |
  | `frequency` | `"annual"`, `"once"`, or `"every_n_years"`. |
  | `interval_years` | `every_n_years` only. Interval in years. |
  | `season_month` | `annual` only. Month integer for placement. |
  | `available_from` | Program availability date (`YYYY-MM-DD`). |
  | `history_years` | Optional. EHR retention window (e.g. flu → 10 y). |
  | `coverage_by_age_sex` | `{"age_band": {sex: rate}}` in [0, 1]. |
- CVX code table:
  [`clinosim/codes/data/cvx.yaml`](../../codes/data/cvx.yaml)
  — 10 codes cross-checked against the CDC IIS CVX list (2026-06).
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
  (order 40).

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| CSV adapter | [`clinosim/modules/output/csv_adapter.py`](../output/csv_adapter.py) (`~L327`, `~L417`) | Writes `immunizations.csv` from `record["immunizations"]`. |
| FHIR `Immunization` builder | [`clinosim/modules/output/fhir_r4/procedures/immunization.py`](../output/fhir_r4/procedures/immunization.py) | Emits one FHIR R4 `Immunization` per record; ids `imm-{patient_id}-{index}`. `vaccineCode` = CVX + locale display, `occurrenceDateTime` = the record date, `primarySource = true`, `performer` populated from `administered_by` when non-empty, `lotNumber` from `_synthetic_lot` when present. |
| Enricher registry | [`clinosim/simulator/enrichers.py:162`](../../simulator/enrichers.py) | POST_RECORDS registration. |

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

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
