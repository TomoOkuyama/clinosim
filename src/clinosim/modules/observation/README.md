# observation

Layer 3 of the observation engine: measurement noise, biological variation, and result flagging. Physiology module provides the "true" value; this module makes it realistic.

## Public API

```python
from clinosim.modules.observation.engine import (
    apply_realistic_variability,
    round_to_precision,
    generate_lab_result,
    determine_flag,
)
```

### `generate_lab_result(lab_name, true_value, rng) -> float`
Full pipeline: biological variation (CVi) + analytical variation (CVa) + rounding.

### `determine_flag(lab_name, value, sex) -> str | None`
Returns `"H"`, `"L"`, `"critical"`, or `None` based on reference ranges.

### Key data tables
- `BIOLOGICAL_CV` — 30+ analytes, from Ricos et al. desirable variation database
- `ANALYTICAL_CV` — 30+ analytes, typical modern analyzer imprecision
- `PRECISION` — reporting decimal places per analyte

## Dependencies
- None (standalone — uses only numpy for random sampling)

## Testing
```bash
source .venv/bin/activate && python -m pytest tests/unit/test_observation.py -v
```

## Implementation status
- [x] 3-layer variability model (CVi + CVa)
- [x] Reporting precision per analyte
- [x] H/L/critical flagging with reference ranges
- [x] Panic value detection (K > 6.5, Hb < 7, etc.)
- [ ] Pre-analytical variation (tourniquet, posture, processing delay)
- [ ] Context-dependent missingness (night, refusal, difficult draw)
- [ ] Explainable anomaly patterns (hemolysis, IV contamination)
- [ ] Pregnancy-specific reference ranges
