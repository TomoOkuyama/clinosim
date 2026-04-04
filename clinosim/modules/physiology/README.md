# physiology

Core realism engine. Manages hidden physiological state variables and derives all observable values (lab results, vital signs) from them.

## Public API

```python
from clinosim.modules.physiology.engine import (
    initialize_state,
    apply_disease_onset,
    update,
    apply_coupling_rules,
    derive_lab_values,
    derive_vital_signs,
)
```

### `initialize_state(profile, conditions, patient_id) -> PhysiologicalState`
Creates initial state from patient's organ reserves and chronic conditions.

### `apply_disease_onset(state, severity, initial_impact) -> PhysiologicalState`
Applies the acute impact of a disease (e.g., pneumonia raises inflammation, causes dehydration).

### `update(state, directive, time_step) -> PhysiologicalState`
Advances the state by one time step. Applies daily deltas scaled to the step size, then runs coupling rules.

### `apply_coupling_rules(state) -> None`
Propagates physiological dependencies between state variables (e.g., low perfusion → renal injury → acidosis).

### `derive_lab_values(state, sex, age, ...) -> dict[str, float]`
Converts hidden state into observable lab values (CRP, WBC, creatinine, etc.). Returns "true" values before noise.

### `derive_vital_signs(state, baseline, timestamp) -> dict[str, float]`
Converts hidden state into vital signs (temperature, HR, BP, RR, SpO2) with circadian variation.

## State variables

| Variable | Range | What it represents |
|---|---|---|
| `inflammation_level` | 0–1 | Systemic inflammation (drives CRP, WBC, PCT) |
| `renal_function` | 0–1 | Kidney function (drives creatinine, BUN, K, eGFR) |
| `cardiac_function` | 0–1 | Heart pump function (drives BNP, perfusion) |
| `hepatic_function` | 0–1 | Liver function (drives AST, ALT, bilirubin, PT-INR) |
| `anemia_level` | 0–1 | Anemia severity (drives Hb, Hct) |
| `coagulation_status` | 0–1 | Coagulopathy (drives PT-INR, platelets, D-dimer) |
| `volume_status` | -1 to +1 | Fluid balance (dehydration ↔ overload) |
| `perfusion_status` | 0–1 | Tissue perfusion (drives lactate, BP) |
| `ph_status` | -1 to +1 | Acid-base balance (drives pH, HCO3, pCO2) |

## Coupling dependency graph
```
cardiac_function --> perfusion_status --> renal_function --> ph_status
                          ^
                    volume_status
inflammation_level --> coagulation_status <-- hepatic_function
                  +--> anemia_level (slow)
```

## How to add a new state variable

1. Add the field to `PhysiologicalState` in `clinosim/types/clinical.py`:
   ```python
   new_variable: float = 0.0
   ```
2. Register its valid range in `_variable_range()` in `engine.py`:
   ```python
   "new_variable": (0.0, 1.0),
   ```
3. If it has a baseline value derived from the patient profile, initialize it inside
   `initialize_state()`, mirroring how `renal_function` is set from `profile.renal_reserve`.
4. If it influences or is influenced by other variables, add the coupling logic in
   `apply_coupling_rules()`. Follow the pattern: check a threshold, compute a delta, apply
   with `clamp()`.
5. If the variable should be observable, add a derivation formula in `derive_lab_values()`
   or `derive_vital_signs()` (see below).
6. Update `StateChangeDirective` handling in `get_daily_directive()` (clinical_course
   module) — add the new variable name to the `for var_name in [...]` list so YAML
   trajectories can target it.

## How to add a new lab derivation formula

All lab derivation lives in `derive_lab_values()` in `engine.py`. Each formula maps one or
more hidden state variables to an observable analyte value. Steps:

1. Add a new entry inside the function body, assigning to `labs["AnalyteName"]`:
   ```python
   # Example: derive a fictional marker driven by hepatic function
   labs["ALT_ratio"] = max(0.0, (1 - hepatic) * 80 + infl * 20)
   ```
   Reference variables already in scope: `infl`, `renal`, `cardiac`, `hepatic`, `anemia`,
   `perfusion`, `ph`, plus the raw `state` object for anything else.
2. Add the analyte to the observation module's `BIOLOGICAL_CV`, `ANALYTICAL_CV`, and
   `PRECISION` dicts so the noise pipeline can process it.
3. Add reference ranges to `determine_flag()` in `clinosim/modules/observation/engine.py`
   if H/L/critical flagging is required.
4. Optionally add the analyte to the expected lab distributions in the relevant disease
   YAML for benchmarking.

## Dependencies
- `clinosim.types.clinical` (PhysiologicalState, StateChangeDirective)
- `clinosim.types.patient` (PatientPhysiologicalProfile, BaselineVitals)

## Testing
```bash
source .venv/bin/activate && python -m pytest tests/unit/test_physiology.py -v
```
16 tests covering: initialization, disease onset, state update, coupling rules, lab derivation, vital signs.

## Implementation status
- [x] 9 state variables with initialization
- [x] Disease onset impact application
- [x] Time-stepping update with scaling
- [x] Inter-variable coupling rules (perfusion→renal→pH, inflammation→DIC, etc.)
- [x] Lab value derivation (20+ analytes)
- [x] Vital sign derivation with circadian variation
- [x] 16 unit tests passing
- [ ] Temporal lag model for lab markers (CRP 24-48h delay, etc.)
- [ ] Intervention immediate effects (fluid bolus, vasopressor, etc.)
- [ ] Pregnancy physiological adjustments
- [ ] Pediatric reference ranges
