# `clinosim.modules.staff` — hospital staff roster generation + event assignment

## Purpose

Generates the practitioner roster (physicians, nurses, lab technicians,
radiologists, pharmacists, and allied-health roles) for a simulated
hospital scaled to its department layout + bed count, and dispatches
per-encounter staff for clinical events (admission, rounds, discharge,
lab collection, lab result, imaging interpretation, medication
administration). The resulting `StaffRoster` is the single source of
staff identities the simulator hands to encounter builders + FHIR
`Practitioner` / `PractitionerRole` emission.

## Scope

- **In scope**: roster construction from `hospital_config`
  (`available_departments`, `wards`, `resource_capacity.inpatient_beds`),
  per-department physician count with bed-scaled formulae for internal
  medicine / general surgery / emergency medicine (see
  [`_staff_thresholds.py`](_staff_thresholds.py) for the exact
  divisor + minimum tables), per-ward nurse count, ED / OPD nurse
  pool, lab tech / radiologist / pharmacist fixed counts, extra
  allied-health roles (C5-25 Chain 3 for β-JP-1 CareTeam expansion),
  country-appropriate name (JP kanji + kana pair) and phone / email
  generation, event-type → staff-role dispatch in `assign_staff`.
- **In scope (fallback IDs)**: `FALLBACK_PHYSICIAN_ID = "DR-001"`,
  `FALLBACK_NURSE_ID = "NS-001"`, `FALLBACK_TECH_ID = "TECH-001"`
  (Issue #562) — grep-alignable sentinels used ONLY when the roster
  is empty (test fixtures, smoke runs). Production paths always have
  a real ID by the time the fallback `dict.get` fires.
- **Out of scope**: patient identifiers
  ([`clinosim.modules.identity`](../identity/README.md)), hospital /
  ward / bed inventory
  ([`clinosim.modules.facility`](../facility/README.md)), nursing
  assessment scaffolding
  ([`clinosim.modules.nursing`](../nursing/README.md)), primary-nurse
  assignment on inpatient encounters (that runs in
  [`clinosim.modules.nursing.engine.nursing_enricher`](../nursing/README.md)
  and picks from THIS roster), FHIR emission
  ([`clinosim.modules.output`](../output/README.md)).

## Public API

```python
from clinosim.modules.staff import (
    StaffMember,                       # dataclass (re-exported from types.staff)
    StaffRoster,                       # dataclass (re-exported from types.staff)
    generate_roster,                   # (hospital_scale, country, rng, hospital_config=None) -> StaffRoster
    assign_staff,                      # (event_type, department, roster, rng) -> {role_in_event: staff_id}
)
from clinosim.modules.staff.engine import (
    FALLBACK_PHYSICIAN_ID,             # "DR-001"
    FALLBACK_NURSE_ID,                 # "NS-001"
    FALLBACK_TECH_ID,                  # "TECH-001"
)
```

`assign_staff` uses `match event_type`:

- `"admission" | "rounds" | "discharge"` → attending physician
  (specialty-matched with graceful fallback) + primary nurse.
- `"lab_collection" | "lab_result"` → performing technician.
- `"imaging_interpretation"` → interpreting radiologist.
- `"medication_administration"` → administering nurse in the ordering
  department.

`StaffRoster.get_by_role(role, department=None)` is the primary
lookup shape the module uses internally.

## Determinism

- **No sub-seed offset in `ENRICHER_SEED_OFFSETS`.** This module does
  not register an enricher — it is called imperatively from the
  encounter simulators, which own the RNG they pass in.
- Caller responsibility: `generate_roster` and `assign_staff` are
  pure with respect to the `rng` argument. The encounter simulators
  (`inpatient.py`, `outpatient.py`, `lab_pipeline.py`) each derive
  their own sub-RNG (e.g. per-encounter seed for admission
  assignment) before calling `assign_staff`, so per-event dispatch
  is reproducible and does not disturb the main clinical stream.

## Dependencies

- `clinosim.modules._shared` — `is_jp` (country dispatch for phone
  format and JP kana names).
- `clinosim.modules.staff._staff_thresholds` — the entire threshold
  table (divisors, minima, counts, qualification-year ranges, phone
  digit ranges, extra staff roster).
- `clinosim.locale.loader` — `load_names(country)` for surname /
  given-name pools.
- `clinosim.types.staff` — `StaffMember`, `StaffRoster`.
- `numpy` — `np.random.Generator`.
- No dependency on any other `clinosim.modules.*`.

## Constants and configuration

- **Threshold table**: [`_staff_thresholds.py`](_staff_thresholds.py)
  — all magic numbers named + docstring-annotated (Issue #562 sweep).
  Includes:
  - Physician-per-bed divisors (`DOCTORS_PER_INTERNAL_MED_BED_DIVISOR`,
    `DOCTORS_PER_SURGERY_BED_DIVISOR`,
    `DOCTORS_PER_ED_BED_DIVISOR`) and minima
    (`MIN_INTERNAL_MED_PHYSICIANS`, `MIN_SURGERY_PHYSICIANS`,
    `MIN_ED_PHYSICIANS`); `DOCTORS_PER_DEPT_FIXED` for other departments.
  - Nursing scaling: `NURSES_PER_BED_DIVISOR`, `NURSES_PER_BED_BUFFER`,
    `NURSES_PER_WARD_MIN`, `MIN_BEDS_PER_WARD`, `FALLBACK_BEDS_PER_WARD`,
    `ED_OPD_NURSES_PER_AREA`.
  - Ancillary role counts: `LAB_TECH_COUNT`, `RADIOLOGIST_COUNT`,
    `PHARMACIST_COUNT`.
  - Qualification-year ranges per role
    (`{PHYSICIAN,NURSE,PHARMACIST,RADIOLOGIST,TECH,ALLIED_HEALTH}_QUALIFICATION_YEAR_{START,END_EXCLUSIVE}`).
  - Sex ratios: `PHYSICIAN_MALE_RATIO`, `NURSE_FEMALE_RATIO`.
  - Phone digit ranges (`JP_PHONE_*`, `US_PHONE_*`).
  - `STAFF_ID_FALLBACK_{MIN,MAX_EXCLUSIVE}` for the missing-name
    fallback path (`Staff-{n}` id when the locale name pool is
    empty).
  - `EXTRA_STAFF_ROLES` — tuple of
    `(role, id_prefix, dept, count, female_ratio)` for the C5-25
    Chain 3 allied-health expansion.
- **Department → staff-ID prefix map** (`_DEPT_PREFIX` in
  `engine.py`): `internal_medicine → "IM"`, `cardiology → "CA"`,
  `pulmonology → "PU"`, `gastroenterology → "GI"`, `nephrology → "NE"`,
  `endocrinology → "EN"`, `neurology → "NR"`,
  `general_surgery → "GS"`, `orthopedics → "OR"`,
  `neurosurgery → "NS"`, `trauma_surgery → "TS"`,
  `emergency_medicine → "EM"`, `primary_care → "PC"`,
  `obstetrics_gynecology → "OB"`, `pediatrics → "PD"`. Unknown
  departments fall back to `dept[:2].upper()`.
- **JP name pair** (`_generate_name_pair`): returns `(kanji, kana)`
  so `StaffMember.name_phonetic` can populate the JP Core Practitioner
  `HumanName` SYL entry (C2-19 continuation). Non-JP returns
  `(name, "")`.

## Directory contents

```
clinosim/modules/staff/
  __init__.py                     public API (StaffMember, StaffRoster, generate_roster, assign_staff)
  engine.py                       roster generation + assign_staff dispatch + name / phone / email helpers
  _staff_thresholds.py            named threshold constants (Issue #562)
  SPEC.md                         v1+ design reference (roles, lifecycle, credentials — not runtime data)
```

The module has **no `enricher.py`, no `audit.py`, no `reference_data/`**.

## Enricher wiring

Not applicable — this module is not registered with
`register_builtin_enrichers` and has no seed offset in
`ENRICHER_SEED_OFFSETS`. The roster is built once per run by the
CLI / encounter simulator, and `assign_staff` is called imperatively
from the encounter code paths listed below.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Encounter builder (inpatient) | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) (`~L45`, `~L260`) | Calls `assign_staff("admission", department, roster, rng)` to pick attending + primary nurse. |
| Encounter builder (outpatient) | [`clinosim/simulator/outpatient.py`](../../simulator/outpatient.py) (`~L21`, `~L109`, `~L161`, `~L177`) | Rounds / medication administration / lab collection assignment. |
| Lab pipeline | [`clinosim/simulator/lab_pipeline.py`](../../simulator/lab_pipeline.py) (`~L51`, `~L113`, `~L131`, `~L166`) | `assign_staff("lab_result", …)` for performing / result technician, uses `FALLBACK_TECH_ID` when the roster is empty. |
| CLI single-encounter driver | [`clinosim/simulator/cli_test_encounter.py`](../../simulator/cli_test_encounter.py) (`~L16`, `~L80`) | Calls `generate_roster("medium", country, rng)` for smoke runs. |
| Nursing primary-nurse enricher | [`clinosim/modules/nursing/engine.py`](../nursing/engine.py) | Picks primary nurse via `roster.get_by_role("nurse")` (transitive consumer of the roster this module produces). |
| FHIR `Practitioner` + `PractitionerRole` builders | [`clinosim/modules/output/fhir_r4/`](../output/fhir_r4/) | Emit `StaffMember` fields as `Practitioner` (name / kana / telecom / qualification) and `PractitionerRole` (department / specialty). |

## Testing

```bash
pytest tests/unit -k staff -q      # types + fallback constants
```

Individual files:

- [`tests/unit/test_staff_types.py`](../../../tests/unit/test_staff_types.py)
  — `StaffMember` / `StaffRoster` dataclass shape.
- [`tests/unit/modules/test_staff_fallback_constants.py`](../../../tests/unit/modules/test_staff_fallback_constants.py)
  — `FALLBACK_*` constants + module-level naming (Issue #562).

Coverage gap: roster generation + `assign_staff` dispatch have no
dedicated unit tests today; they are exercised transitively by
integration + e2e tests. Adding a focused unit test file for
`generate_roster` (scale invariants, ID uniqueness, extra-role
inclusion) and `assign_staff` (per-event-type dispatch, empty-roster
fallback) is a low-cost follow-up.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
