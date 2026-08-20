# `clinosim.modules.diagnosis` — Bayesian differential-diagnosis engine

## Purpose

Maintains a Bayesian differential diagnosis over an encounter's
timeline: initialises a per-encounter differential from disease-YAML
priors, updates candidate probabilities as new labs / vitals /
imaging results arrive (likelihood-ratio Bayesian update), and
resolves a current working / confirmed / discharge diagnosis code.
Also owns the named canonical constants for non-specific / fallback
ICD-10 codes (Issue #551 sweep) that used to be inlined at half a
dozen sites.

## Scope

- **In scope**: `initialize_differential` (seed from disease
  protocol `differential` block); `update_differential`
  (likelihood-ratio update per new observation); `get_current_diagnosis_code`
  (returns the highest-probability candidate or the
  `UNRESOLVED_DIAGNOSIS_ICD` sentinel when no candidate crosses the
  working-diagnosis threshold); named non-specific / fallback
  codes (`UNRESOLVED_DIAGNOSIS_ICD = "R69"`, `ICD_COUGH = "R05"`,
  extension slots for R50.9 / R53.1 / R68.8 / Z09).
- **Out of scope**: disease-protocol definitions
  ([`clinosim.modules.disease`](../disease/README.md)); the ICD /
  SNOMED code registries ([`clinosim/codes/`](../../codes/)); FHIR
  `Condition` / `ClinicalImpression` emission
  ([`clinosim.modules.output`](../output/README.md)); diagnosis
  feedback into trajectory (that runs in
  [`clinosim.modules.clinical_course`](../clinical_course/README.md)).

## Public API

`__init__.py` is empty; consumers import directly from the two
submodules:

```python
from clinosim.modules.diagnosis.engine import (
    initialize_differential,         # (encounter, protocol) -> DifferentialDiagnosis
    update_differential,             # (diff, observation, ...) -> None
    get_current_diagnosis_code,      # (diff) -> ICD-10 code str
)
from clinosim.modules.diagnosis.nonspecific_codes import (
    UNRESOLVED_DIAGNOSIS_ICD,        # "R69"
    ICD_COUGH,                       # "R05" — real symptom, NEVER a wrong-dx sentinel
)
from clinosim.modules.diagnosis._diagnosis_thresholds import (
    WORKING_DIAGNOSIS_MIN_PROB,      # 0.5 — "more likely than not" cutoff
    # …plus confirmed-diagnosis cutoff + age priors + neutral LR fallbacks…
)
```

## Determinism

Not applicable — the module makes no random draws. Differential
initialisation and Bayesian updates are pure functions of the
observation stream + prior probabilities. `get_current_diagnosis_code`
is a deterministic argmax over the differential map.

## Dependencies

- `clinosim.modules._shared` — `get_attr_or_key`.
- `clinosim.modules.diagnosis._diagnosis_thresholds` — every
  working / confirmed cutoff, age-prior adjustment, neutral-LR
  fallback (Issue #637).
- `clinosim.modules.diagnosis.nonspecific_codes` — Issue #551 named
  fallback / non-specific ICD-10 constants.
- `clinosim.types.diagnosis` — `DifferentialDiagnosis`,
  `DifferentialCandidate`.
- `yaml`.

## Constants and configuration

- **Thresholds** ([`_diagnosis_thresholds.py`](_diagnosis_thresholds.py),
  Issue #637 sweep):
  - Family 1 — working / confirmed cutoffs
    (`WORKING_DIAGNOSIS_MIN_PROB = 0.5` — "more likely than not";
    confirmed cutoff pins the threshold above which the differential
    freezes).
  - Family 2 — age-based prior adjustments (elderly patients get a
    lifted prior on age-associated conditions).
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
  — built-in differential library keyed by chief-complaint pattern
  (fallback when a disease YAML omits its `differential` block).

## Directory contents

```
clinosim/modules/diagnosis/
  __init__.py                    empty
  engine.py                      initialize_differential + update_differential + get_current_diagnosis_code
  nonspecific_codes.py           Issue #551 named ICD-10 fallback constants
  _diagnosis_thresholds.py       working / confirmed cutoffs + age priors + neutral LR fallbacks (Issue #637)
  reference_data/
    builtin_differentials.yaml   built-in differential library
  SPEC.md                        extended design reference (not runtime)
```

The module has **no `enricher.py`, no `audit.py`**.

## Enricher wiring

Not applicable — this module is invoked imperatively by the encounter
simulator, not through `register_builtin_enrichers`. It has no seed
offset in `ENRICHER_SEED_OFFSETS`.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) | Calls `initialize_differential` at admission + `get_current_diagnosis_code` at discharge time. |
| Daily loop | [`clinosim/simulator/daily_loop.py`](../../simulator/daily_loop.py) | Calls `update_differential` per new observation. |
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

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
