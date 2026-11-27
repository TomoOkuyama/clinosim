# clinical_course — Clinical Course Engine

## Purpose
Determine the trajectory of a patient's clinical course by selecting a course archetype and driving physiological state variable changes over time (via the physiology module). Handles both the primary disease trajectory and complication cascades.

## Inputs
- `PatientProfile`: Individual-difference parameters (treatment sensitivity, reserves)
- `DiseaseEvent`: Disease type, severity
- `DiseaseProtocol`: Expected course patterns and trigger conditions
- `DiagnosticDecision`: Current working diagnosis (may change over time)
- `TreatmentPlan`: Active treatments and their expected effects
- `HealthcareSystemConfig`: Discharge criteria, LOS targets

## Outputs
- `StateChangeDirective`: Instructions to the physiology module for state variable updates at each time step
- `ClinicalEvent`: Discrete events (fever resolution, complication onset, ICU transfer, discharge)
- `CourseArchetype`: Selected archetype for the patient's trajectory

## Dependencies
- `patient` (individual-difference parameters)
- `disease` (course pattern definitions)
- `diagnosis` (current working diagnosis)
- `treatment` (active treatment effects)
- `physiology` (reads current state, writes state changes)
- `healthcare_system` (discharge criteria)

## Confirmed Specifications

### Clinical course archetypes

| Archetype | Probability | Description |
|---|---|---|
| `smooth_recovery` | 55% | Steady improvement |
| `dip_then_recovery` | 20% | Temporary worsening then improvement (nadir around Day 2) |
| `plateau_then_recovery` | 10% | Plateau phase then improvement |
| `treatment_resistant` | 8% | No response to initial treatment; change required |
| `gradual_deterioration` | 5% | Slow worsening → ICU transfer |
| `sudden_deterioration` | 2% | Sudden critical worsening |

### Unknown-change generation strategy (priority order)

```
Priority 1: Can it be explained by known pathophysiology?
  → YES: Generate via Layer 1–2 rules

Priority 2: Can it be explained by individual-difference parameters?
  → YES: Adjust via PatientPhysiologicalProfile

Priority 3: Does it match a known clinical pattern (archetype)?
  → YES: Select from archetypes

Priority 4: Purely "unknown" change
  → Constrained stochastic generation (rate limits, mutual exclusion)
    + assign an "explainable anomaly" pattern
```

## Open Questions
- [ ] Treatment effect probability model: binary (effective/ineffective) or continuous improvement curve? (global open #3)
- [ ] Discharge/transfer/death outcome model details (global open #8)
- [ ] How archetype selection interacts with individual-difference parameters

## Design Notes

> **Implementation status.** There is no single `evaluate()` entry
> point and no `interpolate_state_trajectory()`. The daily loop
> (`clinosim/simulator/daily_loop.py`) calls `get_daily_directive`
> (which interpolates the YAML `trajectory` with the private
> `_interpolate`), `compute_diagnosis_effectiveness` /
> `apply_diagnosis_modifier`, `natural_recovery_directive` and
> `evaluate_complications` separately; `trigger_orders` are not
> evaluated by this module. See [`README.md`](README.md).

### Call timing (from encounter module)
- `evaluate()`: Called during daily morning rounds. Takes current `PhysiologicalState` + `TreatmentPlan` + `DifferentialDiagnosis` and produces `StateChangeDirective` for the next 24 hours.
- The archetype determines the trajectory shape; the individual-difference parameters (from patient module) modulate the amplitude and timing.
- The encounter module checks the resulting state against discharge criteria and deterioration thresholds to decide the next encounter state (continue treatment / discharge planning / ICU transfer).

### Input from disease module
- Disease protocol YAML defines `course_archetypes` with `state_trajectory` (day-by-day deltas for each state variable)
- `archetype_modifiers` adjust selection probabilities based on patient profile (immune_reactivity, age, treatment_sensitivity)
- The clinical_course module uses `interpolate_state_trajectory()` (defined in disease SPEC) to compute state deltas between key days
- `trigger_orders` conditions are evaluated by clinical_course during `evaluate()`: if a trigger fires (e.g., "Day 3, inflammation still high"), clinical_course informs encounter, which then places the trigger's orders
- Treatment change events (from treatment module) can alter the trajectory: if antibiotic is escalated, the archetype may shift from "treatment_resistant" path to a "recovery" path from that point forward

### Open question resolved
- Treatment effect model: **continuous**, not binary. The disease protocol's `state_trajectory` defines continuous daily deltas, modulated by `treatment_sensitivity`. This is the answer to global open #3.

## Treatment response of deteriorating courses (Issue #3838)

A `gradual_deterioration` or `treatment_resistant` trajectory is authored for its first days; its last value used to be held for ever, so an open-ended rising tail kept the inflammation, and with it the temperature, high for weeks. `reference_data/treatment_response.yaml` names the turn: from the last treatment change of the archetype (`treatment_modifications`; for an archetype without any, its last authored trajectory day) plus `response_delay_days`, the inflammation delta is at most `resolution_inflammation_delta` per day (an authored recovery that is faster is kept). Before that day the course deteriorates as authored. The inflammation a complication adds (`state_impact.inflammation_level`) is held in full for the same delay and then released at the same rate (`clinosim/simulator/sustained_complication.py`), so it does not outlast its treatment.

## Course speed per disease and severity (Issue #3931)

The `course_archetypes` trajectories and the daily natural recovery were authored on the Japanese stay length (`target_los.japan`), which includes days a recovered patient is kept for the practice. A patient becomes clinically stable around the US target length of stay (US practice discharges at stability), so `reference_data/course_time_scale.yaml` holds, per disease and severity, how many times faster than authored the course runs: `target_los.japan mean / target_los.us mean`, bounded by `min_scale` / `max_scale`. The scale is the same in every country (a test keeps the table equal to that ratio). `course_time_scale(disease_id, severity)` returns it (1.0 when absent); `get_daily_directive` reads the trajectory at `day * scale` and multiplies each delta by the scale, `natural_recovery_directive` multiplies the inflammation, volume and symptom-axis recovery by it, so the total change of the course is kept and only its duration shortens; the marrow recovery of the anemia axis is not scaled. Order of magnitude: Halm et al., JAMA 1998;279:1452-7, median time to clinical stability of community-acquired pneumonia 3 days (most lenient definition) to 7 days (most conservative).

Country practice is separate: `locale/<cc>/care_practice.yaml` `hold_stable_patient_to_sampled_target` (Japan true) keeps a clinically stable patient until the stay's sampled target length; the discharge gates (fever, perfusion, vasoactive wean, renal) hold an unstable patient in both countries.
