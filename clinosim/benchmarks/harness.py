"""Benchmark harness — shared LabelRow / BaselineReport / AUROC."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LabelRow:
    """One record's benchmark label + minimum context.

    - patient_id / encounter_id: identifier for downstream joins
    - label: 0 (negative) or 1 (positive) — the prediction target
    - context: optional per-row payload (e.g. onset_day, first-window
      lab values) for baseline classifiers
    """

    patient_id: str
    encounter_id: str
    label: int
    context: dict


@dataclass(frozen=True)
class BaselineReport:
    """Baseline classifier result over a label set."""

    name: str
    n: int
    n_positive: int
    prevalence: float
    auroc: float
    accuracy: float
    positive_predicted_rate: float
    rationale: str


def compute_auroc(y_true: list[int], y_score: list[float]) -> float:
    """Numpy-based AUROC for binary labels + continuous score.

    Uses the Mann-Whitney U interpretation:
      AUROC = P(score_pos > score_neg) + 0.5 P(score_pos == score_neg).

    Degenerate returns:
      - all-positive or all-negative → 0.5
      - empty → 0.0 (silent fail avoided by caller n>0 gate)
    """
    y = np.asarray(y_true, dtype=int)
    s = np.asarray(y_score, dtype=float)
    if y.size == 0:
        return 0.0
    pos_scores = s[y == 1]
    neg_scores = s[y == 0]
    if pos_scores.size == 0 or neg_scores.size == 0:
        return 0.5
    # Vectorized Mann-Whitney U
    total = pos_scores.size * neg_scores.size
    greater = np.sum(pos_scores[:, None] > neg_scores[None, :])
    equal = np.sum(pos_scores[:, None] == neg_scores[None, :])
    return float((greater + 0.5 * equal) / total)


def majority_baseline(labels: list[LabelRow]) -> BaselineReport:
    """Predict the majority class for every row (floor number)."""
    if not labels:
        return BaselineReport(
            name="majority",
            n=0,
            n_positive=0,
            prevalence=0.0,
            auroc=0.0,
            accuracy=0.0,
            positive_predicted_rate=0.0,
            rationale="empty label set",
        )
    y = np.array([r.label for r in labels], dtype=int)
    n = y.size
    n_pos = int(y.sum())
    prevalence = float(n_pos / n)
    predict_positive = prevalence >= 0.5
    accuracy = float(n_pos / n) if predict_positive else float((n - n_pos) / n)
    # AUROC is undefined for constant predictions → 0.5 conventional floor
    auroc = 0.5
    return BaselineReport(
        name="majority",
        n=n,
        n_positive=n_pos,
        prevalence=prevalence,
        auroc=auroc,
        accuracy=accuracy,
        positive_predicted_rate=1.0 if predict_positive else 0.0,
        rationale=(
            "Predict majority class. Establishes the floor accuracy any "
            "informative model must exceed. AUROC is 0.5 (constant scorer)."
        ),
    )
