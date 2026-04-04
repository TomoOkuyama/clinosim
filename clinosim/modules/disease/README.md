# disease

Disease protocol definitions and loader. Each disease is a YAML file containing incidence rates, severity distribution, clinical course archetypes, lab/treatment protocols, and outcome benchmarks.

## Public API

```python
from clinosim.modules.disease.protocol import load_disease_protocol, DiseaseProtocol

protocol = load_disease_protocol("bacterial_pneumonia")  # returns DiseaseProtocol
```

### `load_disease_protocol(disease_id: str) -> DiseaseProtocol`
Loads and validates a disease protocol YAML.

### `DiseaseProtocol`
Pydantic model containing all disease-specific configuration:
- `incidence` — age/sex rates, risk multipliers, seasonal curve
- `severity` — distribution and modifiers
- `course_archetypes` — state trajectories per archetype
- `initial_state_impact` — how disease changes physiological state at onset
- `order_protocols` — admission orders, daily monitoring, triggers
- `diagnostic` — differential priors, likelihood ratios
- `drugs` — first-line, alternatives, escalation, discharge meds
- `outcome_benchmarks` — validation targets (LOS, mortality, readmission)

## Dependencies
- `clinosim.types` (Pydantic models)

## Protocol files
- `modules/disease/reference_data/bacterial_pneumonia.yaml` — Phase 1 (complete)
- `modules/disease/reference_data/heart_failure_exacerbation.yaml` — Phase 1 (not yet)
- `modules/disease/reference_data/hip_fracture.yaml` — Phase 1 (not yet)

## Adding a new disease
1. Create `modules/disease/reference_data/{disease_id}.yaml`
2. Follow the schema in `modules/disease/SPEC.md`
3. No code changes needed — the engine loads any valid YAML

## Testing
```bash
source .venv/bin/activate && python -m pytest tests/unit/test_disease.py -v
```

## Implementation status
- [x] Protocol loader with Pydantic validation
- [x] Bacterial pneumonia reference data (full)
- [ ] Heart failure exacerbation reference data
- [ ] Hip fracture reference data
- [ ] Severity determination algorithm
- [ ] Archetype selection algorithm
