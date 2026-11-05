"""Issue #2674: 15-17-year-olds are high school students, not workers."""

from __future__ import annotations

import pytest

from clinosim import determinism
from clinosim.locale.loader import load_demographics
from clinosim.modules.population._identity import _sample_occupation

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("age", [15, 16, 17])
def test_a_teenager_is_a_high_school_student(country: str, age: int) -> None:
    demo = load_demographics(country)
    for seed in range(40):
        assert _sample_occupation(demo, age, "F", determinism.default_rng(seed)) == "high_school_student"


def test_the_draws_are_unchanged() -> None:
    """The stream is consumed exactly as before, so later draws do not move."""
    demo = load_demographics("US")
    rng_a, rng_b = determinism.default_rng(3), determinism.default_rng(3)
    _sample_occupation(demo, 16, "M", rng_a)
    _sample_occupation(demo, 19, "M", rng_b)  # an 18-21 draw: same shape
    assert rng_a.random() == rng_b.random()


def test_adults_are_unchanged() -> None:
    demo = load_demographics("US")
    assert _sample_occupation(demo, 70, "M", determinism.default_rng(1)) == "retired"
