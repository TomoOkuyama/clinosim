# `clinosim.benchmarks` — early-warning baseline classifiers

## Purpose

`clinosim.benchmarks` extracts labels and computes baseline classifier
metrics for early-warning prediction tasks derived from clinosim-generated
cohorts. The baselines exist so that any external model claiming to
"predict sepsis" or "predict AKI" must exceed trivial rules to demonstrate
value.

Because clinosim generation is deterministic (AD-16), the baseline
metrics themselves are reproducible: same seed + same population →
byte-identical positive / negative distribution → identical baseline
scores.

## Scope

- **In scope**: label extractors for sepsis onset and AKI (KDIGO Stage 1+)
  onset during inpatient encounters, majority-class baseline,
  single-threshold rule baselines (lactate for sepsis, creatinine delta
  for AKI), AUROC computation on a single cohort.
- **Out of scope**: trained ML models (scikit-learn is a deferred optional
  dependency), cross-validation splits (single-cohort baselines are
  enough for the floor number), temporal feature engineering (early-
  window only), tasks other than sepsis / AKI (add via a new label
  extractor if needed).

## Public API

```python
from clinosim.benchmarks import (
    extract_sepsis_labels,      # (cif_dir) -> list[LabelRow]
    extract_aki_labels,         # (cif_dir) -> list[LabelRow]
    majority_baseline,          # (labels) -> BaselineReport
    lactate_threshold_baseline, # (labels, records) -> BaselineReport (sepsis)
    creatinine_delta_baseline,  # (labels, records) -> BaselineReport (AKI)
    compute_auroc,              # (y_true, y_score) -> float
)
```

`LabelRow` and `BaselineReport` are the label and result dataclasses;
see `types.py` for the exact schema.

## Dependencies

- `clinosim.types` for CIF record shapes.
- `pathlib`, standard library only; no external ML dependencies.

## Constants and configuration

- Sepsis-detection lactate threshold: currently inline in
  `sepsis.py` — flagged for extraction in
  [`docs/reviews/2026-08-09-constants-audit.md`](../../docs/reviews/2026-08-09-constants-audit.md).
- AKI-detection creatinine delta: KDIGO Stage 1 = ≥ 0.3 mg/dL rise
  within 48 h — currently inline in `aki.py`.
- No YAML configuration.

## Directory contents

```
clinosim/benchmarks/
  __init__.py           public API
  types.py              LabelRow, BaselineReport dataclasses
  harness.py            shared harness for baseline runners
  sepsis.py             sepsis label extractor + baselines
  aki.py                AKI label extractor + baselines
```

## Testing

```bash
pytest tests/unit -k benchmarks -q
```

Approximately 1 test file references `clinosim.benchmarks`. Coverage
is deliberately light because the baselines are stable numerical
identities; the meaningful test is that they run to completion on any
generated cohort and produce the same AUROC given the same seed.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).
