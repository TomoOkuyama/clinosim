# patient

Patient profile creation. In v0.1-alpha, provides a hardcoded test patient. In later versions, activates Layer 1 population records to full Layer 2 clinical profiles.

## Public API

```python
from clinosim.modules.patient.test_patient import create_test_patient

patient = create_test_patient()  # returns PatientProfile (72F, HT+DM, for pneumonia testing)
```

### `create_test_patient() -> PatientProfile`
Returns a hardcoded 72-year-old Japanese female with hypertension and diabetes. Designed as a realistic pneumonia patient for v0.1-alpha testing.

## Dependencies
- `clinosim.types.patient` (PatientProfile, PatientPhysiologicalProfile, etc.)

## Testing
```bash
source .venv/bin/activate && python -m pytest tests/unit/test_patient.py -v
```

## Implementation status
- [x] Hardcoded test patient for v0.1-alpha
- [ ] Layer 1 → Layer 2 activation (from population)
- [ ] Returning patient reactivation
- [ ] Body metrics generation (age/sex/country-based)
- [ ] Physiological profile generation algorithm
- [ ] Baseline vitals derivation
- [ ] Allergy profile generation
- [ ] Current medications assignment
