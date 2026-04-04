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

## How to add CV values for a new lab item

CV values are stored as module-level dicts in `engine.py`. Adding a new analyte requires
entries in all three tables:

```python
# 1. Within-individual biological variation (Ricos et al. or equivalent source)
BIOLOGICAL_CV["NewItem"] = 0.08   # 8%

# 2. Analytical imprecision (instrument specification or EQAS data)
ANALYTICAL_CV["NewItem"] = 0.04   # 4%

# 3. Reporting precision (number of decimal places)
PRECISION["NewItem"] = 1
```

Use the same key string (e.g. `"NewItem"`) in all three dicts and in whatever
`derive_lab_values()` formula produces it, so that `generate_lab_result()` can look it up.
If no entry exists in a dict, a default is applied (`CVi=5%`, `CVa=3%`, `decimals=1`).

## How to add new reference ranges

Reference ranges are checked in `determine_flag()`. The `defaults` dict inside that
function maps analyte name → sex-stratified or universal normal limits:

```python
defaults["NewItem"] = {"all": (lower, upper)}           # sex-independent
defaults["NewItem"] = {"M": (13.5, 17.5), "F": (11.5, 15.5)}  # sex-stratified
```

If the analyte needs panic-value detection (critical flag), add it to the `panic` dict:

```python
panic["NewItem"] = (critical_low, critical_high)   # use None to skip one side
```

External callers may also supply a `reference_ranges` dict to `determine_flag()` to
override the built-in defaults (e.g. for age-specific or pregnancy-specific ranges).

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
