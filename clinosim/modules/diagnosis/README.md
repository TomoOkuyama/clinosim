# `clinosim.modules.diagnosis` — Bayesian differential-diagnosis engine

## Purpose

Maintains a Bayesian differential diagnosis over an encounter's
timeline: initialises a per-encounter differential from disease-YAML
priors, updates candidate probabilities as new labs / vitals /
imaging results arrive (likelihood-ratio Bayesian update), and
resolves a current working / confirmed / discharge diagnosis code.
Also owns the named canonical constants for non-specific / fallback
ICD-10 codes (Issue #551 sweep) that used to be inlined at half a
dozen sites, the ICD-10 code-class predicates the FHIR emit layer
gates on (Z-chapter visit-reason codes, never-principal codes), and
one RNG-free POST_ENCOUNTER enricher that appends a lab-derived AKI
(N17.9) working diagnosis (`lab_derived_dx.py`, Issue #1326).

## Scope

- **In scope**: `initialize_differential` (seed from the disease
  protocol's `diagnostic.differential` list, falling back to the
  built-in table keyed by disease id); `update_differential`
  (likelihood-ratio update per batch of `(finding, is_positive)`
  findings); `get_current_diagnosis_code` (resolves the working
  diagnosis — or the top candidate when none is set — through the
  confidence-keyed `diagnosis_progression` table, skips candidates
  sex-locked for the patient (Issue #947), and returns the
  `UNRESOLVED_DIAGNOSIS_ICD` sentinel when nothing resolves); named
  non-specific / fallback codes (`UNRESOLVED_DIAGNOSIS_ICD = "R69"`,
  `ICD_COUGH = "R05"`; R50.9 / R53.1 / R68.8 / Z09 are tracked for a
  follow-up sweep and not yet extracted); ICD-10 predicates
  `is_visit_reason_zcode` (Issue #916), `is_never_principal_dx`
  (Issue #2157) and `encounter_primary_dx_code` (Issue #1215); the
  `lab_derived_dx` enricher (Creatinine peak >= 4.0 mg/dL on an
  inpatient encounter with no N17.x and no CKD 4-5 / ESRD baseline
  → N17.9 `working_diagnoses` entry).
- **Out of scope**: disease-protocol definitions
  ([`clinosim.modules.disease`](../disease/README.md)); the ICD /
  SNOMED code registries ([`clinosim/codes/`](../../codes/)); FHIR
  `Condition` / `ClinicalImpression` emission
  ([`clinosim.modules.output`](../output/README.md)); diagnosis
  feedback into trajectory (that runs in
  [`clinosim.modules.clinical_course`](../clinical_course/README.md)).

## Public API

`__init__.py` is empty; consumers import directly from the
submodules:

```python
from clinosim.modules.diagnosis.engine import (
    initialize_differential,         # (disease_id, age, protocol_diagnostic=None) -> DifferentialDiagnosis
    update_differential,             # (diff, findings, confirmation_threshold=0.90, protocol_lr_table=None) -> DifferentialDiagnosis
    get_current_diagnosis_code,      # (diff, protocol_progression=None, patient_sex=None) -> (icd_code, display)
)
from clinosim.modules.diagnosis.nonspecific_codes import (
    UNRESOLVED_DIAGNOSIS_ICD,        # "R69"
    ICD_COUGH,                       # "R05" — real symptom, NEVER a wrong-dx sentinel
    is_visit_reason_zcode,           # (code) -> bool — Z-chapter visit-reason (Issue #916)
    is_never_principal_dx,           # (code) -> bool — Z37 / R65 (Issue #2157)
    encounter_primary_dx_code,       # (record_dict, encounter_id) -> str (Issue #1215)
)
from clinosim.modules.diagnosis.lab_derived_dx import (
    enrich_lab_derived_dx,           # POST_ENCOUNTER enricher (Issue #1326)
)
from clinosim.modules.diagnosis._diagnosis_thresholds import (
    WORKING_DIAGNOSIS_MIN_PROB,      # 0.5 — "more likely than not" cutoff
    # …plus DEFAULT_CONFIRMATION_THRESHOLD (0.90), ELDERLY_HF_PRIOR_AGE_THRESHOLD (75),
    # ELDERLY_HF_PRIOR_MULTIPLIER (1.5), NEUTRAL_LIKELIHOOD_RATIO (1.0)…
)
```

## Determinism

Not applicable — the module makes no random draws. Differential
initialisation and Bayesian updates are pure functions of the
observation stream + prior probabilities. `get_current_diagnosis_code`
is a deterministic walk over the probability-sorted candidate list.
`enrich_lab_derived_dx` is a pure lab-value walk (no RNG, no seed
offset).

## Dependencies

- `clinosim.codes` — `lookup` (ICD-10-CM display resolution).
- `clinosim.simulator.sex_gating` — `is_sex_locked_for`,
  `pick_sex_compatible_dx_code` (lazy import, only when
  `patient_sex` is passed).
- `clinosim.simulator.enrichers` — `EnricherContext`
  (`lab_derived_dx.py`).
- `clinosim.modules.diagnosis._diagnosis_thresholds` — every
  working / confirmed cutoff, age-prior adjustment, neutral-LR
  fallback (Issue #637).
- `clinosim.modules.diagnosis.nonspecific_codes` — Issue #551 named
  fallback / non-specific ICD-10 constants.
- `clinosim.types.diagnosis` — `DifferentialDiagnosis`,
  `DiagnosisCandidate`.
- `yaml`.

## Constants and configuration

- **Thresholds** ([`_diagnosis_thresholds.py`](_diagnosis_thresholds.py),
  Issue #637 sweep):
  - Family 1 — working / confirmed cutoffs
    (`WORKING_DIAGNOSIS_MIN_PROB = 0.5` — "more likely than not";
    `DEFAULT_CONFIRMATION_THRESHOLD = 0.90` — top candidate at or
    above it sets `diff.confirmed = True`).
  - Family 2 — age-based prior adjustment (age >=
    `ELDERLY_HF_PRIOR_AGE_THRESHOLD = 75` multiplies the
    `heart_failure` prior by `ELDERLY_HF_PRIOR_MULTIPLIER = 1.5`
    before normalisation).
  - Family 3 — neutral fallbacks for missing likelihood-ratio
    entries (extracted so the Bayesian neutrality is grep-able
    rather than hidden inside a `dict.get(default=1.0)`).
- **Non-specific codes** ([`nonspecific_codes.py`](nonspecific_codes.py),
  Issue #551): named constants that quote the ICD-10 title verbatim so a
  rename triggers an `ImportError` rather than silent drift. The
  file docstring documents the historical `R05` (Cough) vs `R69`
  (Ill-defined and unknown cause) confusion that used to silently
  mark legitimate cough presentations as wrong-diagnosis.
- **Reference data**:
  [`reference_data/builtin_differentials.yaml`](reference_data/builtin_differentials.yaml)
  — built-in tables keyed by disease id: `differentials`,
  `diagnosis_progression` and `lr_table` (fallbacks when the disease
  YAML omits its `diagnostic.differential` / progression / LR data;
  an unknown disease id falls back to the `bacterial_pneumonia`
  differential).
- **Lab-derived AKI** ([`lab_derived_dx.py`](lab_derived_dx.py)):
  `CREATININE_KDIGO_STAGE3_ABSOLUTE_MG_DL = 4.0`,
  `LAB_DERIVED_AKI_DIAGNOSIS_CODE = "N17.9"`, source tag
  `lab_derived_aki_kdigo_stage3`.

## Directory contents

```
clinosim/modules/diagnosis/
  __init__.py                    empty
  engine.py                      initialize_differential + update_differential + get_current_diagnosis_code
  nonspecific_codes.py           Issue #551 named ICD-10 fallback constants
  _diagnosis_thresholds.py       working / confirmed cutoffs + age priors + neutral LR fallbacks (Issue #637)
  lab_derived_dx.py              POST_ENCOUNTER enricher: Creatinine peak -> N17.9 working dx (Issue #1326)
  reference_data/
    builtin_differentials.yaml   built-in differential library
  SPEC.md                        extended design reference (not runtime)
```

The module has **no `enricher.py`, no `audit.py`** (its one enricher
lives in `lab_derived_dx.py`).

## Enricher wiring

The differential engine is invoked imperatively by the encounter
simulator. `register_builtin_enrichers`
([`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py))
registers one enricher from this module:

| Name | Stage | Order | Seed offset |
|---|---|---|---|
| `lab_derived_dx` | `POST_ENCOUNTER` | 94 (ties with `nursing_assignment`; sorted by name → runs first) | none (RNG-free) |

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) | Calls `initialize_differential` at admission + `get_current_diagnosis_code` at discharge time. |
| Daily loop | [`clinosim/simulator/daily_loop.py`](../../simulator/daily_loop.py) | Calls `update_differential` per new observation. |
| FHIR Condition / Encounter / Procedure emit | [`clinosim/modules/output/fhir_r4/`](../output/fhir_r4/) (`conditions/conditions.py`, `encounters/encounter.py`, `procedures/procedures.py`, `procedures/oxygen_therapy.py`, `lib/inline_bb.py`) | Gate on `is_visit_reason_zcode` / `is_never_principal_dx` / `encounter_primary_dx_code`. |
| FHIR Condition emit | `working_diagnoses` walker in `conditions/conditions.py` | Renders the N17.9 entry appended by `lab_derived_dx`. |
| Wall-clock sentinel test | [`tests/unit/test_wallclock_sentinel_defaults.py`](../../../tests/unit/test_wallclock_sentinel_defaults.py) | Imports the `DifferentialDiagnosis` sentinel defaults. |

## Testing

```bash
pytest tests/unit -k "diagnosis or r05_cough" -q
```

Individual files:

- [`tests/unit/test_diagnosis.py`](../../../tests/unit/test_diagnosis.py)
  — `initialize_differential` + `update_differential` behaviour.
- [`tests/unit/test_diagnosis_code_coverage.py`](../../../tests/unit/test_diagnosis_code_coverage.py)
  — differential ICD-code coverage.
- [`tests/unit/test_diagnosis_code_mapping.py`](../../../tests/unit/test_diagnosis_code_mapping.py)
  — code → display mapping.
- [`tests/unit/test_diagnosis_feedback.py`](../../../tests/unit/test_diagnosis_feedback.py)
  — diagnosis feedback into
  `clinosim.modules.clinical_course` (cross-module integration).
- [`tests/unit/test_types_diagnosis.py`](../../../tests/unit/test_types_diagnosis.py)
  — dataclass shape.
- [`tests/unit/simulator/test_r05_cough_not_wrong_diagnosis.py`](../../../tests/unit/simulator/test_r05_cough_not_wrong_diagnosis.py)
  — Issue #551 guard: an `R05` (Cough) presentation MUST NOT be
  marked as a wrong diagnosis by simply comparing to a stale
  sentinel.
- [`tests/unit/test_lab_derived_dx_1326.py`](../../../tests/unit/test_lab_derived_dx_1326.py)
  — `lab_derived_dx` enricher.
- `tests/unit/output/test_fhir_condition_zcode_visit_reason_916.py`,
  `test_principal_dx_ranking_2157.py`,
  `test_fhir_encounter_reason_code_per_encounter_1215.py` —
  `nonspecific_codes` predicates at the FHIR emit layer.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
