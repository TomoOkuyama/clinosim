"""P2-15 benchmark harness (session 48).

Provides label extractors + baseline classifiers for common early-warning
prediction tasks derived from clinosim-generated CIF:

- **sepsis**: onset of sepsis condition during an inpatient encounter
- **aki**: onset of AKI (KDIGO Stage 1+) during an inpatient encounter

The purpose is to establish reproducible baseline metrics that any external
model must exceed to demonstrate value beyond trivial rules. clinosim's
determinism (AD-16) means a fixed seed + population produces the same
positive/negative distribution across runs, so the baseline itself is
reproducible.

Public entry points:

- :func:`extract_sepsis_labels`(cif_dir) -> list[LabelRow]
- :func:`extract_aki_labels`(cif_dir) -> list[LabelRow]
- :func:`majority_baseline`(labels) -> BaselineReport
- :func:`lactate_threshold_baseline`(labels, records) -> BaselineReport (sepsis-only)
- :func:`creatinine_delta_baseline`(labels, records) -> BaselineReport (aki-only)
- :func:`compute_auroc`(y_true, y_score) -> float

Not included (intentional scope):
- Trained ML models (scikit-learn optional dep, deferred)
- Cross-validation splits (single-cohort baseline is enough for floor number)
- Temporal features (early-window only; complex encoders deferred)
"""

from clinosim.benchmarks.harness import (
    BaselineReport,
    LabelRow,
    compute_auroc,
    majority_baseline,
)
from clinosim.benchmarks.sepsis import (
    extract_sepsis_labels,
    lactate_threshold_baseline,
)
from clinosim.benchmarks.aki import (
    creatinine_delta_baseline,
    extract_aki_labels,
)

__all__ = [
    "BaselineReport",
    "LabelRow",
    "compute_auroc",
    "majority_baseline",
    "extract_sepsis_labels",
    "lactate_threshold_baseline",
    "extract_aki_labels",
    "creatinine_delta_baseline",
]
