# clinical_course

Clinical course archetype engine. Selects a trajectory pattern for each patient and generates daily state change directives.

## Public API

```python
from clinosim.modules.clinical_course.engine import (
    select_archetype,                # (severity, profile, rng) -> archetype name
    get_daily_directive,             # (archetype, day, profile) -> StateChangeDirective
    compute_diagnosis_effectiveness, # (working_dx, ground_truth, confidence, day) -> float
    apply_diagnosis_modifier,        # (directive, effectiveness) -> modified directive
    natural_recovery_directive,      # (day, disease_id, severity, profile) -> directive
    evaluate_complications,          # (day, state, patient, ...) -> list[dict]
)
```

### `select_archetype(severity, profile, rng) -> str`
Selects one of 6 archetypes based on disease severity and patient's physiological profile. Severe patients are more likely to deteriorate; high treatment sensitivity favors smooth recovery.

### `get_daily_directive(archetype_name, day, profile) -> StateChangeDirective`
Returns daily deltas for state variables (inflammation, volume, renal, perfusion) interpolated from archetype trajectory, modulated by patient's immune reactivity and treatment sensitivity.

## Archetypes

| Name | Probability | Pattern |
|---|---|---|
| smooth_recovery | 55% | Steady improvement from Day 1-2 |
| dip_then_recovery | 20% | Worsening Day 1-3, then gradual improvement |
| plateau_then_recovery | 10% | No change 3-5 days, then improvement |
| treatment_resistant | 8% | No response to first-line, requires change Day 3-5 |
| gradual_deterioration | 5% | Slow worsening → ICU |
| sudden_deterioration | 2% | Sudden spike Day 2 (sepsis/PE) |

## YAML-driven archetypes

Archetype trajectories are read from the `course_archetypes` section of each disease's
protocol YAML (e.g. `clinosim/modules/disease/reference_data/bacterial_pneumonia.yaml`).
Both `select_archetype()` and `get_daily_directive()` accept an optional
`protocol_archetypes` dict; when it is provided the YAML definitions take precedence over
the built-in fallbacks.

Expected YAML structure under `course_archetypes`:

```yaml
course_archetypes:
  smooth_recovery:
    probability: 0.55
    trajectory:
      inflammation_level: {0: 0.05, 1: -0.02, 3: -0.08, 7: -0.06, 14: -0.02}
      volume_status:      {0: 0.02, 3: 0.02, 7: 0.01}
  sudden_deterioration:
    probability: 0.02
    trajectory:
      inflammation_level: {0: 0.05, 2: 0.30, 5: -0.05}
      perfusion_status:   {0: 0.00, 2: -0.30, 5: 0.05}
```

Each trajectory key is a day number (int); values are the **daily delta** applied to that
state variable on that day. Days between defined points are linearly interpolated by
`_interpolate()`.

### How to add a custom archetype

1. Add a new entry under `course_archetypes` in the disease YAML. The name must be unique
   within that disease.
2. Provide at minimum a `probability` (float, 0–1) and a `trajectory` dict with at least
   one state variable.
3. All probabilities across archetypes are **normalized** at runtime, so they do not need
   to sum to 1.0 exactly.
4. If the new archetype should also be available as a built-in fallback (i.e. when no YAML
   is loaded), add it to `_FALLBACK_TRAJECTORIES` and `_FALLBACK_PROBABILITIES` in
   `engine.py`.

### How complications are evaluated

`evaluate_complications(day, state, patient, complications, active_complications, rng)`
iterates over the `complications` list (typically sourced from the disease YAML) on each
hospital day:

- A complication is skipped if it is already in `active_complications`.
- It fires only if `day` falls within `onset_day_range: [start, end]`.
- **Cascade complications** specify a `parent_complication` name; the parent must be in
  `active_complications` before the child can trigger.
- Base probability is `probability_per_day` (independent) or
  `probability_given_parent` (cascade).
- Risk factor conditions in the `risk_factors` list (e.g. `"age_over_75"`,
  `"renal_function < 0.4"`) are evaluated against the current `PhysiologicalState` and
  patient object; each matching condition multiplies the probability by its `multiplier`.
- Triggered complications are added to `active_complications` and returned as a list of
  dicts that callers should apply to the physiological state.

## Dependencies
- `clinosim.types.clinical` (StateChangeDirective)
- `clinosim.types.patient` (PatientPhysiologicalProfile)

## Testing
```bash
source .venv/bin/activate && python -m pytest tests/unit/test_clinical_course.py -v
```
13 tests covering: archetype selection, daily directives, interpolation, severity/profile modifiers.

## Diagnosis-treatment feedback

`compute_diagnosis_effectiveness()` calculates how effective treatment is based on diagnostic accuracy. When the working diagnosis is wrong, recovery deltas are dampened via `apply_diagnosis_modifier()`, causing slower CRP decline and prolonged inflammation — leaving traceable footprints in the data.

`diagnostic_difficulty` (0.0-1.0) is read from each disease YAML's `diagnostic` section:
- 0.05: Hip fracture (X-ray confirms instantly)
- 0.25: UTI (urinalysis + culture)
- 0.30: Pneumonia (CXR + culture, moderate)
- 0.35: HF exacerbation (BNP useful but overlaps with pneumonia)
- 0.40: COPD exacerbation (overlaps with pneumonia and HF)

## Natural recovery

`natural_recovery_directive()` adds small baseline healing independent of treatment. Models innate immune response and homeostatic regulation. Scaled by `immune_reactivity` and severity.

## Implementation status
- [x] All 6 archetypes (YAML-driven with hardcoded fallback)
- [x] Severity-dependent selection probability
- [x] Patient profile modulation (immune reactivity, treatment sensitivity)
- [x] Linear interpolation between day points
- [x] Diagnosis-treatment feedback loop
- [x] Natural recovery model
- [x] Diagnostic difficulty per disease (YAML-driven)
- [x] Complication cascade with risk factor evaluation
- [x] Treatment change triggers (Day 3 antibiotic switch etc.)
