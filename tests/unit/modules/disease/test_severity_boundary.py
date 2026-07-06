"""FP-SEV-MODEL Task 1: the canonical category<->score boundary.

SEVERITY_SCORE_RANGES and category_from_score must agree exactly so a uniform
draw inside a category's range re-derives that category (round-trip stability).
"""

import pytest

from clinosim.modules.disease.severity import (
    SEVERITY_CATEGORIES,
    SEVERITY_SCORE_RANGES,
    category_from_score,
)

pytestmark = pytest.mark.unit


def test_categories_and_ranges_consistent():
    assert SEVERITY_CATEGORIES == ("mild", "moderate", "severe")
    assert SEVERITY_SCORE_RANGES["mild"] == (0.0, 0.3)
    assert SEVERITY_SCORE_RANGES["moderate"] == (0.3, 0.7)
    assert SEVERITY_SCORE_RANGES["severe"] == (0.7, 1.0)


@pytest.mark.parametrize(
    "score,cat",
    [
        (0.0, "mild"),
        (0.29, "mild"),
        (0.3, "moderate"),
        (0.5, "moderate"),
        (0.69, "moderate"),
        (0.7, "severe"),
        (0.99, "severe"),
        (1.0, "severe"),
    ],
)
def test_category_from_score_boundaries(score, cat):
    assert category_from_score(score) == cat


def test_every_range_maps_back_to_its_category():
    for cat, (lo, _hi) in SEVERITY_SCORE_RANGES.items():
        assert category_from_score(lo) == cat
