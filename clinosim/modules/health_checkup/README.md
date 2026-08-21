# `clinosim.modules.health_checkup` — JP employer-provided health checkup (opt-in)

## Purpose

Opt-in POST_RECORDS enricher that adds Japanese employer-provided
annual health-checkup encounters (**事業者健診**, mandated by the
Industrial Safety and Health Act 労働安全衛生法) to a JP cohort.
Selects a deterministic 30 % subset of adult patients (age ≥ 40) via
SHA-256 hash on `patient_id`, emits one `CHECKUP` encounter per year
anchored before the simulation snapshot, five statutory measurements
(BMI, systolic BP, diastolic BP, HbA1c, LDL cholesterol), and a
`HEALTH_CHECKUP_REPORT` `ClinicalDocument` stub whose narrative
[`document.narrative`](../document/narrative/README.md) fills in
during Stage 2 (AD-65 two-pass CIF).

Default OFF — the module only fires when
`SimulatorConfig.modules["health_checkup"] == True` and `country == "JP"`.
Off keeps the simulator's default acute-hospital shape unchanged.

## Scope

- **In scope**: patient subset selection (age gate + deterministic
  hash), snapshot-anchored checkup-date pick (approximately 90 days
  before snapshot, so multi-year snapshots produce multiple
  checkups), age-tier checkup-type dispatch
  (40-64 → 事業者健診, 65-74 → 特定健診, 75+ → 広域連合健診 —
  MVP single-tier dispatch; insurance-based refinement deferred to a
  future sub-PR), CHECKUP encounter build (single-day admission +
  discharge), five statutory measurements with per-analyte
  measurement noise, per-analyte interpretation (normal / high) with
  reference-range strings, `HEALTH_CHECKUP_REPORT`
  `ClinicalDocument` stub with `narrative=None` for Stage 2 fill.
- **Out of scope**: narrative content — populated by
  [`clinosim.modules.document.narrative`](../document/narrative/README.md)
  post-simulation (AD-65 Stage 2); FHIR Composition + section text
  emission ([`clinosim.modules.output.fhir_r4.documents`](../output/fhir_r4/documents/README.md));
  insurance-based checkup-type refinement (future sub-PR);
  non-JP cohorts.

## Public API

```python
from clinosim.modules.health_checkup import (
    enrich_health_checkup,          # POST_RECORDS enricher entry
    HEALTH_CHECKUP_SUBSET_RATE,     # 0.30 (tunable subset fraction)
)
```

Internal helpers (in `engine.py`) — not part of the public surface
but useful for tests: `_patient_selected(patient_id)`,
`_pick_checkup_type(age)`, `_pick_checkup_date(snapshot_date)`,
`_derive_checkup_values(patient, rng)`, `_interp_for(loinc, value)`,
`_build_checkup_encounter`, `_build_checkup_lab_results`,
`_build_checkup_document_stub`. `HEALTH_CHECKUP_MIN_AGE = 40` and the
age-tier thresholds (`CHECKUP_TYPE_SPECIFIC_AGE_MIN = 65`,
`CHECKUP_TYPE_REGIONAL_UNION_AGE_MIN = 75`) live in
[`_checkup_thresholds.py`](_checkup_thresholds.py).

## Determinism

- **Patient selection uses SHA-256, not the RNG**. `_patient_selected`
  hashes `patient_id`, converts the first 8 bytes to a fraction, and
  admits patients below `HEALTH_CHECKUP_SUBSET_RATE`. No RNG is
  consumed for selection — the same patient is always selected /
  skipped across runs, even if unrelated modules change.
- Sub-seed offset `0x4843` (`"HC"`) is registered in
  [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["health_checkup"]` and is used for
  per-patient measurement noise on the five checkup labs; the main
  population RNG stream is not consumed (AD-16).
- The checkup date is a deterministic offset from the snapshot date
  (~90 days before), not a random draw.

## Dependencies

- `clinosim.modules._shared` — `is_jp`, `get_attr_or_key`.
- `clinosim.modules.health_checkup._checkup_thresholds` — every
  physiologic bound, measurement-noise SD, interpretation cutoff,
  reference range, and age tier used by the value-derivation
  pipeline (Issue #637 sweep — every scalar in `engine.py` is
  lifted here).
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.types.clinical` — `ClinicalDocument`.
- `clinosim.types.encounter` — `Encounter`, `EncounterStatus`,
  `EncounterType`, `Order`, `OrderResult`, `OrderStatus`, `OrderType`.
- `hashlib.sha256` — patient selection.
- `numpy` — `np.random.Generator` for measurement noise.
- No dependency on any other `clinosim.modules.*`.

## Constants and configuration

- Module-level constants (`engine.py`):
  - `HEALTH_CHECKUP_SUBSET_RATE = 0.30` — deterministic subset
    fraction. MVP calibration; future sub-PR may narrow to patients
    with `employment_status` = employed.
  - `HEALTH_CHECKUP_MIN_AGE = 40` — minimum age for eligibility.
- Age-tier dispatch (`_pick_checkup_type`):
  - Ages 40-64 → `"occupational"` (事業者健診, 労安衛法定).
  - Ages 65-74 → `"specific"` (特定健診, 40-74 保険 base).
  - Ages 75+ → `"regional_union"` (広域連合健診, 後期高齢者医療).
- Threshold table: [`_checkup_thresholds.py`](_checkup_thresholds.py)
  — per-analyte physiologic min / max, measurement-noise SDs,
  reference-range strings, high-threshold cutoffs, DM- vs non-DM
  HbA1c branches, sex-and-age LDL base + scaling, statin reduction
  factor, dyslipidemia lift, plus the two age-tier thresholds above.
- Chief-complaint text per checkup type
  (`_CHECKUP_TYPE_CHIEF_COMPLAINT`): `occupational → "事業者健診"`,
  `specific → "特定健診"`, `regional_union → "広域連合健診"`.

## Directory contents

```
clinosim/modules/health_checkup/
  __init__.py                     re-exports enrich_health_checkup + HEALTH_CHECKUP_SUBSET_RATE
  engine.py                       enricher + patient selection + value derivation + record builders
  _checkup_thresholds.py          named threshold constants (Issue #637)
```

The module has **no `reference_data/`, no `audit.py`, no
`enricher.py`** — the enricher entry point is `enrich_health_checkup`
in `engine.py` and reference values are constants, not YAML.

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`~L350-380`) under `register_builtin_enrichers`:

- `name="health_checkup"`, `stage=POST_RECORDS`, `order=70`.
- `enabled=_health_checkup_enabled` — requires
  `is_jp(config.country)` AND `config.module_enabled("health_checkup")`.
  `None`-safe fallback (mirrors the `care_level` pattern) so
  registry-helper tests with `ctx.config=None` still pass.
- Runs after every other POST_RECORDS enricher (nursing 20 /
  immunization 30 / family_history 40 / code_status 50 /
  care_level 60), so the CHECKUP encounter cannot shift the RNG
  stream those earlier enrichers depend on.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py:373`](../../simulator/enrichers.py) | POST_RECORDS order=70 registration. |
| Encounter type mapping | [`clinosim/modules/output/fhir_r4/encounters/encounter.py`](../output/fhir_r4/encounters/encounter.py) | Maps `EncounterType.CHECKUP` → JP-eCheckup `class` + `type`. |
| FHIR DocumentReference builder | [`clinosim/modules/output/fhir_r4/documents/document_reference_checkup.py`](../output/fhir_r4/documents/document_reference_checkup.py) | Emits the `HEALTH_CHECKUP_REPORT` stub as `DocumentReference` (or Composition once narrative is populated). |
| Narrative Stage 2 | [`clinosim/modules/document/narrative/passes.py`](../document/narrative/passes.py) | Fills the stub's `narrative.sections` with the per-value interpretation + Q4-summary text. |

## Testing

```bash
pytest tests/unit -k "health_checkup or checkup" -q
```

Individual files:

- [`tests/unit/test_health_checkup_enricher.py`](../../../tests/unit/test_health_checkup_enricher.py)
  — enricher gating (opt-in, JP-only, age ≥ 40), subset selection
  determinism, five-measurement emission, snapshot-anchored date.
- [`tests/unit/test_health_checkup_personalization.py`](../../../tests/unit/test_health_checkup_personalization.py)
  — per-patient value derivation (DM/non-DM branching, sex/age LDL
  scaling, dyslipidemia lift, statin reduction).
- [`tests/unit/test_checkup_renderer_personalization.py`](../../../tests/unit/test_checkup_renderer_personalization.py)
  — narrative-side rendering integration point.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
