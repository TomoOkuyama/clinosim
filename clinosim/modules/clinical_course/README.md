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

- **In scope**: `select_archetype` (YAML archetype probabilities +
  severity-tier multipliers + per-disease `archetype_modifiers`
  patient-risk adjustments + age / immune-reactivity /
  treatment-sensitivity speed factors, everything normalised through
  `normalize_probabilities(fallback="raise")`);
  `get_daily_directive` (age-scaled trajectory interpolation with
  immune-reactivity amplitude modulation);
  `evaluate_complications` (per-archetype risk conditions with
  `_evaluate_risk_condition` DSL for chronic-condition / age / lab
  triggers); `compute_diagnosis_effectiveness` +
  `apply_diagnosis_modifier` (diagnosis-driven correction back into
  the trajectory); `natural_recovery_directive` (fallback path);
  import-time validators for `course_archetypes` +
  `archetype_modifiers` sections of disease YAMLs.
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
    evaluate_complications,          # (archetype_name, day, patient, protocol_archetypes, rng) -> list[complication]
    compute_diagnosis_effectiveness, # (encounter, ...) -> effectiveness score
    apply_diagnosis_modifier,        # (directive, effectiveness, ...) -> StateChangeDirective
    natural_recovery_directive,      # fallback directive when the archetype lookup fails
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
  `(archetype, day, age, immune_reactivity)`; the `rng` argument is
  optional and only consumed on `sudden_deterioration`-style
  archetypes where a stochastic event is intentional.

## Dependencies

- `clinosim.modules._shared` — `normalize_probabilities`
  (with `fallback="raise"`).
- `clinosim.modules.clinical_course._archetype_modifiers` —
  per-archetype / per-severity multiplier constants
  (Issue #637 refactor).
- `clinosim.modules.clinical_course._clinical_course_thresholds` —
  residual thresholds not covered by `_archetype_modifiers.py`
  (Issue #637 refactor).
- `clinosim.types.clinical` — `StateChangeDirective`,
  `PatientPhysiologicalProfile`.
- `numpy` — `np.random.Generator`.

## Constants and configuration

- **Fallback archetype table** (`engine.py`): `_FALLBACK_PROBABILITIES`
  is the single source of truth for baseline probabilities when a
  disease YAML omits `course_archetypes`. Severity multiplier logic
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
  - `ARCHETYPE_PROBABILITY_DEFAULT`, `ARCHETYPE_WEIGHT_FLOOR` —
    default and floor for missing archetype probability.
- **Residual thresholds** ([`_clinical_course_thresholds.py`](_clinical_course_thresholds.py),
  Issue #637): constants from `evaluate_complications`,
  `compute_diagnosis_effectiveness`, `_interpolate` that don't fit
  the archetype-modifier bucket.
- **Load-time validators** (`_validate_course_archetypes` +
  `_validate_archetype_modifiers`) fail loud when a disease YAML
  references an unknown archetype name or ships a modifier with a
  malformed `condition` string — silent-no-op prevention.

## Directory contents

```
clinosim/modules/clinical_course/
  __init__.py                        empty
  engine.py                          select_archetype / get_daily_directive / evaluate_complications / diagnosis feedback
  _archetype_modifiers.py            severity + age multiplier constants (Issue #637)
  _clinical_course_thresholds.py     residual threshold constants (Issue #637)
  SPEC.md                            extended design reference (not runtime)
```

The module has **no `enricher.py`, no `audit.py`, no
`reference_data/`** — archetype data lives in the disease YAML
(`clinosim/modules/disease/reference_data/*.yaml`).

## Enricher wiring

Not applicable — this module is invoked imperatively by the
encounter simulator, not through `register_builtin_enrichers`. It
has no seed offset in `ENRICHER_SEED_OFFSETS`.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) (`~L12`, `~L252`) | Calls `select_archetype` at admission, writes the result to `encounter.clinical_course_archetype`. |
| Daily loop | [`clinosim/simulator/daily_loop.py`](../../simulator/daily_loop.py) (`~L21`) | Calls `get_daily_directive` + `evaluate_complications` per admission day; feeds the directive into `physiology.update`. |
| Disease-protocol integration | [`clinosim/modules/disease/protocol.py`](../disease/protocol.py) | Load-time cross-validates that YAML `archetype_modifiers.condition` tokens resolve. |

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
  — module-scoped unit tests.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
