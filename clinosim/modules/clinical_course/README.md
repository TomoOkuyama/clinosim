# `clinosim.modules.clinical_course` — trajectory archetype + daily-directive engine

## Purpose

Owns the day-scale clinical trajectory: chooses one of the disease
YAML's `course_archetypes` (e.g. `smooth_recovery`,
`gradual_deterioration`, `sudden_deterioration`,
`treatment_resistant`) at admission time, evaluates the day-by-day
`StateChangeDirective` that
[`clinosim.modules.physiology`](../physiology/README.md) applies to
the state vector, evaluates complications with disease-scoped risk
conditions, and adjusts trajectory for diagnosis-effectiveness
feedback. Where `physiology` decides "what the state means right
now", `clinical_course` decides "how the state should move over
the next day".

## Scope

- **In scope**: `select_archetype` (YAML archetype probabilities —
  or the built-in fallback table — + severity-tier multipliers +
  per-disease `archetype_modifiers` patient-risk adjustments,
  everything normalised through
  `normalize_probabilities(fallback="raise")`);
  `get_daily_directive` (trajectory interpolation with age-based
  speed / time stretch, treatment-sensitivity recovery scaling,
  immune-reactivity amplitude modulation and optional daily noise);
  `evaluate_complications` (per-complication onset window, parent
  cascade, per-day probability and `risk_factors` multipliers resolved
  by `_evaluate_risk_condition` against the vocabulary in
  `_complication_risk_conditions.py` — age / sex / severity /
  immobility / state-variable thresholds / ICD aliases / stay-context
  conditions, Issue #2093); `compute_diagnosis_effectiveness` +
  `apply_diagnosis_modifier` (diagnosis-driven correction back into
  the trajectory); `natural_recovery_directive` (small baseline
  innate-recovery directive added to the archetype directive every
  day); load-time validators for the `course_archetypes`,
  `archetype_modifiers` and `complications[].risk_factors` sections
  of disease YAMLs.
- **Out of scope**: state-vector semantics + coupling
  ([`clinosim.modules.physiology`](../physiology/README.md)); disease
  YAML schema itself
  ([`clinosim.modules.disease`](../disease/README.md)); encounter
  timeline ([`clinosim.modules.encounter`](../encounter/README.md));
  daily loop mechanics
  ([`clinosim.simulator.daily_loop`](../../simulator/daily_loop.py)).

## Public API

`__init__.py` is empty; consumers import from `engine.py`:

```python
from clinosim.modules.clinical_course.engine import (
    select_archetype,                # (severity, profile, rng, protocol_archetypes=None, protocol_modifiers=None, patient=None) -> archetype_name
    get_daily_directive,             # (archetype_name, day, profile, protocol_archetypes=None, age=70, rng=None) -> StateChangeDirective
    evaluate_complications,          # (day, state, patient, complications, active_complications, rng, severity="moderate", context=None) -> list[dict]
    compute_diagnosis_effectiveness, # (working_diagnosis, ground_truth_disease, diagnosis_confidence, day, diagnostic_difficulty=0.3) -> float
    apply_diagnosis_modifier,        # (directive, effectiveness, current_volume=0.0, current_ph=0.0) -> StateChangeDirective
    natural_recovery_directive,      # (day, disease_id, severity, profile, treatment_effectiveness=1.0) -> StateChangeDirective
    validate_complication_risk_factors,  # (disease_id, complications) -> None — fail-loud vocabulary check
    is_supported_risk_condition,     # (condition) -> bool
)
from clinosim.modules.clinical_course._complication_risk_conditions import (
    ComplicationContext,             # stay context (drugs / devices / procedures) for context risk factors
    DRUG_CLASSES,
)
```

## Determinism

- No sub-seed offset in `ENRICHER_SEED_OFFSETS`. All entry points
  are pure with respect to the `rng` argument the caller provides;
  the encounter simulator (`inpatient.py`) derives a per-encounter
  sub-RNG before calling.
- Archetype selection uses `rng.choice(names, p=weights)` with
  `normalize_probabilities(fallback="raise")` — a zero-sum weight
  vector raises rather than silently biasing the draw.
- Daily-directive interpolation is deterministic in
  `(archetype, day, age, profile)` when `rng` is `None`. When the
  caller passes `rng` (the daily loop always does), every trajectory
  variable draws proportional noise plus a ~10% "bump day"
  perturbation; iteration order over `TRAJECTORY_STATE_VARS` is
  load-bearing for RNG reproducibility.
- `evaluate_complications` draws one `rng.random()` per eligible
  (not yet active, in onset window, parent satisfied) complication.

## Dependencies

- `clinosim.modules._shared` — `normalize_probabilities`
  (with `fallback="raise"`).
- `clinosim.modules.clinical_course._archetype_modifiers` —
  per-archetype / per-severity multiplier constants
  (Issue #637 refactor).
- `clinosim.modules.clinical_course._clinical_course_thresholds` —
  residual thresholds not covered by `_archetype_modifiers.py`
  (Issue #637 refactor).
- `clinosim.modules.clinical_course._complication_risk_conditions` —
  complication risk-factor vocabulary + `ComplicationContext`
  (Issue #2093).
- `clinosim.modules.disease.severity` — `EVALUABLE_CONDITIONS` /
  `_evaluate_condition` (patient-level risk-factor vocabulary).
- `clinosim.modules.physiology.engine` — `canonical_state_vars`.
- `clinosim.types.clinical` — `StateChangeDirective`.
- `clinosim.types.patient` — `PatientPhysiologicalProfile`.
- `numpy` — `np.random.Generator`; `yaml`.

## Constants and configuration

- **Fallback archetype table**
  ([`reference_data/fallback_archetypes.yaml`](reference_data/fallback_archetypes.yaml),
  loaded into `engine._FALLBACK_TRAJECTORIES` /
  `_FALLBACK_PROBABILITIES`): six archetypes (`smooth_recovery` 0.55,
  `dip_then_recovery` 0.20, `plateau_then_recovery` 0.10,
  `treatment_resistant` 0.08, `gradual_deterioration` 0.05,
  `sudden_deterioration` 0.02) — the single source of truth for
  baseline probabilities and trajectories when a disease YAML omits
  `course_archetypes`. Severity multiplier logic
  sources baselines here, never re-typing them inline — this
  eliminates the drift risk when the fallback dict is re-tuned.
- **Archetype-shape modifiers** ([`_archetype_modifiers.py`](_archetype_modifiers.py),
  Issue #637):
  - `SEVERE_{GRADUAL,SUDDEN}_DETERIORATION_MULT`,
    `SEVERE_SMOOTH_RECOVERY_MULT`,
    `MILD_{SMOOTH_RECOVERY,GRADUAL_DETERIORATION,SUDDEN_DETERIORATION}_MULT`
    — severity-tier multipliers applied on top of the fallback
    baseline (or the YAML-provided baseline).
  - `AGE_SPEED_FACTOR_BANDS`, `AGE_SPEED_FACTORS` — age-banded
    recovery-speed factor.
  - `AGED_DETERIORATION_AMPLIFIER_BASE` — deterioration amplifier
    baseline for elderly patients.
  - `IMMUNE_REACTIVITY_SCALE` — inflammation amplitude divisor.
  - `TRAJECTORY_NOISE_PROP_SCALE`, `TRAJECTORY_NOISE_FLOOR` — daily
    noise.
- **Residual thresholds** ([`_clinical_course_thresholds.py`](_clinical_course_thresholds.py),
  Issue #637): `ARCHETYPE_PROBABILITY_DEFAULT` /
  `ARCHETYPE_WEIGHT_FLOOR` (default and floor for missing archetype
  probability), bump-day noise, complication defaults,
  diagnosis-effectiveness coefficients, natural-recovery / anemia /
  symptom-axis recovery rates.
- **Complication risk-factor vocabulary**
  ([`_complication_risk_conditions.py`](_complication_risk_conditions.py),
  Issue #2093): `PATIENT_CONDITIONS` (the internal value sets in `codes/data/valuesets.yaml`, shared with the severity modifiers), `STATE_ALIASES`,
  `SEVERITY_ALIASES`, `CONTEXT_RESOLVED` (resolved from
  `ComplicationContext`), `CONTEXT_CONDITIONS` (declared but evaluate
  False), `DRUG_CLASSES`.
- **Load-time validators** (`_validate_course_archetypes`,
  `_validate_archetype_modifiers`, `validate_complication_risk_factors`,
  called from `clinosim/modules/disease/protocol.py`) fail loud when a
  disease YAML uses an unknown trajectory state variable, references an
  unknown archetype name, ships a modifier with a malformed
  `condition` string, or uses an unknown complication risk factor —
  silent-no-op prevention.

## Directory contents

```
clinosim/modules/clinical_course/
  __init__.py                        empty
  engine.py                          select_archetype / get_daily_directive / evaluate_complications / diagnosis feedback
  _archetype_modifiers.py            severity + age multiplier constants (Issue #637)
  _clinical_course_thresholds.py     residual threshold constants (Issue #637)
  _complication_risk_conditions.py   complication risk-factor vocabulary + ComplicationContext (Issue #2093)
  reference_data/
    fallback_archetypes.yaml         six built-in archetypes (trajectory + probability)
  SPEC.md                            extended design reference (not runtime)
```

The module has **no `enricher.py`, no `audit.py`** — per-disease
archetype data lives in the disease YAML
(`clinosim/modules/disease/reference_data/`).

## Enricher wiring

Not applicable — this module is invoked imperatively by the
encounter simulator, not through `register_builtin_enrichers`. It
has no seed offset in `ENRICHER_SEED_OFFSETS`.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) (`~L12`, `~L643`) | Calls `select_archetype` at admission, writes the result to `encounter.clinical_course_archetype`. |
| Daily loop | [`clinosim/simulator/daily_loop.py`](../../simulator/daily_loop.py) (`~L21`) | Calls `get_daily_directive` → `compute_diagnosis_effectiveness` / `apply_diagnosis_modifier` → `natural_recovery_directive` per admission day and feeds the summed directive into `physiology.update`; calls `evaluate_complications` with a `ComplicationContext`. |
| Disease-protocol integration | [`clinosim/modules/disease/protocol.py`](../disease/protocol.py) | Load-time runs `_validate_archetype_modifiers`, `_validate_course_archetypes` and `validate_complication_risk_factors` on every disease YAML. |

## Testing

```bash
pytest tests/unit -k "clinical_course or diagnosis_feedback" -q
```

Individual files:

- [`tests/unit/test_clinical_course.py`](../../../tests/unit/test_clinical_course.py)
  — `select_archetype` distribution + `get_daily_directive`
  determinism.
- [`tests/unit/test_diagnosis_feedback.py`](../../../tests/unit/test_diagnosis_feedback.py)
  — `compute_diagnosis_effectiveness` +
  `apply_diagnosis_modifier` correction.
- [`tests/unit/modules/clinical_course/`](../../../tests/unit/modules/clinical_course/)
  — module-scoped unit tests (`archetype_modifiers`).
- [`tests/unit/test_complication_risk_factors.py`](../../../tests/unit/test_complication_risk_factors.py),
  [`tests/unit/test_context_risk_factors.py`](../../../tests/unit/test_context_risk_factors.py)
  — risk-factor vocabulary / context resolution (Issue #2093).
- [`tests/unit/test_symptom_recovery_effectiveness.py`](../../../tests/unit/test_symptom_recovery_effectiveness.py)
  — `natural_recovery_directive` symptom-axis scaling (Issue #2097).

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
