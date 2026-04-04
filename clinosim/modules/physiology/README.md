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
