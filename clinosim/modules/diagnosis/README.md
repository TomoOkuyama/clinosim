# diagnosis

Bayesian differential diagnosis engine. Maintains a probability distribution over candidate diagnoses, updates via likelihood ratios as test results arrive, and tracks diagnosis code progression.

## Public API

```python
from clinosim.modules.diagnosis.engine import (
    initialize_differential,   # (disease_id, age) -> DifferentialDiagnosis
    update_differential,       # (diff, findings) -> DifferentialDiagnosis
    get_current_diagnosis_code,  # (diff) -> (icd_code, display_name)
)
```

### `initialize_differential(disease_id, age) -> DifferentialDiagnosis`
Creates initial differential with default priors. Age-adjusted (elderly → higher HF probability).

### `update_differential(diff, findings, threshold) -> DifferentialDiagnosis`
Bayesian update: each finding applies its positive/negative LR to each candidate's probability, then normalizes. Confirms diagnosis when top candidate exceeds threshold (default 90%).

### `get_current_diagnosis_code(diff) -> (str, str)`
Returns ICD code that progresses from unspecified → specific as confidence increases:
- `< 0.5`: R05 (no working diagnosis)
- `0.5–0.7`: J18.9 (pneumonia, unspecified)
- `0.7–0.9`: J18.1 (lobar pneumonia)
- `>= 0.9`: J13 (pneumonia due to S. pneumoniae)

## Dependencies
- None (standalone)

## Testing
```bash
source .venv/bin/activate && python -m pytest tests/unit/test_diagnosis.py -v
```
6 tests covering: initialization, Bayesian update, confirmation, negative findings, code progression, probability normalization.

## Implementation status
- [x] Bayesian differential with 7 candidate diseases
- [x] Likelihood ratio table (4 findings × multiple diseases)
- [x] Diagnosis code progression (unspecified → specific)
- [x] Age-adjusted priors
- [x] 6 unit tests passing
- [ ] Full LR table from disease YAML
- [ ] Diagnostic drift (misdiagnosis, dual pathology, incidental findings)
- [ ] Therapeutic trial evaluation
