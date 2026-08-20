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
disease profile, insurance selection, and JP kana / romaji name
formatting. The simulator calls it once per patient — the returned
profile is what every downstream encounter simulator consumes.

## Scope

- **In scope**: `activate_patient(person, rng, demo)` orchestrator,
  height + weight (with age-based shrinkage past 60),
  `PatientPhysiologicalProfile` fields (immune / metabolism / renal /
  cardiac / hepatic reserves with `AGE_PENALTY_*` scaling),
  age-and-sex scaled baseline vitals (all four BP / HR / RR / SpO₂
  / temperature), delirium-risk beta parameters (with elderly +
  dementia premium), chronic-condition activation with `_generate_stage`
  weighted stage sampling and `STAGE_SEVERITY` score lookup
  (Issue #637 PR-D refactor), home-medication derivation from the
  disease profile, insurance sampling per country / age, JP romaji
  name generation. Also a deterministic
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
# (person: PersonRecord, rng: np.random.Generator, demo: dict) -> PatientProfile

from clinosim.modules.patient.test_patient import create_test_patient
# () -> PatientProfile  (deterministic 72-year-old JP female with HT + T2DM)
```

The stage / severity model in `_severity_activation.py` is imported
by `activator.py` and re-exported for callers that need the tables
directly:

```python
from clinosim.modules.patient.activator import (
    STAGE_SEVERITY,           # {stage_text: severity_score in [0.0, 1.0]}
    # …stage-weight tuples per chronic-condition ICD…
)
```

## Determinism

- **No sub-seed offset in `ENRICHER_SEED_OFFSETS`**. This module is
  invoked by the simulator inside the population pass with an
  explicit `rng` argument, so per-patient determinism is the
  caller's contract; a patient cache keyed by `person_id` guarantees
  each patient is activated exactly once per run (see
  `simulator/engine.py:399-410`).
- Chronic-condition stage sampling uses `rng.choice(p=…)` with weight
  vectors validated to sum to 1.0 at import (see
  `_severity_activation.py`); swapping the previously-inline literals
  for the named tuples is byte-diff clean.
- Home-medication attachment is deterministic given (patient, disease
  profile) — no additional RNG draws.

## Dependencies

- `clinosim.modules._shared` — `is_jp`, `normalize_probabilities`,
  `resolve_lang`.
- `clinosim.modules.patient._patient_activator_thresholds` — 586 LOC
  of named baseline / reserve / delirium / chronic-condition
  thresholds (Issue #637 sweep).
- `clinosim.modules.patient._severity_activation` — per-condition
  stage weight vectors + `STAGE_SEVERITY` score table.
- `clinosim.modules.physiology.engine` — `hba1c_from_glycemic_control`
  (used at HbA1c derivation time).
- `clinosim.modules.population.engine` — `PersonRecord` +
  `_sample_given_name` (name-formatting reuse).
- `clinosim.locale.loader` — `load_names(country)` for kana / romaji
  formatting.
- `clinosim.types.patient` — `PatientProfile`,
  `PatientPhysiologicalProfile`, `BaselineVitals`, `HomeMedication`,
  `ChronicCondition`.
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
  - `RESERVE_FLOOR`, `_RESERVE_BETA_PARAMS`,
    `IMMUNE_REACTIVITY_BETA_PARAMS` — physiological-reserve
    sampling shape.
  - `DRUG_METABOLISM_{LABELS,JP_PROBS,US_PROBS}` — country-varying
    fast / normal / slow probability vector.
  - `DELIRIUM_{BETA_PARAMS,ELDERLY_AGE_THRESHOLD,ELDERLY_PREMIUM,DEMENTIA_PREMIUM}`
    — delirium-risk model.
  - `CHRONIC_{ONSET_YEAR_MIN,ONSET_YEAR_MAX_EXCLUSIVE,ONSET_MONTH_MIN,…}`
    — chronic-condition onset date sampling.
  - `CHRONIC_{CONTROLLED_PROBABILITY,SEVERITY_MILD_PROBABILITY}`.
- **Stage + severity tables**: [`_severity_activation.py`](_severity_activation.py)
  (Issue #637 PR-D) —
  - Per-condition stage weight tuples (e.g. CKD, NYHA, GOLD),
    validated at import to sum to 1.0.
  - `STAGE_SEVERITY: dict[str, float]` — maps a stage text to a
    `[0.0, 1.0]` severity score consumed by
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
  activator.py                         activate_patient orchestrator (629 LOC)
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
during the population pass, not through `register_builtin_enrichers`.
It has no seed offset in `ENRICHER_SEED_OFFSETS`. The `activate_patient`
call happens per patient inside a caller-owned cache keyed by
`person_id` so activation is exactly-once per run.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Simulator boot | [`clinosim/simulator/engine.py`](../../simulator/engine.py) (`~L19`, `~L399-410`, `~L970`) | Activates every population member into the patient cache before per-encounter simulation; re-activates for `unknown_condition` walkthroughs. |
| Enumeration path | [`clinosim/simulator/enumerate.py`](../../simulator/enumerate.py) (`~L581`, `~L647`) | Late-imports `activate_patient` for the enumeration entry point. |
| CLI single-encounter driver | [`clinosim/simulator/cli_test_encounter.py`](../../simulator/cli_test_encounter.py) (`~L15`, `~L111`, `~L191`) | Activates one patient at a time for smoke runs. |
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
