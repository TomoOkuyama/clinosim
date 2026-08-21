# `clinosim.benchmarks` — early-warning baseline classifiers

## Purpose

`clinosim.benchmarks` extracts labels and computes baseline classifier
metrics for early-warning prediction tasks derived from
clinosim-generated cohorts. The baselines exist so that any external
model claiming to "predict sepsis" or "predict AKI" must exceed
trivial rules to demonstrate value beyond a majority-class guess or a
single-threshold rule.

Because clinosim generation is deterministic (AD-16), the baseline
metrics themselves are reproducible: same seed + same population →
byte-identical positive / negative distribution → identical baseline
scores.

## Scope

- **In scope**: label extractors for sepsis onset and AKI onset during
  inpatient encounters (`extract_sepsis_labels`, `extract_aki_labels`);
  majority-class baseline (`majority_baseline`); single-threshold rule
  baselines (`lactate_threshold_baseline` for sepsis,
  `creatinine_delta_baseline` for AKI); a hand-rolled `compute_auroc`
  using the Mann-Whitney U interpretation.
- **Out of scope**: trained ML models (scikit-learn is a deferred
  optional dependency, currently unused), cross-validation splits
  (single-cohort baselines are enough for the floor number), temporal
  feature engineering (early-window only), tasks other than sepsis /
  AKI (add via a new label extractor + baseline pair if needed).

## Public API

```python
from clinosim.benchmarks import (
    extract_sepsis_labels,      # (cif_dir) -> list[LabelRow]
    extract_aki_labels,         # (cif_dir) -> list[LabelRow]
    majority_baseline,          # (labels) -> BaselineReport
    lactate_threshold_baseline, # (labels) -> BaselineReport (sepsis)
    creatinine_delta_baseline,  # (labels, threshold=0.3) -> BaselineReport (aki)
    compute_auroc,              # (y_true, y_score) -> float
    LabelRow, BaselineReport,   # dataclasses re-exported from harness.py
)
```

`add_benchmark_subparser` and `dispatch_benchmark` in `cli.py` wire
these into the top-level `clinosim` CLI, but are not re-exported at
package level.

## Determinism

Not applicable at import time — the package has no random draws. The
baselines are pure functions of the input labels: same labels → same
`BaselineReport`. Determinism of the underlying labels is inherited
from the cohort producer (`clinosim.simulator`, AD-16).

## Dependencies

- `numpy` — vectorised AUROC.
- Standard library `pathlib`, `dataclasses`, `argparse`, `typing`.
- **No external ML dependencies.** scikit-learn is intentionally not
  imported.

## Constants and configuration

- **Sepsis-detection lactate threshold** — currently inline in
  `sepsis.py::lactate_threshold_baseline`. Flagged for extraction in
  [`docs/reviews/2026-08-09-constants-audit.md`](../../docs/reviews/2026-08-09-constants-audit.md).
- **AKI-detection creatinine delta** — `creatinine_delta_baseline`
  takes a `threshold: float = 0.3` argument (mg/dL rise between the
  first-day baseline creatinine and the peak during the encounter).
  This is the KDIGO Stage 1 SCr criterion (≥ 0.3 mg/dL rise) — the
  KDIGO "1.5× baseline" variant is not applied because Stage 1 fires
  on either criterion, and 0.3 mg/dL is the tighter one at typical
  admission-baseline SCr values.
- **`compute_auroc` degenerate returns** —
  `pos.size == 0 or neg.size == 0` → `0.5` (documented as the
  Mann-Whitney U convention); empty input → `0.0` (caller must guard
  `n > 0`).
- **No YAML configuration.**

## Directory contents

```
clinosim/benchmarks/
  __init__.py           public API (8 exports)
  harness.py            LabelRow, BaselineReport dataclasses;
                        compute_auroc; majority_baseline
  sepsis.py             sepsis label extractor + lactate_threshold_baseline
  aki.py                AKI label extractor + creatinine_delta_baseline
  cli.py                `clinosim benchmark` subcommand
                        (add_benchmark_subparser / dispatch_benchmark)
```

## Testing

```bash
pytest tests/unit -k benchmarks -q
```

One test file references `clinosim.benchmarks`. Coverage is
deliberately light because the baselines are stable numerical
identities; the meaningful test is that they run to completion on any
generated cohort and produce the same AUROC given the same seed. When
adding a new benchmark task, add its own label extractor + baseline
pair + a one-shot test that pins the AUROC to the expected value on a
small deterministic cohort.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
