"""Severity sampling + the canonical category<->score boundary (FP-SEV-MODEL, c2).

The disease module owns the severity distribution (disease-YAML ``severity.distribution``
+ ``modifiers``), so it owns severity sampling. This module is the SINGLE definition of
the mild/moderate/severe category boundary and the continuous score each category maps
to (used by the population-time hospitalization gate).
"""

from __future__ import annotations

SEVERITY_CATEGORIES: tuple[str, str, str] = ("mild", "moderate", "severe")

# Half-open ranges (upper-inclusive on severe). category_from_score is exactly
# consistent with these so a uniform draw inside a range re-derives its category.
SEVERITY_SCORE_RANGES: dict[str, tuple[float, float]] = {
    "mild": (0.0, 0.3),
    "moderate": (0.3, 0.7),
    "severe": (0.7, 1.0),
}


def category_from_score(score: float) -> str:
    """Map a continuous severity score in [0, 1] to its category."""
    if score >= 0.7:
        return "severe"
    if score >= 0.3:
        return "moderate"
    return "mild"
