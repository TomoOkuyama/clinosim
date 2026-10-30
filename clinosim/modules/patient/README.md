# `clinosim.modules.patient` — Layer-1 person → Layer-2 patient activation

## Purpose

Promotes a Layer-1 `PersonRecord` (from
[`clinosim.modules.population`](../population/README.md)) into a
Layer-2 `PatientProfile` — attaches physiological reserves (renal /
hepatic / cardiac / immune / drug-metabolism), baseline vitals
(HR / SBP / DBP / RR / SpO₂ / temperature) with age + sex scaling,
chronic-condition activation with per-condition stage sampling
(`"CKD G3a"`, `"NYHA III"`, `"GOLD 2"`, …) and severity scoring
that the physiology engine reads, home-medication assembly by
disease profile, insurance selection, and locale-ordered display
names (family-first for JP) plus a sampled emergency contact. The
simulator activates each person once per `(person_id, as_of_year)`
cache key — the returned profile is what every downstream encounter
simulator consumes.

## Scope

- **In scope**: `activate_patient(person, rng, demo, as_of_year=None)` orchestrator,
  height + weight (with age-based shrinkage past 60),
  `PatientPhysiologicalProfile` fields (immune / metabolism / renal /
  cardiac / hepatic reserves with `AGE_PENALTY_*` scaling),
  age-and-sex scaled baseline vitals (all four BP / HR / RR / SpO₂
  / temperature), delirium-risk beta parameters (with elderly +
  dementia premium), chronic-condition activation with `_generate_stage`
  weighted stage sampling and `STAGE_SEVERITY` score lookup
  (Issue #637 PR-D refactor), home-medication derivation from the
  disease profile, insurance sampling per country / age, display-name
  ordering + emergency-contact name sampling. Also a deterministic
  `create_test_patient()` fixture in `test_patient.py`.
- **Out of scope**: patient *generation* (belongs to
  [`clinosim.modules.population`](../population/README.md)); disease
  protocol definitions
  ([`clinosim.modules.disease`](../disease/README.md)); physiology
  state advance ([`clinosim.modules.physiology`](../physiology/README.md));
  encounter simulation ([`clinosim.simulator`](../../simulator/));
  chronic-medication catalogue
  ([`clinosim.locale`](../../locale/) `chronic_medications.yaml`).

## Public API

`__init__.py` is empty; consumers import the entry points directly:

```python
from clinosim.modules.patient.activator import activate_patient
# (person: PersonRecord, rng: np.random.Generator, demo: dict,
#  as_of_year: int | None = None) -> PatientProfile

from clinosim.modules.patient.test_patient import create_test_patient
# () -> PatientProfile  (deterministic 72-year-old JP female with HT + T2DM)
```

The stage / severity tables in `_severity_activation.py` are imported
into `activator.py`'s namespace (no `__all__`), so callers that need
them can import from either module:

```python
from clinosim.modules.patient.activator import (
    STAGE_SEVERITY,           # {condition_code: {stage_text: severity_score in [0.0, 1.0]}}
    # …stage-weight tuples per chronic-condition ICD…
)
```

## Determinism

- **No sub-seed offset in `ENRICHER_SEED_OFFSETS`**. This module is
  invoked on demand by the simulator with an explicit `rng`
  argument, so per-patient determinism is the caller's contract.
  `simulator/_setup.py::_activate_cached_person` caches profiles
  keyed by `(person_id, as_of_year)` and activates on a miss with
  `derive_phase_rng(master_seed, PHASE_INPATIENT_SIM,
  "activate|<person_id>")`, so activation is exactly-once per key and
  independent of encounter order.
- Chronic-condition stage sampling uses `rng.choice(p=…)` with weight
  vectors validated to sum to 1.0 at import (see
  `_severity_activation.py`); swapping the previously-inline literals
  for the named tuples is byte-diff clean.
- Home-medication attachment (`_derive_home_medications`) does not
  draw from the caller's `rng`: it uses a per-patient sub-RNG seeded
  by `seeding.chronic_medication_seed(patient_id)` (and
  `chemotherapy_regimen_seed(patient_id, code)` for chemo regimens),
  so it is deterministic given (patient, conditions, country, age).
- **Chronic-continuation carryforward (v0.5.x fix)**: home-medication
  items sourced from a disease-YAML `continue_at_discharge` block
  (lifelong secondary-prevention drugs: anticoagulant, statin,
  antihypertensive, antiplatelet) survive across encounters. The
  fix lives in
  [`clinosim/simulator/discharge_rx.py`](../../simulator/discharge_rx.py)
  (`_append_item(chronic_continuation=True)` defaults to 28 days) and
  [`clinosim/simulator/helpers.py`](../../simulator/helpers.py)
  (`_deactivate_to_layer1` acute filter now guards `0 < d <= 14`
  so `duration_days=0` — the disease-YAML "long-term / unspecified"
  marker used by `atrial_fibrillation_rvr.yaml` etc. — falls through
  as chronic). Regression tests:
  `test_continue_at_discharge_items_default_to_28_day_chronic_duration`,
  `test_duration_days_zero_is_chronic_and_carries_forward`,
  `test_duration_days_seven_is_acute_and_dropped`,
  `test_anticoag_from_admission1_carries_forward_to_admission2_home_meds`.
- **Newborn Patient generation**: when a delivery fires, a paired
  newborn `PatientProfile` is built by
  [`clinosim/simulator/perinatal.py`](../../simulator/perinatal.py)
  (`_build_newborn_patient`), not by `activate_patient`: id
  `"<mother_id>-BABY"` (`"<mother_id>-<N>-BABY"` for later births),
  household and family name inherited from the mother, sex sampled via
  a per-mother sub-RNG, `birthDate` = the delivery date, neonatal
  baseline vitals from `perinatal.yaml`. The delivery returns two
  `CIFPatientRecord`s (mother + newborn) linked via `Encounter.partOf`
  on the newborn side. The newborn is then registered into the
  population via `population/newborn.py::register_newborn` and is
  enrolled (`enrolled_from`) from the day after birth-stay discharge,
  after which later encounters activate it through the normal cache. See
  [`docs/reference/oncology-obstetric-service-lines.md`](../../../docs/reference/oncology-obstetric-service-lines.md).

## Dependencies

- `clinosim.modules._shared` — `is_jp`, `normalize_probabilities`,
  `resolve_lang`.
- `clinosim.modules.patient._patient_activator_thresholds` — 586 LOC
  of named baseline / reserve / delirium / chronic-condition
  thresholds (Issue #637 sweep).
- `clinosim.modules.patient._severity_activation` — per-condition
  stage weight vectors + `STAGE_SEVERITY` score table.
- `clinosim.modules.longitudinal.engine` — `state_at` (lazy import;
  diabetes `HbA1c x.x%` stage text and engine-owned chronic stages
  are read from `person.longitudinal_history`).
- `clinosim.modules.population.engine` — `PersonRecord` +
  `_sample_given_name` (emergency-contact name sampling) and
  `pick_active_chemo_regimen` (lazy).
- `clinosim.modules.population._pediatric_anthropometry` —
  growth-chart height parameters for the pediatric branch.
- `clinosim.locale.loader` — `load_names(country)` (emergency-contact
  given names), `load_chronic_medications`, `load_chemo_regimens`.
- `clinosim.seeding` — `chronic_medication_seed`,
  `chemotherapy_regimen_seed`.
- `clinosim.modules.drug_safety`, `clinosim.codes.drugs` (lazy) —
  home-medication safety check and drug resolution.
- `clinosim.types.patient` — `PatientProfile`,
  `PatientPhysiologicalProfile`, `BaselineVitals`, `HomeMedication`,
  `ChronicCondition`, `PersonName`.
- `numpy` — `np.random.Generator` (rng.beta, rng.choice, rng.normal).

## Constants and configuration

- **Threshold table**: [`_patient_activator_thresholds.py`](_patient_activator_thresholds.py)
  — every scalar previously inline in `activator.py` lifted here
  (Issue #637). Named clusters include:
  - `BASELINE_{HR,SBP,DBP,RR,SPO2,TEMPERATURE}_*` — age / sex
    scaling, means, standard deviations, ceilings for the six
    vital-sign types.
  - `AGE_PENALTY_{MIN_AGE,SCALE,HEPATIC_RATIO}` — reserve
    depletion beyond `AGE_PENALTY_MIN_AGE`.
  - `RESERVE_FLOOR`, `IMMUNE_REACTIVITY_BETA_PARAMS` —
    physiological-reserve sampling shape (the shared reserve Beta,
    `_RESERVE_BETA_PARAMS = (30, 2)`, lives in `activator.py`).
  - `DRUG_METABOLISM_{LABELS,JP_PROBS,US_PROBS}` — country-varying
    poor / normal / rapid / ultra_rapid probability vector.
  - `DELIRIUM_{BETA_PARAMS,ELDERLY_AGE_THRESHOLD,ELDERLY_PREMIUM,DEMENTIA_PREMIUM,PARKINSON_PREMIUM}`
    — delirium-risk model.
  - `DVT_{BETA_PARAMS,ELDERLY_AGE_THRESHOLD,ELDERLY_PREMIUM}` — DVT
    susceptibility.
  - `CHRONIC_{ONSET_YEAR_MIN,ONSET_YEAR_MAX_EXCLUSIVE,ONSET_MONTH_MIN,…}`
    — chronic-condition onset date sampling.
  - `CHRONIC_{CONTROLLED_PROBABILITY,SEVERITY_MILD_PROBABILITY}`.
- **Stage + severity tables**: [`_severity_activation.py`](_severity_activation.py)
  (Issue #637 PR-D) —
  - Per-condition stage weight tuples (e.g. CKD, NYHA, GOLD),
    validated at import to sum to 1.0.
  - `STAGE_SEVERITY: dict[str, dict[str, float]]` — per condition
    code, maps a stage text to a `[0.0, 1.0]` severity score consumed by
    [`clinosim.modules.physiology.engine.initialize_state`](../physiology/README.md).
    Scores above each condition's severe-threshold (defined in
    `clinosim/modules/physiology/_coupling_coefficients.py`) fire
    the "severe" physiology branch.
- **Test-patient fixture**: [`test_patient.py`](test_patient.py) —
  `create_test_patient()` returns a deterministic 72-year-old JP
  female with hypertension + type-2 diabetes; used by legacy
  v0.1-alpha tests that need a stable patient without booting the
  full population module.

## Directory contents

```
clinosim/modules/patient/
  __init__.py                          empty
  activator.py                         activate_patient orchestrator (~1150 LOC)
  _patient_activator_thresholds.py     named thresholds (586 LOC, Issue #637)
  _severity_activation.py              chronic-condition stage + severity tables (Issue #637 PR-D)
  test_patient.py                      deterministic create_test_patient() fixture
  SPEC.md                              extended design reference (not runtime)
```

The module has **no `enricher.py`, no `audit.py`, no
`reference_data/`** — the activator is called directly by the
simulator, chronic-medication data lives in `clinosim/locale/`, and
verification is via the tests below.

## Enricher wiring

Not applicable — this module is invoked directly by the simulator
when a person first needs a clinical profile, not through
`register_builtin_enrichers`. It has no seed offset in
`ENRICHER_SEED_OFFSETS`. The `activate_patient` call happens inside
the caller-owned cache keyed by `(person_id, as_of_year)` so
activation is exactly-once per key.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Patient cache | [`clinosim/simulator/_setup.py`](../../simulator/_setup.py) (`_activate_cached_person`) | Activates on cache miss; called from `_dispatch.py` and the `phases/` runners (`_readmission`, `_post_discharge`, `_healthcare_calendar`, `_ed_slot`). |
| Forced scenarios | [`clinosim/simulator/engine.py`](../../simulator/engine.py) (`~L387`) | Activates the synthetic `FORCED-NNNN` persons. |
| Enumeration path | [`clinosim/simulator/enumerate.py`](../../simulator/enumerate.py) (`~L581`, `~L647`) | Late-imports `activate_patient` for the enumeration entry point. |
| CLI single-encounter driver | [`clinosim/simulator/cli_test_encounter.py`](../../simulator/cli_test_encounter.py) (`~L14`, `~L110`, `~L190`) | Activates one patient at a time for smoke runs. |
| Outpatient encounter | [`clinosim/simulator/outpatient.py`](../../simulator/outpatient.py) | Uses `PatientProfile` fields set by the activator. |
| Types layer | [`clinosim/types/patient.py`](../../types/patient.py) | The activator populates every field on `PatientProfile` + child types. |

## Testing

```bash
pytest tests/unit -k "patient or activator" -q
pytest tests/integration -k "patient_cache" -q
```

Individual files:

- [`tests/unit/test_patient_profile.py`](../../../tests/unit/test_patient_profile.py)
  — `PatientProfile` type shape.
- [`tests/unit/test_patient_factory_fixture.py`](../../../tests/unit/test_patient_factory_fixture.py)
  — `create_test_patient()` fixture stability.
- [`tests/unit/test_patient_cache_current_meds_sync.py`](../../../tests/unit/test_patient_cache_current_meds_sync.py)
  — patient-cache home-medication sync (the "same patient across
  encounters carries the same meds" contract).
- [`tests/unit/test_activator_chronic_medications_exclusive.py`](../../../tests/unit/test_activator_chronic_medications_exclusive.py)
  — chronic-medication attachment is exclusive per disease.
- [`tests/integration/test_patient_cache_current_meds_carryforward.py`](../../../tests/integration/test_patient_cache_current_meds_carryforward.py)
  — cross-encounter cache carryforward end-to-end.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
