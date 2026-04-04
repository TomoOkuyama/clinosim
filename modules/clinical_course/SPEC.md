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
